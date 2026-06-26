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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, date, timedelta, time
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")

import atlas_db
import atlas_account as acct
from atlas_time import current_et_market_date, add_trading_days
from atlas_symbol_meta import normalize_price, normalize_snapshot_fields

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
    evaluate_gap_breakout,
    evaluate_catalyst_override,
    get_opening_range_low,
    MASSIVE_API_KEY,
    MASSIVE_BASE,
    EODHD_API_KEY,
)

# =============================================================================
# VALIDATED PARAMETERS (see atlas_v2_validated_doctrine.md)
# =============================================================================
RISK_PCT_FULL = 0.01      # 1% equity risk for 4/4 BUY
RISK_PCT_HALF = 0.005     # 0.5% equity risk for 3/4 BUY (Small)
RISK_PCT_GAP_BREAKOUT = 0.0025  # 0.25% equity risk for opening gap-up breakout
RISK_PCT_INTRADAY_BREAKOUT = 0.0025  # 0.25% equity risk for mid-morning breakout continuation
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
BREAKOUT_TOO_HOT_EMA_PCT = 20.0  # gap-up breakout must not be >20% above EMA10
BREAKOUT_STOP_BUFFER_PCT = 0.005  # opening-range stop sits just below range low
BREAKOUT_FALLBACK_STOP_PCT = 0.04  # fallback trailing stop when intraday candles unavailable
LATE_ENTRY_CUTOFF_ET = time(14, 30)  # no new entries at/after 2:30 PM ET
SPY_INTRADAY_DROP_VETO_PCT = -0.4  # block new entries if SPY drops more than 0.4% in 30 minutes
LIVE_PRICE_CACHE_TTL_SEC = 300  # pending-pullback live quote cache; 5 minutes
SECTOR_SWEEP_TRIGGER_MOVE_PCT = 5.0
SECTOR_SWEEP_TRIGGER_RVOL = 2.0
SECTOR_SWEEP_CANDIDATE_RVOL = 1.5
SECTOR_SWEEP_MAX_PEERS = 15
SECTOR_SWEEP_PEER_CACHE_PATH = "/tmp/atlas_sector_peer_cache.json"
SECTOR_SWEEP_PEER_CACHE_TTL_SEC = 86400
SECTOR_SWEEP_PEER_LOOKUP_WORKERS = 8
_LIVE_PRICE_CACHE = {}
# Massive/Polygon single-ticker snapshot can 404 for active symbols that still
# have trade/aggregate data. Bypass that endpoint for known cases to avoid noisy
# audit alerts and use last-trade/prev-agg fallback instead.
SINGLE_SNAPSHOT_BYPASS_TICKERS = {"CWAN"}
_SECTOR_SWEEP_REF_CACHE = {}
_SECTOR_SWEEP_FUND_CACHE = {}
_SECTOR_SWEEP_PEER_CACHE = {}


def _sector_sweep_load_disk_peer_cache():
    try:
        if not os.path.exists(SECTOR_SWEEP_PEER_CACHE_PATH):
            return {}
        with open(SECTOR_SWEEP_PEER_CACHE_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        now_ts = _audit_time.time()
        fresh = {}
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            ts = float(item.get("ts") or 0)
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else None
            if meta and now_ts - ts < SECTOR_SWEEP_PEER_CACHE_TTL_SEC:
                fresh[key] = {"ts": ts, "meta": meta}
        return fresh
    except Exception:
        return {}


def _sector_sweep_save_disk_peer_cache(cache):
    try:
        tmp = f"{SECTOR_SWEEP_PEER_CACHE_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, SECTOR_SWEEP_PEER_CACHE_PATH)
    except Exception:
        pass


def _sector_sweep_peer_disk_key(ticker, max_peers):
    return f"{str(ticker or '').upper()}:{int(max_peers or SECTOR_SWEEP_MAX_PEERS)}"


def _sector_sweep_get_disk_peer_meta(ticker, max_peers):
    key = _sector_sweep_peer_disk_key(ticker, max_peers)
    cache = _sector_sweep_load_disk_peer_cache()
    item = cache.get(key) or {}
    meta = item.get("meta")
    return dict(meta) if isinstance(meta, dict) else None


def _sector_sweep_put_disk_peer_meta(ticker, max_peers, meta):
    if not isinstance(meta, dict):
        return
    key = _sector_sweep_peer_disk_key(ticker, max_peers)
    cache = _sector_sweep_load_disk_peer_cache()
    cache[key] = {"ts": _audit_time.time(), "meta": meta}
    _sector_sweep_save_disk_peer_cache(cache)


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
    ticker = (ticker or "").upper()
    if not MASSIVE_API_KEY or not ticker:
        return None
    now_ts = _audit_time.time()
    cached = _LIVE_PRICE_CACHE.get(ticker)
    if cached and (now_ts - float(cached.get("ts", 0))) <= LIVE_PRICE_CACHE_TTL_SEC:
        return cached.get("price")
    try:
        if ticker not in SINGLE_SNAPSHOT_BYPASS_TICKERS:
            r = _audit_get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                params={"apiKey": MASSIVE_API_KEY}, headers={"Accept": "application/json"}, timeout=5,
            )
            if r.status_code == 200:
                t = normalize_snapshot_fields(ticker, (r.json() or {}).get("ticker") or {})
                for section, key in (("lastTrade", "p"), ("min", "c"), ("day", "c")):
                    value = (t.get(section) or {}).get(key)
                    if value:
                        price = float(value)
                        _LIVE_PRICE_CACHE[ticker] = {"ts": now_ts, "price": price}
                        return price
            elif r.status_code == 404:
                SINGLE_SNAPSHOT_BYPASS_TICKERS.add(ticker)
            else:
                return None
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/last/trade/{ticker}",
            params={"apiKey": MASSIVE_API_KEY}, headers={"Accept": "application/json"}, timeout=5,
        )
        if r.status_code == 200:
            price = ((r.json() or {}).get("results") or {}).get("p")
            if price:
                price = float(price)
                _LIVE_PRICE_CACHE[ticker] = {"ts": now_ts, "price": price}
                return price
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
    fixed_last = normalize_price(ticker, aggs[-1]["c"])
    return float(fixed_last if fixed_last is not None else aggs[-1]["c"])


def _normalize_price_bars(ticker, aggs):
    out = []
    for row in aggs or []:
        item = dict(row)
        for key in ("c", "h", "l", "o"):
            if item.get(key) not in (None, ""):
                fixed = normalize_price(ticker, item.get(key))
                if fixed is not None:
                    item[key] = fixed
        out.append(item)
    return out


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
    risk_pct = RISK_PCT_HALF if half else RISK_PCT_FULL
    return size_position_for_risk(equity, entry, stop, risk_pct)


def size_position_for_risk(equity, entry, stop, risk_pct):
    """Return integer share count for an explicit equity-risk fraction."""
    risk_per_share = entry - stop
    if risk_per_share <= 0 or equity <= 0 or entry <= 0:
        return 0
    dollar_risk = equity * float(risk_pct or 0)
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


def _late_session_entry_block(now=None):
    """Return a BLOCK decision if new entries are past the ET cutoff; exits unaffected."""
    now_et = (now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York")))
    if now_et.time() >= LATE_ENTRY_CUTOFF_ET:
        return {
            "action": "BLOCK",
            "reason": f"LATE_SESSION_CUTOFF: no new entries after 14:30 ET ({now_et:%H:%M ET})",
            "entry_guard": "LATE_SESSION_CUTOFF",
            "now_et": now_et.isoformat(),
        }
    return None


def _spy_intraday_drop_pct(minutes=30):
    """Return SPY percent change over the last N minutes from minute aggregates."""
    if not MASSIVE_API_KEY:
        return None
    try:
        today = current_et_market_date().isoformat()
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/aggs/ticker/SPY/range/1/minute/{today}/{today}",
            params={"apiKey": MASSIVE_API_KEY, "adjusted": "true", "sort": "asc", "limit": 50000},
            headers={"Accept": "application/json"},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("results") or []
        if len(rows) < 2:
            return None
        et = ZoneInfo("America/New_York")
        latest = rows[-1]
        latest_ts = latest.get("t")
        latest_px = latest.get("c")
        if latest_ts is None or latest_px is None:
            return None
        latest_dt = datetime.fromtimestamp(float(latest_ts) / 1000.0, tz=timezone.utc).astimezone(et)
        cutoff = latest_dt - timedelta(minutes=int(minutes or 30))
        base = None
        for row in rows:
            ts = row.get("t")
            close = row.get("c")
            if ts is None or close is None:
                continue
            dt = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc).astimezone(et)
            if dt >= cutoff:
                base = row
                break
        if not base:
            return None
        base_px = float(base.get("c"))
        latest_px = float(latest_px)
        if base_px <= 0:
            return None
        return ((latest_px - base_px) / base_px) * 100.0
    except Exception:
        return None


def _entry_guard_block():
    """Final guardrail before any new BUY: late cutoff + short-term SPY drop veto."""
    late = _late_session_entry_block()
    if late:
        return late
    spy_drop = _spy_intraday_drop_pct(minutes=30)
    if spy_drop is not None and spy_drop < SPY_INTRADAY_DROP_VETO_PCT:
        return {
            "action": "BLOCK",
            "reason": f"SPY_INTRADAY_DROP_VETO: SPY {spy_drop:.2f}% over last 30 min < -0.40%",
            "entry_guard": "SPY_INTRADAY_DROP_VETO",
            "spy_30m_change_pct": round(spy_drop, 3),
        }
    return None


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
    aggs = _clean_daily_aggs(_normalize_price_bars(ticker, get_massive_aggs(ticker, days=60)))
    if len(aggs) < EMA_PERIOD:
        fallback = _clean_daily_aggs(_normalize_price_bars(ticker, _get_eodhd_pullback_aggs(ticker, days=120)))
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
                "entry": row.get("trigger_price"), "price": row.get("reference_price"),
                "pct_over_ema": row.get("pct_over_ema"), "price_source": "pending_pullback_reference",
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
    sig.setdefault("ticker", ticker)
    sig.setdefault("score", row.get("score") or "3/4 Pillars")
    sig.setdefault("signal", row.get("signal") or "")
    fundamentals = sig.get("fundamentals")
    try:
        row_pillars = int(str(row.get("score") or sig.get("score") or "0").split("/")[0])
    except Exception:
        row_pillars = 0
    breakout_meta = evaluate_gap_breakout(
        ticker, pillars=row_pillars, sentiment_info=sig.get("sentiment_info"),
        current_price=state["last_close"], ema10=state["ema10"],
    )
    if (isinstance(breakout_meta, dict) and breakout_meta.get("qualifies")
            and state["pct_over_ema"] <= BREAKOUT_TOO_HOT_EMA_PCT):
        sig["gap_breakout"] = breakout_meta
        decision = consider_buy(
            sig, dry_run=dry_run, regime=regime, pending=pending,
            reserved_cash=reserved_cash, manage_pending=False,
        )
        decision["pending_id"] = row.get("id")
        decision["from_pending_pullback"] = True
        decision["breakout_from_pending_pullback"] = True
        decision.setdefault("score", sig.get("score") or row.get("score"))
        decision.setdefault("signal", sig.get("signal") or row.get("signal"))
        decision.setdefault("rvol", sig.get("rvol"))
        if decision.get("action") == "BUY" and not dry_run:
            atlas_db.mark_pending_pullback_filled(ticker)
        return decision
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
        "gap_breakout": breakout_meta,
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

    aggs = _normalize_price_bars(ticker, get_massive_aggs(ticker, days=90))
    if not aggs:
        return {"ticker": ticker, "action": "HOLD", "reason": "no price data"}

    atr = calculate_atr(aggs) or (entry * 0.05)
    exit_aggs = aggs
    try:
        entry_day = date.fromisoformat(str(entry_at)[:10]) if entry_at else None
        if entry_day:
            scoped = []
            for d in aggs:
                ts = d.get("t")
                if ts is None:
                    continue
                day = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc).date()
                if day >= entry_day:
                    scoped.append(d)
            if scoped:
                exit_aggs = scoped
    except Exception:
        exit_aggs = aggs
    closes = [d["c"] for d in exit_aggs]
    highs = [d.get("h", d["c"]) for d in exit_aggs]
    live_last = _last_price(ticker)
    last = float(live_last if live_last is not None else closes[-1])
    persisted_stop = lot.get("stop_loss")
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
# Gap-up breakout entry (opening 9:30-10:00 ET window only)
# --------------------------------------------------------------------------- #
def _gap_breakout_window_open(now=None):
    now_et = now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York"))
    start = time(9, 30)
    end = time(10, 0)
    return start <= now_et.time() < end


def _gap_breakout_snapshot(ticker):
    ticker = (ticker or "").upper()
    if not MASSIVE_API_KEY:
        return {}
    try:
        if ticker not in SINGLE_SNAPSHOT_BYPASS_TICKERS:
            r = _audit_get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                params={"apiKey": MASSIVE_API_KEY}, headers={"Accept": "application/json"}, timeout=5,
            )
            if r.status_code == 200:
                t = normalize_snapshot_fields(ticker, (r.json() or {}).get("ticker") or {})
                day = t.get("day") or {}
                prev = t.get("prevDay") or {}
                last_trade = t.get("lastTrade") or {}
                current = day.get("c") or last_trade.get("p") or prev.get("c")
                return {
                    "current": float(current) if current else None,
                    "prev_close": float(prev.get("c")) if prev.get("c") else None,
                    "day_volume": float(day.get("v") or day.get("volume") or 0),
                }
            if r.status_code == 404:
                SINGLE_SNAPSHOT_BYPASS_TICKERS.add(ticker)
            else:
                return {}
        current = _live_price_lookup(ticker)
        prev_close = None
        day_volume = 0.0
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/aggs/ticker/{ticker}/prev",
            params={"apiKey": MASSIVE_API_KEY, "adjusted": "true"}, headers={"Accept": "application/json"}, timeout=5,
        )
        if r.status_code == 200:
            rows = (r.json() or {}).get("results") or []
            if rows:
                prev_close = rows[0].get("c")
                day_volume = rows[0].get("v") or 0.0
        return {
            "current": float(current) if current else None,
            "prev_close": float(prev_close) if prev_close else None,
            "day_volume": float(day_volume or 0),
        }
    except Exception:
        return {}


def _avg_daily_volume(ticker, days=30):
    aggs = get_massive_aggs(ticker, days=max(int(days or 30) + 5, 35)) or []
    vols = []
    for row in aggs[-int(days or 30):]:
        try:
            v = float(row.get("v") or 0)
            if v > 0:
                vols.append(v)
        except Exception:
            pass
    return (sum(vols) / len(vols)) if vols else None


def _recent_gap_catalyst(ticker, now=None):
    """True if Benzinga news or earnings beat exists within the last 24 hours."""
    ticker = (ticker or "").upper()
    now_utc = (now.astimezone(timezone.utc) if now else datetime.now(timezone.utc))
    since_utc = now_utc - timedelta(hours=24)
    if MASSIVE_API_KEY:
        try:
            r = _audit_get(
                f"{MASSIVE_BASE}/v2/reference/news",
                params={
                    "apiKey": MASSIVE_API_KEY,
                    "ticker": ticker,
                    "published_utc.gte": since_utc.isoformat().replace("+00:00", "Z"),
                    "published_utc.lte": now_utc.isoformat().replace("+00:00", "Z"),
                    "limit": 5,
                    "sort": "published_utc",
                    "order": "desc",
                },
                headers={"Accept": "application/json"}, timeout=8,
            )
            rows = (r.json() or {}).get("results") if r.status_code == 200 else []
            if rows:
                title = (rows[0].get("title") or "Recent Benzinga news").strip()
                return True, title
        except Exception:
            pass
        try:
            start = since_utc.date().isoformat()
            end = now_utc.date().isoformat()
            r = _audit_get(
                f"{MASSIVE_BASE}/benzinga/v1/earnings",
                params={"apiKey": MASSIVE_API_KEY, "ticker": ticker, "date.gte": start, "date.lte": end, "limit": 10},
                headers={"Accept": "application/json"}, timeout=8,
            )
            rows = (r.json() or {}).get("results") if r.status_code == 200 else []
            for row in rows or []:
                eps = row.get("eps_surprise_percent")
                rev = row.get("revenue_surprise_percent")
                try:
                    eps_hit = eps is not None and float(eps) > 0
                    rev_hit = rev is not None and float(rev) > 0
                except Exception:
                    eps_hit = rev_hit = False
                if eps_hit or rev_hit:
                    return True, "Benzinga earnings beat"
        except Exception:
            pass
    return False, None


def consider_gap_up_breakout(signal_result, dry_run=True, regime=None, pending=None, reserved_cash=0.0, now=None):
    ticker = signal_result["ticker"].upper()
    score = signal_result.get("score", "0/4 Pillars")
    try:
        pillars = int(str(score).split("/")[0])
    except Exception:
        pillars = 0
    if not _gap_breakout_window_open(now=now):
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_WINDOW_CLOSED"}
    if pillars < 3:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_SCORE_LT_3"}
    allowed, why = check_admission(ticker, regime=regime, pending=pending)
    if not allowed:
        return {"ticker": ticker, "action": "BLOCK", "reason": why}

    snap = _gap_breakout_snapshot(ticker)
    entry = snap.get("current")
    prev_close = snap.get("prev_close")
    if not entry or not prev_close or prev_close <= 0:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_PRICE_UNAVAILABLE"}
    gap_pct = ((entry / prev_close) - 1.0) * 100.0
    if gap_pct <= 4.0:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_GAP_LE_4", "gap_pct": round(gap_pct, 2)}
    avg_vol = _avg_daily_volume(ticker, days=30)
    day_vol = snap.get("day_volume")
    if not avg_vol or not day_vol:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_RVOL_UNAVAILABLE", "gap_pct": round(gap_pct, 2)}
    rvol = day_vol / avg_vol
    if rvol <= 1.5:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_RVOL_LE_1_5", "gap_pct": round(gap_pct, 2), "gap_rvol": round(rvol, 2)}
    catalyst_ok, catalyst_note = _recent_gap_catalyst(ticker, now=now)
    if not catalyst_ok:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_NO_24H_BENZINGA_CATALYST", "gap_pct": round(gap_pct, 2), "gap_rvol": round(rvol, 2)}

    stop = round(entry * 0.95, 2)
    target = round(entry + (2 * (entry - stop)), 2)
    equity = acct.get_equity(price_lookup=_price_lookup)
    shares = size_position_for_risk(equity, entry, stop, RISK_PCT_GAP_BREAKOUT)
    if shares <= 0:
        return {"ticker": ticker, "action": "SKIP", "reason": "GAP_BREAKOUT_SIZED_TO_ZERO"}
    cost = round(shares * entry, 2)
    cash = acct.get_cash() - float(reserved_cash or 0)
    if cost > cash:
        shares = math.floor(cash / entry) if entry > 0 else 0
        cost = round(shares * entry, 2)
        if shares <= 0:
            return {"ticker": ticker, "action": "SKIP", "reason": f"Insufficient cash (free ${cash:,.0f})"}
    decision = {
        "ticker": ticker,
        "action": "BUY",
        "reason": f"GAP-UP BREAKOUT: gap +{gap_pct:.1f}%, RVOL {rvol:.1f}x, catalyst: {catalyst_note}",
        "entry": round(entry, 2), "stop": stop, "target": target,
        "shares": shares, "cost": cost,
        "risk_pct": RISK_PCT_GAP_BREAKOUT * 100,
        "score": score, "signal": signal_result.get("signal", ""),
        "entry_type": "GAP_UP_BREAKOUT",
        "gap_pct": round(gap_pct, 2), "gap_rvol": round(rvol, 2),
        "catalyst": catalyst_note,
        "equity": equity,
    }
    if not dry_run:
        try:
            atlas_db.open_trade(
                ticker, round(entry, 2), shares, stop_loss=stop, risk_pct=decision["risk_pct"], target_price=target,
                status="PENDING_FILL",
                notes=f"Atlas gap-up breakout: gap +{gap_pct:.1f}%, RVOL {rvol:.1f}x; catalyst {catalyst_note}; stop {stop}; target {target}; 0.25% risk on equity ${equity:,.0f}",
            )
        except Exception as e:
            decision["action"] = "ERROR"
            decision["reason"] = str(e)
    return decision


# --------------------------------------------------------------------------- #
# Intraday breakout continuation (10:00-12:00 ET only)
# --------------------------------------------------------------------------- #
def _intraday_breakout_window_open(now=None):
    now_et = now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York"))
    return time(10, 0) <= now_et.time() < time(12, 0)


def _prior_day_high(ticker):
    aggs = _normalize_price_bars(ticker, get_massive_aggs(ticker, days=10)) or []
    if len(aggs) < 2:
        return None
    try:
        return float(aggs[-2].get("h") or aggs[-2].get("c"))
    except Exception:
        return None


def _latest_completed_5m_close(ticker, now=None):
    if not MASSIVE_API_KEY:
        return None
    now_et = now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York"))
    market_day = now_et.date().isoformat()
    completed_before = now_et - timedelta(minutes=5)
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/v2/aggs/ticker/{ticker}/range/5/minute/{market_day}/{market_day}",
            params={"apiKey": MASSIVE_API_KEY, "adjusted": "true", "sort": "asc", "limit": 5000},
            headers={"Accept": "application/json"}, timeout=8,
        )
        if r.status_code != 200:
            return None
        rows = _normalize_price_bars(ticker, (r.json() or {}).get("results") or [])
        latest = None
        for row in rows:
            ts = row.get("t")
            close = row.get("c")
            if ts is None or close is None:
                continue
            dt = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc).astimezone(ZoneInfo("America/New_York"))
            if dt <= completed_before:
                latest = row
        return float(latest.get("c")) if latest else None
    except Exception:
        return None


def _spy_positive_on_day():
    snap = _gap_breakout_snapshot("SPY")
    current = snap.get("current")
    prev_close = snap.get("prev_close")
    return bool(current and prev_close and float(current) > float(prev_close))


def _recent_benzinga_catalyst(ticker, now=None):
    ticker = (ticker or "").upper()
    if not MASSIVE_API_KEY:
        return False, None
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=24)
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/benzinga/v2/news",
            params={
                "apiKey": MASSIVE_API_KEY,
                "tickers": ticker,
                "date.gte": since_utc.date().isoformat(),
                "limit": 10,
            },
            headers={"Accept": "application/json"}, timeout=8,
        )
        rows = (r.json() or {}).get("results") if r.status_code == 200 else []
        for row in rows or []:
            published = row.get("published_utc") or row.get("created") or row.get("updated") or row.get("date")
            if published:
                try:
                    txt = str(published).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(txt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt.astimezone(timezone.utc) < since_utc:
                        continue
                except Exception:
                    pass
            title = (row.get("title") or "Recent Benzinga catalyst").strip()
            return True, title
    except Exception:
        pass
    return False, None


def _sector_sweep_window_open(now=None):
    now_et = now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York"))
    return time(9, 30) <= now_et.time() < time(12, 0)


def _sector_sweep_snapshot_metrics(ticker):
    snap = _gap_breakout_snapshot(ticker)
    current = snap.get("current")
    prev_close = snap.get("prev_close")
    day_vol = snap.get("day_volume")
    avg_vol = _avg_daily_volume(ticker, days=30)
    out = {"current": current, "prev_close": prev_close, "day_volume": day_vol, "avg_volume": avg_vol}
    try:
        if current and prev_close and float(prev_close) > 0:
            out["move_pct"] = ((float(current) / float(prev_close)) - 1.0) * 100.0
    except Exception:
        pass
    try:
        if day_vol and avg_vol and float(avg_vol) > 0:
            out["rvol"] = float(day_vol) / float(avg_vol)
    except Exception:
        pass
    return out


def _sector_sweep_reference_details(ticker):
    ticker = (ticker or "").upper()
    if not ticker or not MASSIVE_API_KEY:
        return {}
    if ticker in _SECTOR_SWEEP_REF_CACHE:
        return _SECTOR_SWEEP_REF_CACHE[ticker] or {}
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/v3/reference/tickers/{ticker}",
            params={"apiKey": MASSIVE_API_KEY}, headers={"Accept": "application/json"}, timeout=6,
        )
        data = (r.json() or {}).get("results") if r.status_code == 200 else {}
        _SECTOR_SWEEP_REF_CACHE[ticker] = data or {}
    except Exception:
        _SECTOR_SWEEP_REF_CACHE[ticker] = {}
    return _SECTOR_SWEEP_REF_CACHE[ticker] or {}


def _sector_sweep_fundamentals_general(ticker):
    ticker = (ticker or "").upper()
    if not ticker or not EODHD_API_KEY:
        return {}
    if ticker in _SECTOR_SWEEP_FUND_CACHE:
        return _SECTOR_SWEEP_FUND_CACHE[ticker] or {}
    try:
        r = _audit_get(
            f"https://eodhd.com/api/fundamentals/{ticker}.US",
            params={"api_token": EODHD_API_KEY, "fmt": "json"},
            headers={"Accept": "application/json"}, timeout=8,
        )
        data = (r.json() or {}).get("General") if r.status_code == 200 else {}
        _SECTOR_SWEEP_FUND_CACHE[ticker] = data or {}
    except Exception:
        _SECTOR_SWEEP_FUND_CACHE[ticker] = {}
    return _SECTOR_SWEEP_FUND_CACHE[ticker] or {}


def _sector_sweep_classification(ticker):
    ref = _sector_sweep_reference_details(ticker)
    gen = _sector_sweep_fundamentals_general(ticker)
    return {
        "ticker": (ticker or "").upper(),
        "name": ref.get("name") or gen.get("Name"),
        "sic_code": ref.get("sic_code"),
        "sic_description": ref.get("sic_description"),
        "sector": gen.get("Sector"),
        "industry": gen.get("Industry"),
        "gic_sector": gen.get("GicSector"),
        "gic_group": gen.get("GicGroup"),
        "gic_industry": gen.get("GicIndustry"),
        "gic_subindustry": gen.get("GicSubIndustry"),
    }


def _sector_sweep_is_us_listed_equity(ticker):
    ref = _sector_sweep_reference_details(ticker)
    if not ref:
        return False
    typ = str(ref.get("type") or "").upper()
    market = str(ref.get("market") or "").lower()
    locale = str(ref.get("locale") or "").lower()
    exch = str(ref.get("primary_exchange") or "").upper()
    return bool(
        ref.get("active", True)
        and market == "stocks"
        and locale == "us"
        and typ not in {"ETF", "ETN", "FUND", "INDEX"}
        and exch not in {"OTC", "PINX", "OOTC"}
    )


def _sector_sweep_related_peers(ticker):
    if not MASSIVE_API_KEY:
        return []
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/v1/related-companies/{ticker}",
            params={"apiKey": MASSIVE_API_KEY}, headers={"Accept": "application/json"}, timeout=8,
        )
        if r.status_code != 200:
            return []
        return [(row.get("ticker") or "").upper() for row in ((r.json() or {}).get("results") or []) if row.get("ticker")]
    except Exception:
        return []


def _sector_sweep_eodhd_industry_peers(industry, sector=None, limit=120):
    if not EODHD_API_KEY or not industry:
        return []
    filters = [["industry", "=", industry], ["exchange", "=", "US"], ["market_capitalization", ">", 200000000], ["adjusted_close", ">", 2]]
    if sector:
        filters.insert(0, ["sector", "=", sector])
    try:
        r = _audit_get(
            "https://eodhd.com/api/screener",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": json.dumps(filters), "limit": int(limit), "sort": "market_capitalization.desc"},
            headers={"Accept": "application/json"}, timeout=10,
        )
        if r.status_code != 200:
            return []
        return [(row.get("code") or "").upper().replace(".US", "") for row in ((r.json() or {}).get("data") or []) if row.get("code")]
    except Exception:
        return []


def _sector_sweep_curated_gics_industry_peers(gic_industry):
    if str(gic_industry or "").strip().lower() != "semiconductors & semiconductor equipment":
        return []
    return [
        "NVDA", "AMD", "AVGO", "QCOM", "MU", "MRVL", "ON", "STM", "TSM", "ASML", "AMAT", "LRCX",
        "KLAC", "TER", "UCTT", "MKSI", "MXL", "ALGM", "ENTG", "ONTO", "NVMI", "AEIS", "ACLS", "COHU",
        "VECO", "ICHR", "FORM", "AMKR", "LSCC", "MPWR", "RMBS", "SMTC", "DIOD", "POWI", "CRUS", "WOLF",
    ]


def sector_catalyst_sweep_peers(ticker, max_peers=SECTOR_SWEEP_MAX_PEERS):
    ticker = (ticker or "").upper()
    cache_key = (ticker, int(max_peers or SECTOR_SWEEP_MAX_PEERS))
    if cache_key in _SECTOR_SWEEP_PEER_CACHE:
        return dict(_SECTOR_SWEEP_PEER_CACHE[cache_key])
    disk_meta = _sector_sweep_get_disk_peer_meta(ticker, max_peers)
    if disk_meta:
        _SECTOR_SWEEP_PEER_CACHE[cache_key] = dict(disk_meta)
        return dict(disk_meta)
    cls = _sector_sweep_classification(ticker)
    raw = []
    if cls.get("industry"):
        raw.extend(_sector_sweep_eodhd_industry_peers(cls.get("industry"), sector=cls.get("sector"), limit=max(30, int(max_peers or SECTOR_SWEEP_MAX_PEERS) * 3)))
    raw.extend(_sector_sweep_related_peers(ticker))
    raw.extend(_sector_sweep_curated_gics_industry_peers(cls.get("gic_industry")))
    limit = int(max_peers or SECTOR_SWEEP_MAX_PEERS)
    peers, seen, candidates = [], {ticker}, []
    for sym in raw:
        sym = (sym or "").upper().strip()
        if not sym or sym in seen or "." in sym or "-" in sym:
            continue
        seen.add(sym)
        candidates.append(sym)
        if len(candidates) >= max(limit * 3, limit):
            break
    workers = max(1, min(SECTOR_SWEEP_PEER_LOOKUP_WORKERS, len(candidates) or 1))
    if candidates:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_sym = {executor.submit(_sector_sweep_is_us_listed_equity, sym): sym for sym in candidates}
            usable = {}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    usable[sym] = bool(future.result())
                except Exception:
                    usable[sym] = False
        for sym in candidates:
            if usable.get(sym):
                peers.append(sym)
                if len(peers) >= limit:
                    break
    meta = {"trigger": ticker, "classification": cls, "peers": peers, "peer_count": len(peers)}
    _SECTOR_SWEEP_PEER_CACHE[cache_key] = dict(meta)
    _sector_sweep_put_disk_peer_meta(ticker, max_peers, meta)
    return meta


def sector_catalyst_sweep_trigger(signal_result, now=None):
    ticker = str((signal_result or {}).get("ticker") or "").upper()
    if not ticker or not _sector_sweep_window_open(now=now):
        return None
    metrics = _sector_sweep_snapshot_metrics(ticker)
    move_pct = metrics.get("move_pct")
    rvol = metrics.get("rvol")
    if move_pct is None or float(move_pct) <= SECTOR_SWEEP_TRIGGER_MOVE_PCT:
        return None
    if rvol is None or float(rvol) <= SECTOR_SWEEP_TRIGGER_RVOL:
        return None
    catalyst_ok, catalyst_note = _recent_benzinga_catalyst(ticker, now=now)
    if not catalyst_ok:
        return None
    meta = sector_catalyst_sweep_peers(ticker)
    meta.update({
        "move_pct": round(float(move_pct), 2),
        "rvol": round(float(rvol), 2),
        "catalyst": catalyst_note,
        "entry_type": "SECTOR_CATALYST_SWEEP",
    })
    return meta if meta.get("peers") else None


def consider_sector_catalyst_peer_breakout(signal_result, trigger_meta, dry_run=True, regime=None, pending=None,
                                           reserved_cash=0.0, now=None):
    ticker = str((signal_result or {}).get("ticker") or "").upper()
    if not ticker or not _sector_sweep_window_open(now=now):
        return {"ticker": ticker, "action": "SKIP", "reason": "SECTOR_SWEEP_WINDOW_CLOSED"}
    score = signal_result.get("score", "0/4 Pillars")
    try:
        pillars = int(str(score).split("/")[0])
    except Exception:
        pillars = 0
    if pillars < 3:
        return {"ticker": ticker, "action": "SKIP", "reason": "SECTOR_SWEEP_SCORE_LT_3"}
    if atlas_db.get_pending_pullback(ticker):
        return {"ticker": ticker, "action": "SKIP", "reason": "SECTOR_SWEEP_ALREADY_WAITING_FOR_DIP"}
    allowed, why = check_admission(ticker, regime=regime, pending=pending)
    if not allowed:
        return {"ticker": ticker, "action": "BLOCK", "reason": why}
    rv = None
    try:
        rv = float(signal_result.get("rvol")) if signal_result.get("rvol") is not None else None
    except Exception:
        rv = None
    metrics = None
    if rv is None:
        metrics = _sector_sweep_snapshot_metrics(ticker)
        rv = metrics.get("rvol")
    if rv is None or float(rv) <= SECTOR_SWEEP_CANDIDATE_RVOL:
        return {"ticker": ticker, "action": "SKIP", "reason": "SECTOR_SWEEP_RVOL_LE_1_5", "breakout_rvol": round(float(rv), 2) if rv is not None else None}
    if metrics is None:
        metrics = _sector_sweep_snapshot_metrics(ticker)
    entry = metrics.get("current") or signal_result.get("entry_price")
    if not entry:
        return {"ticker": ticker, "action": "SKIP", "reason": "SECTOR_SWEEP_PRICE_UNAVAILABLE", "breakout_rvol": round(float(rv), 2)}
    prior_high = _prior_day_high(ticker)
    breakout_level = float(prior_high or entry)
    entry = round(float(entry), 2)
    stop_base = breakout_level if breakout_level < entry else entry
    stop = round(float(stop_base) * 0.98, 2)
    target = round(entry + (2 * (entry - stop)), 2)
    equity = acct.get_equity(price_lookup=_price_lookup)
    shares = size_position_for_risk(equity, entry, stop, RISK_PCT_INTRADAY_BREAKOUT)
    cost = round(shares * entry, 2) if shares else 0.0
    trigger = (trigger_meta or {}).get("trigger")
    decision = {
        "ticker": ticker,
        "action": "CANDIDATE",
        "reason": f"SECTOR CATALYST SWEEP: {trigger} sympathy breakout candidate, {score}, RVOL {float(rv):.1f}x",
        "entry": entry, "stop": stop, "target": target,
        "shares": shares, "cost": cost,
        "risk_pct": RISK_PCT_INTRADAY_BREAKOUT * 100,
        "score": score, "signal": signal_result.get("signal", ""),
        "entry_type": "INTRADAY_BREAKOUT_CONTINUATION",
        "sector_sweep": True,
        "sector_sweep_trigger": trigger,
        "sector_sweep_trigger_move_pct": (trigger_meta or {}).get("move_pct"),
        "sector_sweep_trigger_rvol": (trigger_meta or {}).get("rvol"),
        "sector_sweep_catalyst": (trigger_meta or {}).get("catalyst"),
        "breakout_level": round(float(breakout_level), 2),
        "breakout_rvol": round(float(rv), 2),
        "equity": equity,
    }
    return decision


def consider_intraday_breakout_continuation(signal_result, dry_run=True, regime=None, pending=None,
                                             reserved_cash=0.0, now=None):
    """Mid-morning continuation: 5m close above prior-day high on extreme volume."""
    ticker = signal_result["ticker"].upper()
    score = signal_result.get("score", "0/4 Pillars")
    try:
        pillars = int(str(score).split("/")[0])
    except Exception:
        pillars = 0
    if not _intraday_breakout_window_open(now=now):
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_WINDOW_CLOSED"}
    if pillars < 3:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_SCORE_LT_3"}
    if atlas_db.get_pending_pullback(ticker):
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_ALREADY_WAITING_FOR_DIP"}
    allowed, why = check_admission(ticker, regime=regime, pending=pending)
    if not allowed:
        return {"ticker": ticker, "action": "BLOCK", "reason": why}
    if not _spy_positive_on_day():
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_SPY_NOT_POSITIVE"}
    catalyst_ok, catalyst_note = _recent_benzinga_catalyst(ticker, now=now)
    if not catalyst_ok:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_NO_24H_BENZINGA_CATALYST"}
    prior_high = _prior_day_high(ticker)
    if not prior_high:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_PRIOR_HIGH_UNAVAILABLE"}
    close_5m = _latest_completed_5m_close(ticker, now=now)
    if not close_5m or close_5m <= prior_high:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_NO_5M_CLOSE_ABOVE_PRIOR_HIGH", "breakout_level": round(prior_high, 2), "entry": round(close_5m, 2) if close_5m else None}
    snap = _gap_breakout_snapshot(ticker)
    avg_vol = _avg_daily_volume(ticker, days=30)
    day_vol = snap.get("day_volume")
    if not avg_vol or not day_vol:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_RVOL_UNAVAILABLE", "breakout_level": round(prior_high, 2)}
    rvol = day_vol / avg_vol
    if rvol <= 2.0:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_RVOL_LE_2", "breakout_level": round(prior_high, 2), "breakout_rvol": round(rvol, 2)}

    entry = round(float(close_5m), 2)
    breakout_level = round(float(prior_high), 2)
    stop = round(float(prior_high) * 0.98, 2)
    target = round(entry + (2 * (entry - stop)), 2)
    equity = acct.get_equity(price_lookup=_price_lookup)
    shares = size_position_for_risk(equity, entry, stop, RISK_PCT_INTRADAY_BREAKOUT)
    if shares <= 0:
        return {"ticker": ticker, "action": "SKIP", "reason": "INTRADAY_BREAKOUT_SIZED_TO_ZERO"}
    cost = round(shares * entry, 2)
    cash = acct.get_cash() - float(reserved_cash or 0)
    if cost > cash:
        shares = math.floor(cash / entry) if entry > 0 else 0
        cost = round(shares * entry, 2)
        if shares <= 0:
            return {"ticker": ticker, "action": "SKIP", "reason": f"Insufficient cash (free ${cash:,.0f})"}
    decision = {
        "ticker": ticker, "action": "BUY",
        "reason": f"INTRADAY BREAKOUT CONTINUATION: 5m close {entry:.2f} > prior high {breakout_level:.2f}, RVOL {rvol:.1f}x, catalyst: {catalyst_note}",
        "entry": entry, "stop": stop, "target": target,
        "shares": shares, "cost": cost,
        "risk_pct": RISK_PCT_INTRADAY_BREAKOUT * 100,
        "score": score, "signal": signal_result.get("signal", ""),
        "entry_type": "INTRADAY_BREAKOUT_CONTINUATION",
        "breakout_level": breakout_level,
        "breakout_rvol": round(rvol, 2),
        "catalyst": catalyst_note,
        "equity": equity,
    }
    if not dry_run:
        try:
            atlas_db.open_trade(
                ticker, entry, shares, stop_loss=stop, risk_pct=decision["risk_pct"], target_price=target,
                status="PENDING_FILL",
                notes=f"Atlas intraday breakout continuation: break {breakout_level}; entry {entry}; RVOL {rvol:.1f}x; catalyst {catalyst_note}; stop {stop}; target {target}; 0.25% risk on equity ${equity:,.0f}",
            )
        except Exception as e:
            decision["action"] = "ERROR"
            decision["reason"] = str(e)
    return decision


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
    catalyst_override_meta = signal_result.get("catalyst_override")
    catalyst_override_entry = bool(
        pillars == 2 and isinstance(catalyst_override_meta, dict) and catalyst_override_meta.get("qualifies")
    )

    if pillars < 3 and not catalyst_override_entry:
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

    breakout_stop = None
    catalyst_override_stop = None
    breakout_meta = None

    if catalyst_override_entry:
        fill = round(float(catalyst_override_meta.get("current_price") or signal_result.get("entry_price")), 2)
        catalyst_override_stop = round(fill * 0.95, 2)
        trig_detail = (
            f"CATALYST OVERRIDE Entry: score {score}, RVOL {float(catalyst_override_meta.get('rvol') or 0):.2f}, "
            f"gap +{float(catalyst_override_meta.get('gap_pct') or 0):.1f}%, "
            f"sentiment {float(catalyst_override_meta.get('sentiment_score') or 0):+.2f}; half-size, 5% stop"
        )
        if manage_pending and not dry_run:
            atlas_db.delete_pending_pullback(ticker)
    elif pullback_override_entry is not None:
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
            breakout_meta = signal_result.get("gap_breakout")
            if not isinstance(breakout_meta, dict) or not breakout_meta.get("qualifies"):
                breakout_meta = evaluate_gap_breakout(
                    ticker, pillars=pillars, sentiment_info=signal_result.get("sentiment_info"),
                    current_price=state["last_close"], ema10=state["ema10"],
                )
            if (isinstance(breakout_meta, dict) and breakout_meta.get("qualifies")
                    and state["pct_over_ema"] <= BREAKOUT_TOO_HOT_EMA_PCT):
                fill = round(float(state["last_close"]), 2)
                or_low = get_opening_range_low(ticker, minutes=30) or get_opening_range_low(ticker, minutes=15)
                if or_low and float(or_low) < fill:
                    breakout_stop = round(float(or_low) * (1.0 - BREAKOUT_STOP_BUFFER_PCT), 2)
                    stop_detail = f"opening-range stop below ${float(or_low):.2f}"
                else:
                    breakout_stop = round(fill * (1.0 - BREAKOUT_FALLBACK_STOP_PCT), 2)
                    stop_detail = "4% fallback trailing stop"
                trig_detail = (
                    f"Gap-Up Breakout Entry: gap +{float(breakout_meta.get('gap_pct') or 0):.1f}%, "
                    f"volume {float(breakout_meta.get('volume_ratio') or 0):.1f}x 30D, "
                    f"sentiment {float(breakout_meta.get('sentiment_score') or 0):+.2f}; {stop_detail}"
                )
                if manage_pending:
                    atlas_db.delete_pending_pullback(ticker)
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
                        "gap_breakout": breakout_meta,
                        "indicator_confluence": confluence,
                        "macro_context": macro_ctx,
                        "insider_activity": signal_result.get("insider_activity"),
                    }
                trigger = round(state["armed_trigger"], 2)
            if breakout_stop is None:
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

    entry_guard = _entry_guard_block()
    if entry_guard:
        return {"ticker": ticker, "score": score, "signal": signal_result.get("signal", ""), **entry_guard}

    # Stop from the engine's risk card if present, else recompute.
    stop = None
    rc = signal_result.get("risk_card") or {}
    if catalyst_override_stop is not None:
        stop = catalyst_override_stop
    elif breakout_stop is not None:
        stop = breakout_stop
    elif rc.get("stop_loss"):
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
    half = (pillars == 3) or cautious or catalyst_override_entry
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
        "gap_breakout": breakout_meta or signal_result.get("gap_breakout"),
        "catalyst_override": catalyst_override_meta if catalyst_override_entry else signal_result.get("catalyst_override"),
        "entry_type": "CATALYST_OVERRIDE" if catalyst_override_entry else ("GAP_BREAKOUT" if breakout_stop is not None else "PULLBACK"),
        "position_size_flag": "HALF_SIZE_CATALYST_OVERRIDE" if catalyst_override_entry else None,
        "indicator_confluence": confluence,
        "confluence_confirmed": confluence_confirmed,
        "confluence_note": confluence_note,
        "momentum_weak": momentum_weak,
        "decision_quality": "CATALYST_OVERRIDE" if catalyst_override_entry else ("CONFIRMED_ACT" if confluence_confirmed else ("MOMENTUM_WEAK_ALLOWED" if momentum_weak else "NORMAL")),
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
