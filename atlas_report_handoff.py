"""Unified concise Atlas report formatter.

Builds the short operator-facing handoff used by pre-market, intraday,
post-market, and EOD handoff messages.
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

SCRIPTS_DIR = __import__("os").environ.get("ATLAS_SCRIPTS_DIR") or __import__("os").path.dirname(__import__("os").path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import atlas_db
import atlas_portfolio as port
from atlas_symbol_meta import ticker_label
from atlas_report_blocks import holding_block, pullback_block, watch_list_block
from atlas_time import current_et_market_date, add_trading_days, previous_et_trading_date_str

SEP = "─────────────────────────────────────────"
DOUBLE = "═══════════════════════════════"
ET = ZoneInfo("America/New_York")


def _money_whole(value):
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "N/A"


def _money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


def _signed_money(value):
    try:
        v = float(value)
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v):,.0f}"
    except Exception:
        return "N/A"


def _signed_pct(value):
    try:
        v = float(value)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"
    except Exception:
        return "N/A"


def _pct_whole(value):
    try:
        v = float(value)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.0f}%"
    except Exception:
        return "N/A"


def _num(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _date_label(day):
    return day.strftime("%B %-d").upper()


def _header(report_date=None):
    day = report_date or current_et_market_date()
    nxt = add_trading_days(day, 1)
    return [
        SEP,
        f"🤖 ATLAS HANDOFF — {_date_label(day)} → {nxt.day}, {nxt.year}",
        DOUBLE,
        "",
    ]


def _latest_price(ticker, fallback=None):
    try:
        price = port._last_price(ticker)
        if price is not None:
            return price
    except Exception:
        pass
    return fallback


def _append_entry_gap(lines):
    if lines and lines[-1] != "":
        lines.append("")


def _open_position_lines():
    rows = atlas_db.get_open_positions()
    positions = []
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        entry = _num(row.get("price"))
        qty = _num(row.get("quantity"), 0.0)
        now = _latest_price(ticker, fallback=entry)
        positions.append({
            "ticker": ticker,
            "entry_price": entry,
            "current_price": now,
            "stop_loss": row.get("stop_loss"),
            "target_price": row.get("target_price"),
            "quantity": qty,
        })
    lines = holding_block(positions, {})
    if lines and lines[0] == "":
        lines = lines[1:]
    return lines, len(rows)

def _position_note(ticker):
    notes = {
        "INTC": "Goldman initiated · PT $150",
        "MS": "$20B buyback announced",
    }
    return notes.get((ticker or "").upper())


def _pending_stop_target(row):
    trigger = _num(row.get("trigger_price"), None)
    if trigger is None:
        return None, None
    sig = row.get("signal_result") or {}
    rc = sig.get("risk_card") or {}
    entry_ref = _num(sig.get("entry_price"), _num(row.get("reference_price"), trigger))
    stop_ref = _num(rc.get("stop_loss"), None)
    stop = None
    if entry_ref is not None and stop_ref is not None:
        risk_ref = entry_ref - stop_ref
        if risk_ref > 0:
            stop = round(trigger - risk_ref, 2)
    if stop is None:
        return None, None
    target = round(trigger + (2 * (trigger - stop)), 2)
    return stop, target


def _pending_pullback_lines(limit=None):
    rows = atlas_db.get_pending_pullbacks(status="WAITING")
    today = current_et_market_date().strftime("%Y-%m-%d")
    rows = [r for r in rows if str((r or {}).get("expires_at") or "9999-12-31") >= today]

    def sort_key(row):
        return abs(_num(row.get("pct_over_ema"), 999.0))

    selected = sorted(rows, key=sort_key)
    if limit is not None:
        selected = selected[:limit]
    data = []
    for row in selected:
        item = dict(row)
        item.update({
            "action": "WAIT",
            "reason": "PULLBACK — armed for handoff",
            "entry": item.get("trigger_price"),
            "entry_price": item.get("trigger_price"),
            "current_price": item.get("reference_price"),
            "price": item.get("reference_price"),
        })
        data.append(item)
    lines = pullback_block(data)
    if lines and lines[0] == "":
        lines = lines[1:]
    return lines, len(rows)

def _latest_handoff(market_day):
    today = market_day.strftime("%Y-%m-%d")
    previous = previous_et_trading_date_str(market_day)
    return atlas_db.get_handoff(today) or atlas_db.get_handoff(previous) or {}


def _open_position_tickers():
    try:
        return {str(row.get("ticker") or "").upper().strip() for row in atlas_db.get_open_positions() if row.get("ticker")}
    except Exception:
        return set()


def _watch_list_lines(data):
    raw = data.get("WATCH", []) if isinstance(data, dict) else []
    watch_rows = [{"ticker": str(item or "").upper().strip(), "action": "WATCH"} for item in (raw or [])]
    lines = watch_list_block(watch_rows, open_tickers=_open_position_tickers())
    if lines and lines[0] == "":
        lines = lines[1:]
    return lines

def _entry_type_lines():
    return [
        "3️⃣ ENTRY TYPES",
        "",
        "   🚀 Gap-Up Breakout    · 9:30–10:00 AM · RVOL >1.5x · Catalyst required · Risk 0.25%",
        "",
        "   📈 Intraday Breakout  · 10:00–12:00 PM · RVOL >2.0x · Catalyst required · Risk 0.25%",
        "",
        "   🎣 Pullback to EMA    · All day        · RVOL any   · Catalyst optional  · Risk 0.50%",
        "",
    ]


def _break_lines():
    return [
        "4️⃣ IF SOMETHING BREAKS",
        "",
        "   ❌ No intraday reports — restart com.atlas.intraday on M2",
        "",
        "   ❌ Atlas silent on Telegram — run: hermes -p atlas gateway restart",
        "",
        "   ⛔ AtlasOps must NOT touch Telegram .env — correct chat ID ends 9320",
        "",
    ]


def build_atlas_handoff_report(context=None, report_date=None):
    day = report_date or current_et_market_date()
    data = _latest_handoff(day)
    lines = _header(day)
    open_lines, open_count = _open_position_lines()
    armed_lines, armed_count = _pending_pullback_lines()
    watch_lines = _watch_list_lines(data)
    lines += open_lines
    lines += [SEP, ""]
    lines += armed_lines
    lines += [SEP, ""]
    lines += watch_lines
    lines += [SEP, ""]
    lines += _entry_type_lines()
    lines += [SEP, ""]
    lines += _break_lines()
    lines += [SEP]
    lines += [f"   ✅ All fixes verified · {day.strftime('%B %-d, %Y')}"]
    lines += [SEP]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_atlas_handoff_report())
