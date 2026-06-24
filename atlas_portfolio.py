"""
atlas_portfolio.py  —  Atlas v2 trade-management brain
============================================================================

This is the layer the original Atlas was MISSING. The engine (atlas_engine.py)
only scored tickers; it never decided how many shares to buy, whether a buy was
allowed, or when to sell. Those rules are HALF the validated edge.

Everything here matches `atlas_v2_validated_doctrine.md` exactly:

  POSITION SIZING
    shares = floor( (equity * RISK_PCT) / (entry - stop) )
    RISK_PCT = 1% for 4/4 BUY, 0.5% for 3/4 BUY (Small)
    single position capped at MAX_POS_PCT (20%) of equity

  ADMISSION (a new buy is blocked if ANY is true)
    - SPY is below its 50-day SMA (regime risk-off)
    - already MAX_POSITIONS (10) open
    - already MAX_PER_SECTOR (3) open in that ticker's sector
    - already hold the ticker
    - insufficient cash

  ENTRY TRIGGER  (pullback-to-EMA10)
    after a BUY signal, only enter when price has pulled back to within
    PULLBACK_TOL of the 10-day EMA (don't buy extended). Fill ~ EMA10.

  EXITS (run daily over open lots; calls atlas_db.close_trade)
    - hard stop:  price <= entry - 1.5*ATR
    - trailing:   +1R -> stop to breakeven; +2R -> stop to +1R
    - time exit:  > MAX_HOLD_DAYS (40) trading days open

This module is import-safe on the Mac (it reuses atlas_engine's data helpers).
It NEVER deletes data; sells go through the existing FIFO close_trade ledger.
"""

import os
import sys
import math
import json
import requests
from datetime import datetime, timezone, date, timedelta

sys.path.insert(0, "/Users/yasser/scripts")

import atlas_db
import atlas_account as acct
from atlas_time import current_et_market_date, add_trading_days

# Reuse the engine's data + indicator helpers so prices/ATR match exactly.
from atlas_engine import (
    get_massive_aggs,
    calculate_atr,
    check_regime,
    check_earnings_context,
    check_fundamentals,
    check_massive_indicators,
    evaluate_indicator_confluence,
    check_macro_context,
    check_fda_calendar,
    MASSIVE_API_KEY,
    MASSIVE_BASE,
    EODHD_API_KEY,
)

# =============================================================================
# VALIDATED PARAMETERS (see atlas_v2_validated_doctrine.md)
# =============================================================================
RISK_PCT_FULL = 0.01      # 1% equity risk for 4/4 BUY
RISK_PCT_HALF = 0.005     # 0.5% equity risk for 3/4 BUY (Small)
MAX_POS_PCT = 0.20        # cap any single position at 20% of equity
MAX_POSITIONS = 10        # max concurrent open positions
MAX_PER_SECTOR = 3        # max concurrent open positions per sector
ATR_STOP_MULT = 1.5       # hard stop = entry - 1.5*ATR
MAX_HOLD_DAYS = 40        # time exit
EMA_PERIOD = 10           # pullback entry reference
PULLBACK_TOL = 0.02       # in-band signal threshold: close <= 10-EMA +2% buys now
PULLBACK_FILL_TOL = 0.005  # armed pullback trigger: price <= 10-EMA +0.5%
PENDING_PULLBACK_DAYS = 3  # valid for 3 trading days
MAX_PULLBACK_ARM_PCT = 15.0  # >15% over EMA10 is too extended; no 3-day limit


try:
    from atlas_audit import log_api_call as _atlas_log_api_call
except Exception:
    _atlas_log_api_call = None

import time as _audit_time
_REQUESTS_GET = requests.get


def _audit_provider(endpoint):
    text = str(endpoint or "").lower()
    if "massive.com" in text or "polygon.io" in text:
        return "Massive"
    if "benzinga.com" in text:
        return "Benzinga"
    if "eodhd.com" in text:
        return "EODHD"
    return None


def _audit_get(url, *args, **kwargs):
    provider = _audit_provider(url)
    start = _audit_time.perf_counter()
    try:
        response = _REQUESTS_GET(url, *args, **kwargs)
        if provider and _atlas_log_api_call:
            try:
                latency_ms = int((_audit_time.perf_counter() - start) * 1000)
                status = getattr(response, "status_code", None)
                _atlas_log_api_call(provider, os.path.basename(__file__), sys._getframe(1).f_code.co_name,
                                    str(url), status, latency_ms,
                                    bool(status is not None and 200 <= int(status) < 400), None, None)
            except Exception:
                pass
        return response
    except Exception as e:
        if provider and _atlas_log_api_call:
            try:
                latency_ms = int((_audit_time.perf_counter() - start) * 1000)
                _atlas_log_api_call(provider, os.path.basename(__file__), sys._getframe(1).f_code.co_name,
                                    str(url), None, latency_ms, False, str(e)[:500], None)
            except Exception:
                pass
        raise

# Minimal static sector map for the common scout universe. Unknown tickers are
# treated as their own unique sector (so they never block each other). Extend
# freely — this is only used for the per-sector concentration cap.
BLOCKED_TRADE_TICKERS = {"SPY", "QQQ", "DIA"}  # regime/index benchmarks, not swing trades

SECTOR_MAP = {
    "NVDA": "Semis", "AMD": "Semis", "SMCI": "Semis", "AVGO": "Semis",
    "MU": "Semis", "INTC": "Semis", "QCOM": "Semis", "TSM": "Semis",
    "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech", "GOOG": "Tech",
    "META": "Tech", "ORCL": "Tech", "CRM": "Tech", "ADBE": "Tech",
    "AMZN": "Consumer", "TSLA": "Consumer", "NFLX": "Consumer",
    "HD": "Consumer", "NKE": "Consumer", "SBUX": "Consumer",
    "COIN": "Financials", "JPM": "Financials", "GS": "Financials",
    "MS": "Financials", "V": "Financials", "MA": "Financials",
    "PLTR": "Software", "SNOW": "Software", "CRWD": "Software",
    "NOW": "Software", "PANW": "Software", "DDOG": "Software",
    "LLY": "Health", "UNH": "Health", "JNJ": "Health", "PFE": "Health",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
}


def sector_of(ticker):
    return SECTOR_MAP.get(ticker.upper(), f"_solo_{ticker.upper()}")


# --------------------------------------------------------------------------- #
# Price / indicator helpers (reuse engine fetch)
# --------------------------------------------------------------------------- #
def _live_price_lookup(ticker):
    """Return current/last intraday price from Massive snapshot; None if unavailable."""
    if not MASSIVE_API_KEY:
        return None
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            params={"apiKey": MASSIVE_API_KEY}, headers={"Accept": "application/json"}, timeout=5,
        )
        if r.status_code != 200:
            return None
        t = (r.json() or {}).get("ticker") or {}
        for section, key in (("lastTrade", "p"), ("min", "c"), ("day", "c")):
            value = (t.get(section) or {}).get(key)
            if value:
                return float(value)
    except Exception:
        return None
    return None


def _last_price(ticker):
    live = _live_price_lookup(ticker)
    if live:
        return live
    aggs = get_massive_aggs(ticker, days=30)
    if not aggs:
        return None
    return float(aggs[-1]["c"])


def _ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _price_lookup(ticker):
    """Used by acct.get_equity for mark-to-market sizing."""
    return _last_price(ticker)


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #
def size_position(equity, entry, stop, half=False):
    """Return integer share count per validated 1% (or 0.5%) risk rule.

    Capped so that entry*shares <= MAX_POS_PCT * equity.
    Returns 0 if the math is invalid (stop >= entry, etc.).
    """
    risk_per_share = entry - stop
    if risk_per_share <= 0 or equity <= 0 or entry <= 0:
        return 0
    risk_pct = RISK_PCT_HALF if half else RISK_PCT_FULL
    dollar_risk = equity * risk_pct
    shares = math.floor(dollar_risk / risk_per_share)

    # Cap by max position value.
    max_value = MAX_POS_PCT * equity
    if shares * entry > max_value:
        shares = math.floor(max_value / entry)
    return max(shares, 0)


# --------------------------------------------------------------------------- #
# Admission control
# --------------------------------------------------------------------------- #
def _open_positions():
    """List of open lots as dicts from the existing trades ledger."""
    return atlas_db.get_trades(status="OPEN")


def check_admission(ticker, regime=None, pending=None):
    """Return (allowed: bool, reason: str). Pure check, no side effects.

    `pending` is an optional iterable of ticker symbols already approved for a
    BUY earlier in the SAME run but not yet committed to the DB (relevant in a
    dry-run, or when batching). They are counted toward the position/sector/
    duplicate caps so a single run can never plan more than the limits allow.
    """
    ticker = ticker.upper()
    pending = {p.upper() for p in (pending or [])}

    if ticker in BLOCKED_TRADE_TICKERS:
        return False, f"Benchmark/index ETF excluded from trading ({ticker})"

    # Soft regime is informational for entries. Weak/missing SPY does not block buys;
    # consider_buy() applies cautious half-size risk when the regime detail is WEAK.
    if regime is None:
        regime = check_regime()

    open_pos = _open_positions()

    # Held = already in DB + already approved this run.
    held = {p["ticker"].upper() for p in open_pos} | pending
    if ticker in held:
        return False, f"Already holding {ticker}"

    # Distinct tickers open (lots can split, so count unique names).
    if len(held) >= MAX_POSITIONS:
        return False, f"Max positions reached ({MAX_POSITIONS})"

    # Per-sector cap (DB positions + pending approvals).
    sec = sector_of(ticker)
    sec_count = sum(1 for p in open_pos if sector_of(p["ticker"]) == sec)
    sec_count += sum(1 for p in pending if sector_of(p) == sec)
    if sec_count >= MAX_PER_SECTOR:
        return False, f"Max {MAX_PER_SECTOR} positions in sector {sec}"

    return True, "OK"


# --------------------------------------------------------------------------- #
# Entry trigger: buy in-band now; arm first pullback for extended signals
# --------------------------------------------------------------------------- #
def _add_trading_days(start_day, days):
    return add_trading_days(start_day, days)


def _parse_day(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _clean_daily_aggs(aggs):
    """Return daily bars with valid positive closes only."""
    clean = []
    for d in aggs or []:
        try:
            close = float(d.get("c"))
        except Exception:
            continue
        if close <= 0:
            continue
        item = dict(d)
        item["c"] = close
        try:
            low = float(item.get("l", close))
            item["l"] = low if low > 0 else close
        except Exception:
            item["l"] = close
        clean.append(item)
    return clean


def _get_eodhd_pullback_aggs(ticker, days=90):
    """Fallback daily EOD bars for new/short-history tickers; preserves EMA math."""
    if not EODHD_API_KEY:
        return []
    end_day = current_et_market_date()
    start_day = end_day - timedelta(days=days)
    try:
        r = _audit_get(
            f"https://eodhd.com/api/eod/{ticker}.US",
            params={
                "api_token": EODHD_API_KEY,
                "fmt": "json",
                "from": start_day.isoformat(),
                "to": end_day.isoformat(),
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        rows = r.json()
        if not isinstance(rows, list):
            return []
        out = []
        for row in rows:
            close = row.get("adjusted_close", row.get("close"))
            out.append({"c": close, "l": row.get("low", close), "date": row.get("date")})
        return out
    except Exception:
        return []


def _pullback_state(ticker):
    aggs = _clean_daily_aggs(get_massive_aggs(ticker, days=60))
    if len(aggs) < EMA_PERIOD:
        fallback = _clean_daily_aggs(_get_eodhd_pullback_aggs(ticker, days=120))
        if len(fallback) > len(aggs):
            aggs = fallback
    if len(aggs) < EMA_PERIOD:
        return None, f"Insufficient data for EMA10 ({len(aggs)}/{EMA_PERIOD})"
    closes = [float(d["c"]) for d in aggs]
    ema10 = _ema(closes, EMA_PERIOD)
    if ema10 is None:
        return None, "EMA10 unavailable"
    daily_close = float(closes[-1])
    live_price = _live_price_lookup(ticker)
    if live_price is None:
        return None, "Live price unavailable for pullback trigger"
    daily_low = float(aggs[-1].get("l", daily_close))
    last_price = float(live_price)
    last_low = min(daily_low, last_price)
    pct_over = ((last_price / ema10) - 1.0) * 100.0 if ema10 else 0.0
    return {
        "ema10": float(ema10),
        "last_close": last_price,
        "last_low": last_low,
        "pct_over_ema": pct_over,
        "price_source": "live_snapshot",
        "daily_close_ref": daily_close,
        "inband_trigger": float(ema10) * (1 + PULLBACK_TOL),
        "armed_trigger": float(ema10) * (1 + PULLBACK_FILL_TOL),
    }, "OK"


def _waiting_line(ticker, score, price, pct_over, trigger):
    return (f"WAITING FOR PULLBACK — {ticker} ({score}): price ${price:.2f} "
            f"= +{pct_over:.1f}% over 10-EMA. Limit armed at ${trigger:.2f} "
            f"(3-day window).")


def _too_extended_line(ticker, pct_over):
    return (f"TOO EXTENDED — {ticker} (+{pct_over:.1f}% over 10-EMA): "
            f"no trade, watching for base/consolidation.")


def check_pullback_entry(ticker):
    """Return (triggered, detail, entry_price) for fresh BUY signals.

    In-band (close <= EMA10 +2%) behaves as before: immediate buy. Extended
    signals are not bought here; consider_buy() arms the pending pullback state.
    """
    state, detail = _pullback_state(ticker)
    if not state:
        return False, detail, None
    if state["last_close"] <= state["inband_trigger"]:
        fill = max(min(state["last_close"], state["inband_trigger"]), state["last_low"])
        return True, f"Pulled back to 10-EMA {state['ema10']:.2f} (close {state['last_close']:.2f})", round(fill, 2)
    return False, (f"Extended: close {state['last_close']:.2f} > 10-EMA {state['ema10']:.2f} "
                   f"+{int(PULLBACK_TOL*100)}%"), None


def evaluate_pending_pullback(ticker, dry_run=True, regime=None, pending=None, reserved_cash=0.0):
    """Evaluate one persisted WAITING pullback. Returns None if none exists."""
    ticker = (ticker or "").upper()
    row = atlas_db.get_pending_pullback(ticker)
    if not row:
        return None

    today = current_et_market_date()
    expires = _parse_day(row.get("expires_at"))
    if expires and today > expires:
        atlas_db.expire_pending_pullback(ticker)
        return {
            "ticker": ticker, "action": "EXPIRE", "score": row.get("score"),
            "reason": f"PULLBACK EXPIRED — {ticker}, no fill in 3 days.",
            "pending_id": row.get("id"),
        }

    state, detail = _pullback_state(ticker)
    if not state:
        sig = row.get("signal_result") or {}
        fundamentals = sig.get("fundamentals")
        try:
            row_pillars = int(str(row.get("score") or "0").split("/")[0])
        except Exception:
            row_pillars = 0
        if not fundamentals and row_pillars >= 3:
            fundamentals = check_fundamentals(ticker)
        indicator_info = sig.get("indicator_info") or (check_massive_indicators(ticker) if row_pillars >= 3 else None)
        fda_calendar = sig.get("fda_calendar") or (check_fda_calendar(ticker, fundamentals=fundamentals) if row_pillars >= 3 else None)
        return {"ticker": ticker, "action": "WAIT", "score": row.get("score"), "reason": detail,
                "pending_id": row.get("id"), "wait_type": "PULLBACK_WAITING",
                "fundamentals": fundamentals, "fda_calendar": fda_calendar, "indicator_info": indicator_info, "atr_info": sig.get("atr_info"), "sentiment_info": sig.get("sentiment_info"), "macro_context": check_macro_context()}

    trigger = float(row.get("trigger_price") or state["armed_trigger"])
    if state["last_close"] <= trigger:
        sig = row.get("signal_result") or {}
        sig.setdefault("ticker", ticker)
        sig.setdefault("score", row.get("score") or "3/4 Pillars")
        decision = consider_buy(
            sig, dry_run=dry_run, regime=regime, pending=pending,
            reserved_cash=reserved_cash, pullback_override_entry=round(trigger, 2),
            pullback_override_reason=(f"Pulled back to armed 10-EMA limit {trigger:.2f} "
                                      f"(last {state['last_close']:.2f})"),
            manage_pending=False,
        )
        decision["pending_id"] = row.get("id")
        decision["from_pending_pullback"] = True
        decision.setdefault("score", sig.get("score") or row.get("score"))
        decision.setdefault("signal", sig.get("signal") or row.get("signal"))
        decision.setdefault("rvol", sig.get("rvol"))
        if decision.get("action") == "BUY" and not dry_run:
            atlas_db.mark_pending_pullback_filled(ticker)
        return decision

    sig = row.get("signal_result") or {}
    fundamentals = sig.get("fundamentals")
    try:
        row_pillars = int(str(row.get("score") or "0").split("/")[0])
    except Exception:
        row_pillars = 0
    if not fundamentals and row_pillars >= 3:
        fundamentals = check_fundamentals(ticker)
    indicator_info = sig.get("indicator_info") or (check_massive_indicators(ticker) if row_pillars >= 3 else None)
    fda_calendar = sig.get("fda_calendar") or (check_fda_calendar(ticker, fundamentals=fundamentals) if row_pillars >= 3 else None)
    return {
        "ticker": ticker,
        "action": "WAIT",
        "score": row.get("score"),
        "reason": _waiting_line(ticker, row.get("score") or "?", state["last_close"], state["pct_over_ema"], trigger),
        "pending_id": row.get("id"),
        "wait_type": "PULLBACK_WAITING",
        "entry": round(trigger, 2),
        "expires_at": row.get("expires_at"),
        "fundamentals": fundamentals,
        "fda_calendar": fda_calendar,
        "indicator_info": indicator_info,
        "atr_info": sig.get("atr_info"),
        "sentiment_info": sig.get("sentiment_info"),
        "macro_context": check_macro_context(),
    }


# --------------------------------------------------------------------------- #
# Exit engine (runs daily over open lots)
# --------------------------------------------------------------------------- #
def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _days_open(entry_at):
    dt = _parse_dt(entry_at)
    if not dt:
        return 0
    return (datetime.now(timezone.utc) - dt).days


def evaluate_exit(lot, dry_run=True, regime=None):
    """Decide whether an open lot should be closed today.

    Uses the persisted decision stop as the hard stop. Trailing/regime rules may
    raise the effective stop, but never lower the persisted decision stop.
    """
    ticker = lot["ticker"].upper()
    qty = int(lot["quantity"])
    entry = float(lot["entry_price"])
    entry_at = lot.get("entry_at")

    aggs = get_massive_aggs(ticker, days=90)
    if not aggs:
        return {"ticker": ticker, "action": "HOLD", "reason": "no price data"}

    closes = [d["c"] for d in aggs]
    highs = [d.get("h", d["c"]) for d in aggs]
    live_last = _last_price(ticker)
    last = float(live_last if live_last is not None else closes[-1])
    persisted_stop = lot.get("stop_loss")
    atr = calculate_atr(aggs) or (entry * 0.05)
    fallback_stop = entry - (ATR_STOP_MULT * atr)
    hard_stop = float(persisted_stop) if persisted_stop is not None else fallback_stop
    risk = max(entry - hard_stop, 0.01)
    target = lot.get("target_price")
    target = float(target) if target is not None else entry + (2 * risk)

    high_water = max(max(highs) if highs else last, last)
    peak_R = (high_water - entry) / risk if risk > 0 else 0.0
    gain_R = (last - entry) / risk if risk > 0 else 0.0

    stop = hard_stop
    trail_note = "persisted decision stop"
    if peak_R >= 2.0:
        stop = max(stop, entry + risk)
        trail_note = "peak +2R reached -> stop locked at +1R"
    elif peak_R >= 1.0:
        stop = max(stop, entry)
        trail_note = "peak +1R reached -> stop at breakeven"

    regime_ok, regime_detail = regime if regime is not None else check_regime()
    earnings_ctx = check_earnings_context(ticker)
    fda_calendar = check_fda_calendar(ticker, holding=True)
    risk_off_tightened = False
    if not regime_ok and stop < entry:
        stop = entry
        risk_off_tightened = True
        trail_note = f"regime risk-OFF -> stop tightened to breakeven ({regime_detail})"

    if not dry_run and lot.get("id") and stop > hard_stop:
        atlas_db.update_trade_stop(lot.get("id"), round(stop, 2))

    days = _days_open(entry_at)

    if last >= target:
        action, reason, price = "SELL", f"2R target hit; last {last:.2f} >= target {target:.2f}", round(last, 2)
    elif last <= hard_stop:
        action, reason, price = "SELL", f"Persisted stop hit; last {last:.2f} <= stop {hard_stop:.2f}", round(last, 2)
    elif last <= stop and not (risk_off_tightened and last < entry):
        action, reason, price = "SELL", f"Stop hit ({trail_note}); last {last:.2f} <= stop {stop:.2f}", round(last, 2)
    elif days > MAX_HOLD_DAYS:
        action, reason, price = "SELL", f"Time exit (> {MAX_HOLD_DAYS} days open)", round(last, 2)
    else:
        return {
            "ticker": ticker, "action": "HOLD", "qty": qty, "entry": round(entry, 2),
            "reason": f"{trail_note}; gain {gain_R:+.2f}R; {days}d open",
            "last": round(last, 2), "stop": round(stop, 2), "target": round(target, 2),
            "gain_R": round(gain_R, 2), "regime_ok": regime_ok,
            "earnings_context": earnings_ctx,
            "earnings_warning": earnings_ctx.get("holding_warning_note") if earnings_ctx.get("holding_warning") else None,
            "fda_calendar": fda_calendar,
            "fda_warning": fda_calendar.get("holding_warning_note") if isinstance(fda_calendar, dict) and fda_calendar.get("holding_warning") else None,
        }

    if not dry_run:
        try:
            atlas_db.close_trade(ticker, price, quantity=qty)
        except Exception as e:
            return {"ticker": ticker, "action": "ERROR", "reason": str(e)}

    return {"ticker": ticker, "action": action, "reason": reason, "price": price, "qty": qty,
            "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2), "regime_ok": regime_ok}


def run_exits(dry_run=True):
    """Evaluate every open lot for an exit. Returns list of decisions."""
    results = []
    regime = check_regime()
    for lot in _open_positions():
        results.append(evaluate_exit(lot, dry_run=dry_run, regime=regime))
    return results


# --------------------------------------------------------------------------- #
# Entry pipeline: turn a scored signal into a sized, admitted, triggered order
# --------------------------------------------------------------------------- #
def consider_buy(signal_result, dry_run=True, regime=None, pending=None, reserved_cash=0.0,
                 pullback_override_entry=None, pullback_override_reason=None, manage_pending=True):
    """Given a result dict from atlas_engine.analyze_ticker, decide whether to
    open a position, and how big. Returns a decision dict.

    `pending` / `reserved_cash` let a batch runner account for buys already
    approved earlier in the same pass (so caps and cash can't be exceeded even
    in a single dry-run). In live mode each buy commits immediately, so the DB
    already reflects them and these default to empty/zero.
    """
    ticker = signal_result["ticker"].upper()
    score = signal_result.get("score", "0/4 Pillars")
    pillars = int(str(score).split("/")[0])

    if pillars < 3:
        return {"ticker": ticker, "action": "SKIP", "reason": f"Score {score} (need 3/4 or 4/4)"}

    allowed, why = check_admission(ticker, regime=regime, pending=pending)
    if not allowed:
        return {"ticker": ticker, "action": "BLOCK", "reason": why}

    fundamentals = signal_result.get("fundamentals") or check_fundamentals(ticker)
    indicator_info = signal_result.get("indicator_info") or check_massive_indicators(ticker)
    confluence = evaluate_indicator_confluence(indicator_info)
    macro_ctx = check_macro_context()
    earnings_ctx = check_earnings_context(ticker)
    fda_calendar = signal_result.get("fda_calendar") or check_fda_calendar(ticker, fundamentals=fundamentals)
    if earnings_ctx.get("entry_blackout"):
        return {"ticker": ticker, "action": "BLOCK", "reason": earnings_ctx.get("blackout_reason"),
                "earnings_context": earnings_ctx, "earnings_blackout": True,
                "earnings_note": earnings_ctx.get("blackout_reason"),
                "fundamentals": fundamentals, "indicator_info": indicator_info, "atr_info": signal_result.get("atr_info"), "sentiment_info": signal_result.get("sentiment_info"), "indicator_confluence": confluence, "macro_context": macro_ctx,
                "fda_calendar": fda_calendar, "insider_activity": signal_result.get("insider_activity")}

    if isinstance(fda_calendar, dict) and fda_calendar.get("entry_blackout"):
        return {"ticker": ticker, "action": "BLOCK", "reason": fda_calendar.get("blackout_reason"),
                "fda_calendar": fda_calendar, "fda_blackout": True,
                "fda_note": fda_calendar.get("blackout_reason"),
                "earnings_context": earnings_ctx, "fundamentals": fundamentals,
                "indicator_info": indicator_info, "atr_info": signal_result.get("atr_info"),
                "sentiment_info": signal_result.get("sentiment_info"), "indicator_confluence": confluence,
                "macro_context": macro_ctx, "insider_activity": signal_result.get("insider_activity")}

    if pullback_override_entry is not None:
        fill = round(float(pullback_override_entry), 2)
        trig_detail = pullback_override_reason or f"Pulled back to armed 10-EMA limit {fill:.2f}"
    else:
        state, state_detail = _pullback_state(ticker)
        if not state:
            if manage_pending and ("EMA10" in state_detail or "EMA" in state_detail):
                atlas_db.upsert_ema_retry(ticker=ticker, score=score, signal=signal_result.get("signal", ""),
                                          signal_result=signal_result, reason=state_detail)
            return {"ticker": ticker, "action": "WAIT", "reason": state_detail, "wait_type": "EMA_RETRY",
                    "fundamentals": fundamentals, "fda_calendar": fda_calendar, "macro_context": check_macro_context()}
        if manage_pending:
            atlas_db.delete_ema_retry(ticker)
        if state["last_close"] <= state["inband_trigger"]:
            fill = round(max(min(state["last_close"], state["inband_trigger"]), state["last_low"]), 2)
            trig_detail = f"Pulled back to 10-EMA {state['ema10']:.2f} (close {state['last_close']:.2f})"
        else:
            if state["pct_over_ema"] > MAX_PULLBACK_ARM_PCT:
                if manage_pending:
                    atlas_db.delete_pending_pullback(ticker)
                return {
                    "ticker": ticker,
                    "action": "SKIP",
                    "reason": _too_extended_line(ticker, state["pct_over_ema"]),
                    "wait_type": "TOO_EXTENDED",
                    "ema10": round(state["ema10"], 2),
                    "price": round(state["last_close"], 2),
                    "pct_over_ema": round(state["pct_over_ema"], 1),
                    "fundamentals": fundamentals,
                    "fda_calendar": fda_calendar,
                    "indicator_info": indicator_info,
                    "atr_info": signal_result.get("atr_info"),
                    "sentiment_info": signal_result.get("sentiment_info"),
                    "indicator_confluence": confluence,
                    "macro_context": macro_ctx,
                    "insider_activity": signal_result.get("insider_activity"),
                }
            trigger = round(state["armed_trigger"], 2)
            expires = _add_trading_days(current_et_market_date(), PENDING_PULLBACK_DAYS).isoformat()
            if manage_pending:
                atlas_db.upsert_pending_pullback(
                    ticker=ticker, score=score, signal=signal_result.get("signal", ""),
                    signal_result=signal_result, ema10=state["ema10"], trigger_price=trigger,
                    reference_price=state["last_close"], pct_over_ema=state["pct_over_ema"],
                    expires_at=expires,
                )
            return {
                "ticker": ticker,
                "action": "WAIT",
                "reason": _waiting_line(ticker, score, state["last_close"], state["pct_over_ema"], trigger),
                "wait_type": "PULLBACK_ARMED",
                "entry": trigger,
                "ema10": round(state["ema10"], 2),
                "price": round(state["last_close"], 2),
                "pct_over_ema": round(state["pct_over_ema"], 1),
                "expires_at": expires,
                "earnings_context": earnings_ctx,
                "fundamentals": fundamentals,
                "fda_calendar": fda_calendar,
                "indicator_info": indicator_info,
                "atr_info": signal_result.get("atr_info"),
                "sentiment_info": signal_result.get("sentiment_info"),
                "indicator_confluence": confluence,
                "macro_context": macro_ctx,
                "insider_activity": signal_result.get("insider_activity"),
                "earnings_note": (earnings_ctx.get("earnings_momentum") or {}).get("earnings_momentum_note")
                                 or (earnings_ctx.get("earnings_miss") or {}).get("earnings_miss_note")
                                 or (earnings_ctx.get("note") if earnings_ctx.get("unknown") else None),
            }

    # Stop from the engine's risk card if present, else recompute.
    stop = None
    rc = signal_result.get("risk_card") or {}
    if rc.get("stop_loss"):
        # rescale the stop relative to the actual fill (engine stop was vs its close)
        entry_ref = signal_result.get("entry_price", fill)
        risk_ref = entry_ref - rc["stop_loss"]
        stop = round(fill - risk_ref, 2) if risk_ref > 0 else None
    if stop is None:
        aggs = get_massive_aggs(ticker, days=60)
        atr = calculate_atr(aggs) if aggs else None
        stop = round(fill - ATR_STOP_MULT * atr, 2) if atr else round(fill * 0.95, 2)

    equity = acct.get_equity(price_lookup=_price_lookup)
    regime_detail = str((regime or (True, ""))[1])
    cautious = ("WEAK" in regime_detail.upper() or "UNKNOWN" in regime_detail.upper()
                or "UNAVAILABLE" in regime_detail.upper() or bool((macro_ctx or {}).get("cautious")))
    half = (pillars == 3) or cautious
    shares = size_position(equity, fill, stop, half=half)
    if shares <= 0:
        return {"ticker": ticker, "action": "SKIP", "reason": "Sized to 0 shares (risk/cap/cash)"}

    cost = round(shares * fill, 2)
    cash = acct.get_cash() - float(reserved_cash or 0)  # cash not already earmarked this run
    if cost > cash:
        # scale down to available cash
        shares = math.floor(cash / fill) if fill > 0 else 0
        cost = round(shares * fill, 2)
        if shares <= 0:
            return {"ticker": ticker, "action": "SKIP", "reason": f"Insufficient cash (free ${cash:,.0f})"}

    risk_distance = fill - stop
    target = round(fill + (2 * risk_distance), 2)
    confluence_confirmed = bool(pillars == 3 and confluence.get("bullish"))
    momentum_weak = bool(pillars == 3 and confluence.get("weak"))
    confluence_note = confluence.get("note")
    if confluence_confirmed:
        trig_detail = f"{trig_detail}; RSI/MACD confluence confirmed"

    decision = {
        "ticker": ticker, "action": "BUY", "reason": trig_detail,
        "entry": fill, "stop": stop, "target": target, "shares": shares, "cost": cost,
        "risk_pct": (RISK_PCT_HALF if half else RISK_PCT_FULL) * 100,
        "cautious_mode": cautious,
        "score": score,
        "signal": signal_result.get("signal", ""),
        "rvol": signal_result.get("rvol"),
        "analyst_rating": signal_result.get("analyst_rating"),
        "analyst_insight": signal_result.get("analyst_insight"),
        "fundamentals": fundamentals,
        "fda_calendar": fda_calendar,
        "fda_note": fda_calendar.get("tag") if isinstance(fda_calendar, dict) else None,
        "indicator_info": indicator_info,
        "atr_info": signal_result.get("atr_info"),
        "sentiment_info": signal_result.get("sentiment_info"),
        "indicator_confluence": confluence,
        "confluence_confirmed": confluence_confirmed,
        "confluence_note": confluence_note,
        "momentum_weak": momentum_weak,
        "decision_quality": "CONFIRMED_ACT" if confluence_confirmed else ("MOMENTUM_WEAK_ALLOWED" if momentum_weak else "NORMAL"),
        "insider_activity": signal_result.get("insider_activity"),
        "macro_context": macro_ctx,
        "earnings_context": earnings_ctx,
        "earnings_note": (earnings_ctx.get("earnings_momentum") or {}).get("earnings_momentum_note")
                         or (earnings_ctx.get("earnings_miss") or {}).get("earnings_miss_note")
                         or (earnings_ctx.get("note") if earnings_ctx.get("unknown") else None),
        "equity": equity,
    }

    if not dry_run:
        try:
            atlas_db.open_trade(
                ticker, fill, shares,
                stop_loss=stop, risk_pct=decision["risk_pct"], target_price=target,
                status="PENDING_FILL",
                notes=f"Atlas v2 entry: {trig_detail}; score {score}; signal {signal_result.get('signal', '')}; stop {stop}; target {target}; "
                      f"{'0.5%' if half else '1%'} risk on equity ${equity:,.0f}"
                      f"{' (cautious weak-market/macro mode)' if cautious else ''}",
            )
        except Exception as e:
            decision["action"] = "ERROR"
            decision["reason"] = str(e)

    return decision


if __name__ == "__main__":
    acct.init_account()
    print(json.dumps({
        "account": acct.get_account_summary(price_lookup=_price_lookup),
        "open_positions": _open_positions(),
        "exits_dry_run": run_exits(dry_run=True),
    }, indent=2, default=str))
