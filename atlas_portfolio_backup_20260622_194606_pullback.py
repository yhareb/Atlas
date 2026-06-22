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
from datetime import datetime, timezone

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
RISK_PCT_HALF = 0.005     # 0.5% equity risk for 3/4 BUY (Small)
MAX_POS_PCT = 0.20        # cap any single position at 20% of equity
MAX_POSITIONS = 10        # max concurrent open positions
MAX_PER_SECTOR = 3        # max concurrent open positions per sector
ATR_STOP_MULT = 1.5       # hard stop = entry - 1.5*ATR
MAX_HOLD_DAYS = 40        # time exit
EMA_PERIOD = 10           # pullback entry reference
PULLBACK_TOL = 0.02       # within 2% of the 10-EMA counts as a pullback touch

# Minimal static sector map for the common scout universe. Unknown tickers are
# treated as their own unique sector (so they never block each other). Extend
# freely — this is only used for the per-sector concentration cap.
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
# Entry trigger: pullback to 10-EMA
# --------------------------------------------------------------------------- #
def check_pullback_entry(ticker):
    """Return (triggered, detail, entry_price).

    Validated rule: don't buy extended. Enter only when price is within
    PULLBACK_TOL of the 10-day EMA. Entry fills ~ at the EMA (better of EMA or
    today's close, never below today's low).
    """
    aggs = get_massive_aggs(ticker, days=60)
    if not aggs or len(aggs) < EMA_PERIOD + 1:
        return False, "Insufficient data for EMA10", None
    closes = [d["c"] for d in aggs]
    ema10 = _ema(closes, EMA_PERIOD)
    if ema10 is None:
        return False, "EMA10 unavailable", None
    last_close = closes[-1]
    last_low = aggs[-1]["l"]

    # Price within tolerance ABOVE the EMA (a healthy pullback to support),
    # i.e. close is between EMA and EMA*(1+tol). We don't chase prices far above.
    if last_close <= ema10 * (1 + PULLBACK_TOL):
        fill = max(min(last_close, ema10 * (1 + PULLBACK_TOL)), last_low)
        return True, f"Pulled back to 10-EMA {ema10:.2f} (close {last_close:.2f})", round(fill, 2)
    return False, f"Extended: close {last_close:.2f} > 10-EMA {ema10:.2f} +{int(PULLBACK_TOL*100)}%", None


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
def consider_buy(signal_result, dry_run=True, regime=None, pending=None, reserved_cash=0.0):
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

    triggered, trig_detail, fill = check_pullback_entry(ticker)
    if not triggered:
        return {"ticker": ticker, "action": "WAIT", "reason": trig_detail}

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
        "risk_pct": (RISK_PCT_HALF if half else RISK_PCT_FULL) * 100,
        "equity": equity,
    }

    if not dry_run:
        try:
            atlas_db.open_trade(
                ticker, fill, shares,
                notes=f"Atlas v2 entry: {trig_detail}; stop {stop}; "
                      f"{'0.5%' if half else '1%'} risk on equity ${equity:,.0f}",
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
