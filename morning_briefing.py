"""
morning_briefing.py
Runs at 9:00am ET every trading day.
Reads Atlas state from atlas.db and sends a concise morning
operator briefing to Telegram.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Load staging dispatch before production dependencies can alter sys.path/module cache.
from atlas_holding_state_consumer_projection import select_leaf as _atlas_select_leaf
from atlas_notify import send_telegram
from atlas_time import current_et_market_date, previous_et_trading_date_str

_atlas_staging_package_dir = os.path.dirname(os.path.abspath(__file__))
if _atlas_staging_package_dir not in sys.path:
    sys.path.insert(0, _atlas_staging_package_dir)
if "/Users/yasser/scripts" not in sys.path:
    sys.path.append("/Users/yasser/scripts")
import atlas_db
import atlas_portfolio as port
from atlas_symbol_meta import ticker_label
from atlas_report_blocks import holding_block, pullback_block, watch_list_block
from atlas_report_authority import render_portfolio_visibility_block, normalize_open_position_rows, pending_exposure_compact_lines

TELEGRAM_BOT_TOKEN = "STAGING_DISABLED"
TELEGRAM_CHAT_ID = "STAGING_DISABLED"
ET = ZoneInfo("America/New_York")


def send_telegram_message(message):
    return send_telegram(message, label="morning_briefing", route="professor_dm", report_type="morning_briefing")


def _num(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _money(value):
    value = _num(value)
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _money0(value):
    value = _num(value)
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def _signed_money(value):
    value = _num(value, 0.0)
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.0f}"


def _signed_pct(value):
    value = _num(value, 0.0)
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _shares(value):
    value = _num(value, 0.0)
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _latest_price(ticker, fallback=None):
    try:
        price = port._last_price(ticker)
        if price is not None:
            return float(price)
    except Exception:
        pass
    return fallback


def _latest_handoff(market_day):
    today = market_day.strftime("%Y-%m-%d")
    previous = previous_et_trading_date_str(market_day)
    return atlas_db.get_handoff(today) or atlas_db.get_handoff(previous) or {}


def _legacy_holding_lines():
    rows = atlas_db.get_open_positions()
    pending = atlas_db.get_pending_broker_confirmation_trades()
    positions = normalize_open_position_rows(rows, price_lookup=lambda ticker: _latest_price(ticker, fallback=None))
    return render_portfolio_visibility_block(positions, pending)

def _holding_lines():
    return _atlas_select_leaf("PRE_MARKET_HOLDINGS", _legacy_holding_lines,
                              reference="morning_briefing._holding_lines")

def _pending_stop_target(row):
    trigger = _num(row.get("trigger_price"))
    if trigger is None:
        return None, None
    sig = row.get("signal_result") or {}
    rc = sig.get("risk_card") or {}
    entry_ref = _num(sig.get("entry_price"), _num(row.get("reference_price"), trigger))
    stop_ref = _num(rc.get("stop_loss"))
    stop = None
    if entry_ref is not None and stop_ref is not None:
        risk_ref = entry_ref - stop_ref
        if risk_ref > 0:
            stop = round(trigger - risk_ref, 2)
    if stop is None:
        return None, None
    target = round(trigger + (2 * (trigger - stop)), 2)
    return stop, target


def _armed_lines(market_day):
    all_rows = atlas_db.get_pending_pullbacks(status="WAITING")
    today = market_day.strftime("%Y-%m-%d")
    rows = [r for r in all_rows if str((r or {}).get("expires_at") or "9999-12-31") >= today]
    stale = len(all_rows) - len(rows)
    rows = sorted(rows, key=lambda r: (str(r.get("expires_at") or ""), str(r.get("ticker") or "")))
    data = []
    for row in rows:
        item = dict(row)
        item.setdefault("action", "WAIT")
        item.setdefault("reason", "PULLBACK — armed for morning plan")
        item.setdefault("entry", item.get("trigger_price"))
        item.setdefault("entry_price", item.get("trigger_price"))
        item.setdefault("current_price", item.get("reference_price"))
        item.setdefault("current_price_source", "[CACHE]")
        item.setdefault("price", item.get("reference_price"))
        data.append(item)
    lines = pullback_block(data)
    if stale:
        lines.append(f"⚠️ {stale} stale expired row(s) hidden; engine will expire them on evaluation.")
    return lines

def _watch_lines(data):
    raw = data.get("WATCH", []) if isinstance(data, dict) else []
    watch_rows = [{"ticker": str(t or "").upper(), "action": "WATCH"} for t in (raw or [])]
    open_tickers = {str(r.get("ticker") or "").upper() for r in atlas_db.get_open_positions()}
    return watch_list_block(watch_rows, open_tickers=open_tickers)

def render_morning_briefing():
    market_day = current_et_market_date()
    today = market_day.strftime("%Y-%m-%d")
    data = _latest_handoff(market_day)
    handoff_date = data.get("date", "none") if isinstance(data, dict) else "none"
    now_et = datetime.now(ET).strftime("%-I:%M %p")

    lines = [
        f"🦅 ATLAS MORNING — {now_et} ET",
        f"📅 Trading day {today} · handoff {handoff_date}",
        "📡 Open plan: exits first, then armed pullbacks, then fresh scan",
    ]
    lines += _holding_lines()
    lines += _armed_lines(market_day)
    lines += _watch_lines(data)
    lines += ["", "━━━ ✅ OPEN PLAN ━━━", "Pending pullbacks are included in the scan queue and evaluated before fresh candidates."]
    return "\n".join(lines)


def generate_morning_briefing(send=True):
    message = render_morning_briefing()
    if send:
        send_telegram_message(message)
    return message




if __name__ == "__main__":
    if "--print" in sys.argv or "--dry-run" in sys.argv:
        print(generate_morning_briefing(send=False))
    else:
        generate_morning_briefing(send=True)
