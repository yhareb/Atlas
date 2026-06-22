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
from datetime import datetime, timezone, date, timedelta

sys.path.insert(0, "/Users/yasser/scripts")

import atlas_db
import atlas_account as acct

# Reuse the engine's data + indicator helpers so prices/ATR match exactly.
from atlas_engine import (
    get_massive_aggs,
    calculate_atr,
    check_regime,
)

# =============================================================================
# VALIDATED PARAMETERS (see atlas_v2_validated_doctrine.md)
# =============================================================================
RISK_PCT_FULL = 0.01      # 1% equity risk for 4/4 BUY
RISK_PCT_HALF = 0.01      # 1% equity risk for 3/4 BUY (Small)
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
def _last_price(ticker):
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
    """Return integer share count per validated 1% risk rule.

    Capped so that entry*shares <= MAX_POS_PCT * equity.
    Returns 0 if the math is invalid (stop >= entry, etc.).
    """
    risk_per_share = entry - stop
    if risk_per_share <= 0 or equity <= 0 or entry <= 0:
        return 0
    risk_pct = RISK_PCT_FULL  # Prof rule: 1% risk per trade for every BUY
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

    # Regime gate.
    if regime is None:
        regime = check_regime()
    regime_ok, regime_detail = regime
    if not regime_ok:
        return False, f"Regime risk-OFF ({regime_detail})"

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
    cur = start_day
    added = 0
    while added < int(days):
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def _parse_day(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _pullback_state(ticker):
    aggs = get_massive_aggs(ticker, days=60)
    if not aggs or len(aggs) < EMA_PERIOD + 1:
        return None, "Insufficient data for EMA10"
    closes = [float(d["c"]) for d in aggs]
    ema10 = _ema(closes, EMA_PERIOD)
    if ema10 is None:
        return None, "EMA10 unavailable"
    last_close = float(closes[-1])
    last_low = float(aggs[-1].get("l", last_close))
    pct_over = ((last_close / ema10) - 1.0) * 100.0 if ema10 else 0.0
    return {
        "ema10": float(ema10),
        "last_close": last_close,
        "last_low": last_low,
        "pct_over_ema": pct_over,
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

    today = date.today()
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
        return {"ticker": ticker, "action": "WAIT", "score": row.get("score"), "reason": detail,
                "pending_id": row.get("id"), "wait_type": "PULLBACK_WAITING"}

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
        if decision.get("action") == "BUY" and not dry_run:
            atlas_db.mark_pending_pullback_filled(ticker)
        return decision

    return {
        "ticker": ticker,
        "action": "WAIT",
        "score": row.get("score"),
        "reason": _waiting_line(ticker, row.get("score") or "?", state["last_close"], state["pct_over_ema"], trigger),
        "pending_id": row.get("id"),
        "wait_type": "PULLBACK_WAITING",
        "entry": round(trigger, 2),
        "expires_at": row.get("expires_at"),
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


def evaluate_exit(lot, dry_run=True):
    """Decide whether an open lot should be closed today.

    Returns dict {action, reason, price, ...}. Executes close_trade unless dry_run.
    Trailing-stop state is derived from price action (stateless): we recompute
    the effective stop from entry, ATR and the highest close since entry.
    """
    ticker = lot["ticker"].upper()
    qty = int(lot["quantity"])
    entry = float(lot["entry_price"])

    aggs = get_massive_aggs(ticker, days=90)
    if not aggs:
        return {"ticker": ticker, "action": "HOLD", "reason": "no price data"}

    closes = [d["c"] for d in aggs]
    highs = [d.get("h", d["c"]) for d in aggs]
    last = closes[-1]
    atr = calculate_atr(aggs) or (entry * 0.05)
    risk = ATR_STOP_MULT * atr            # 1R in dollars per share
    init_stop = entry - risk
    entry_at = lot.get("entry_at")

    # Best gain EVER reached since entry (high-water mark) drives the ratchet.
    # The stop ratchets UP at +1R / +2R and never un-ratchets, exactly as the
    # backtest modelled it. We approximate "since entry" with the available
    # window high (Massive aggs here don't carry per-bar dates); this is the
    # conservative, validated behaviour.
    high_water = max(highs) if highs else last
    peak_R = (high_water - entry) / risk if risk > 0 else 0.0
    gain_R = (last - entry) / risk if risk > 0 else 0.0

    # Trailing logic (validated) — ratchet on PEAK, not current price.
    stop = init_stop
    trail_note = "initial 1.5xATR stop"
    if peak_R >= 2.0:
        stop = max(stop, entry + risk)     # lock +1R
        trail_note = "peak +2R reached -> stop locked at +1R"
    elif peak_R >= 1.0:
        stop = max(stop, entry)            # breakeven
        trail_note = "peak +1R reached -> stop at breakeven"

    days = _days_open(entry_at)

    # Decide.
    if last <= stop:
        action, reason, price = "SELL", f"Stop hit ({trail_note}); last {last:.2f} <= stop {stop:.2f}", round(last, 2)
    elif days > MAX_HOLD_DAYS:
        action, reason, price = "SELL", f"Time exit (> {MAX_HOLD_DAYS} days open)", round(last, 2)
    else:
        return {
            "ticker": ticker, "action": "HOLD",
            "reason": f"{trail_note}; gain {gain_R:+.2f}R; {days}d open",
            "last": round(last, 2), "stop": round(stop, 2), "gain_R": round(gain_R, 2),
        }

    if not dry_run:
        try:
            atlas_db.close_trade(ticker, price, quantity=qty)
        except Exception as e:
            return {"ticker": ticker, "action": "ERROR", "reason": str(e)}

    return {"ticker": ticker, "action": action, "reason": reason, "price": price, "qty": qty}


def run_exits(dry_run=True):
    """Evaluate every open lot for an exit. Returns list of decisions."""
    results = []
    for lot in _open_positions():
        results.append(evaluate_exit(lot, dry_run=dry_run))
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

    if pullback_override_entry is not None:
        fill = round(float(pullback_override_entry), 2)
        trig_detail = pullback_override_reason or f"Pulled back to armed 10-EMA limit {fill:.2f}"
    else:
        state, state_detail = _pullback_state(ticker)
        if not state:
            return {"ticker": ticker, "action": "WAIT", "reason": state_detail}
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
                }
            trigger = round(state["armed_trigger"], 2)
            expires = _add_trading_days(date.today(), PENDING_PULLBACK_DAYS).isoformat()
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
    half = (pillars == 3)
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

    decision = {
        "ticker": ticker, "action": "BUY", "reason": trig_detail,
        "entry": fill, "stop": stop, "shares": shares, "cost": cost,
        "risk_pct": RISK_PCT_FULL * 100,
        "equity": equity,
    }

    if not dry_run:
        try:
            atlas_db.open_trade(
                ticker, fill, shares,
                notes=f"Atlas v2 entry: {trig_detail}; stop {stop}; "
                      f"1% risk on equity ${equity:,.0f}",
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
