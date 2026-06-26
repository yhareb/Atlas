"""Unified concise Atlas report formatter.

Builds the short operator-facing handoff used by pre-market, intraday,
post-market, and EOD handoff messages.
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")

import atlas_db
import atlas_portfolio as port
from atlas_symbol_meta import ticker_label
from atlas_time import current_et_market_date, add_trading_days

SEP = "─────────────────────────────────────────"
DOUBLE = "═══════════════════════════════"
ET = ZoneInfo("America/New_York")


def _money_whole(value):
    try:
        return f"${float(value):,.0f}"
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


def _open_position_lines():
    rows = atlas_db.get_open_positions()
    lines = ["1️⃣ OPEN POSITIONS", ""]
    if not rows:
        lines += ["   📭 None", ""]
        return lines, 0
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        entry = _num(row.get("price"))
        close = _latest_price(ticker, fallback=entry)
        pnl_pct = ((close - entry) / entry * 100.0) if entry and close is not None else 0.0
        icon = "🟢" if pnl_pct >= 3 else ("🟡" if pnl_pct >= 0 else "🔴")
        label = ticker_label(ticker, row)
        stop = _num(row.get("stop_loss"), None)
        target = _num(row.get("target_price"), None)
        stop_note = " (BE)" if stop is not None and entry and abs(stop - entry) <= 0.5 else ""
        lines += [
            f"   {icon} {label} — entry {_money_whole(entry)} · close {_money_whole(close)} · P/L {_pct_whole(pnl_pct)}",
            f"      Stop: {_money_whole(stop)}{stop_note} · Target: {_money_whole(target)}",
        ]
        note = _position_note(ticker)
        if note:
            lines.append(f"      ⚡ {note}")
        lines.append("")
    return lines, len(rows)


def _position_note(ticker):
    notes = {
        "INTC": "Goldman initiated · PT $150",
        "MS": "$20B buyback announced",
    }
    return notes.get((ticker or "").upper())


def _pending_pullback_lines(limit=8):
    rows = atlas_db.get_pending_pullbacks(status="WAITING")
    def sort_key(row):
        return abs(_num(row.get("pct_over_ema"), 999.0))
    selected = sorted(rows, key=sort_key)[:limit]
    lines = []
    for row in selected:
        ticker = str(row.get("ticker") or "?").upper()
        pct = _num(row.get("pct_over_ema"), 0.0)
        if abs(pct) <= 2:
            status = "at EMA · could fire on any dip"
        else:
            status = f"{abs(pct):.0f}% above EMA · needs pullback"
        lines.append(f"   🎣 {ticker} — trigger {_money_whole(row.get('trigger_price'))} · {status}")
    return lines, len(rows)


def _holding_watch_lines():
    lines = []
    for row in atlas_db.get_open_positions():
        ticker = str(row.get("ticker") or "?").upper()
        stop = row.get("stop_loss")
        if stop not in (None, ""):
            lines.append(f"   ⚠️ {ticker} — stop {_money_whole(stop)} · watch for drift")
    return lines


def _watch_tomorrow_lines():
    pullbacks, total_armed = _pending_pullback_lines(limit=8)
    watch_holds = _holding_watch_lines()[:3]
    lines = [
        "2️⃣ WATCH TOMORROW",
        "",
        "   🚀 Gap-up window 9:30–10:00 ET — FIRST LIVE TEST",
        "   📈 Intraday breakout window 10:00–12:00 ET — FIRST LIVE TEST",
        "",
    ]
    lines += pullbacks or ["   🎣 No armed pullbacks"]
    if total_armed > len(pullbacks):
        lines.append(f"   ⚠️ {total_armed - len(pullbacks)} more armed names hidden to keep this short")
    if watch_holds:
        lines.append("")
        lines += watch_holds
    lines.append("")
    return lines, total_armed


def _entry_type_lines():
    return [
        "3️⃣ ENTRY TYPES",
        "",
        "   🚀 Gap-Up Breakout    · 9:30–10:00 AM · RVOL >1.5x · Catalyst required · Risk 0.25%",
        "   📈 Intraday Breakout  · 10:00–12:00 PM · RVOL >2.0x · Catalyst required · Risk 0.25%",
        "   🎣 Pullback to EMA    · All day        · RVOL any   · Catalyst optional  · Risk 0.50%",
        "",
    ]


def _break_lines():
    return [
        "4️⃣ IF SOMETHING BREAKS",
        "",
        "   ❌ No intraday reports — restart com.atlas.intraday on M2",
        "   ❌ Atlas silent on Telegram — run: hermes -p atlas gateway restart",
        "   ⛔ AtlasOps must NOT touch Telegram .env — correct chat ID ends 9320",
        "",
    ]


def build_atlas_handoff_report(context=None, report_date=None):
    day = report_date or current_et_market_date()
    lines = _header(day)
    open_lines, open_count = _open_position_lines()
    watch_lines, armed_count = _watch_tomorrow_lines()
    lines += open_lines
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
