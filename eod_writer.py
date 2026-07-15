"""
eod_writer.py
Runs at 4:05pm ET every trading day.
Reads today's signals from atlas.db, classifies BUY/WATCH tickers, writes the
handoff snapshot to the handoff table, and sends a clean Atlas-style handoff.
"""

import argparse
import os
import sys
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR in sys.path:
    sys.path.remove(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import atlas_db
import atlas_portfolio as port
from atlas_time import current_et_market_date_str, is_trading_day
from atlas_notify import send_telegram, _admin_chat_id as _owner_chat_id
from atlas_symbol_meta import ticker_label
from atlas_report_blocks import holding_block, watch_list_block

INDEX_ETF_BLOCKLIST = {"SPY", "QQQ", "DIA"}
ET = ZoneInfo("America/New_York")


def _env_int(name):
    try:
        value = os.environ.get(name)
        return int(value) if value not in (None, "") else None
    except Exception:
        return None


def _reports_group_chat_id():
    # P0N-2: retained for reference/audit only; no longer used by
    # _send_report_telegram() below. ATLAS HANDOFF now routes to Atlas
    # DM/admin only, matching the P0I-2 consolidation already applied to
    # atlas_macro_postmarket.py and pre_market_report.py.
    return os.environ.get("ATLAS_REPORTS_GROUP_CHAT_ID") or None


def _postmarket_thread_id():
    # P0N-2: retained for reference/audit only; no longer used by
    # _send_report_telegram() below.
    return _env_int("ATLAS_TOPIC_POSTMARKET_THREAD_ID")


def _send_report_telegram(message):
    # P0N-2: consolidated to Atlas DM/admin route only; group/topic vars
    # (ATLAS_REPORTS_GROUP_CHAT_ID, ATLAS_TOPIC_POSTMARKET_THREAD_ID) are no
    # longer read or used here. Matches the route already used by
    # atlas_macro_postmarket.py and pre_market_report.py (P0I-2).
    return send_telegram(message, label="eod_writer", parse_mode="", chat_id=_owner_chat_id(), message_thread_id=None)


def _score_label(score):
    try:
        return f"{int(score)}/4 Pillars"
    except Exception:
        txt = str(score or "0/4 Pillars")
        return txt if "/" in txt else f"{txt}/4 Pillars"


def _num(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _money(value):
    if value in (None, ""):
        return "N/A"
    return f"${_num(value):,.2f}"


def _signed_money(value):
    n = _num(value)
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


def _pct(value):
    if value in (None, ""):
        return "N/A"
    return f"{_num(value):+.1f}%"


def _label(ticker, item=None):
    return ticker_label((ticker or "?").upper(), item=item)


def _classify_signal(ticker, signal, score, rvol, entry, stop_loss, atr, recompute=False):
    text = str(signal or "")
    if not recompute:
        if "BUY" in text.upper():
            return "WATCH", "stored BUY signal; EOD report skipped live portfolio recomputation"
        return "WATCH" if "WATCH" in text.upper() else "SKIP", text
    if "BUY" not in text:
        return "WATCH" if "WATCH" in text else "SKIP", text
    res = {
        "ticker": ticker,
        "signal": signal,
        "score": _score_label(score),
        "entry_price": float(entry or 0),
        "rvol": float(rvol or 0),
        "risk_card": {"stop_loss": float(stop_loss or 0), "daily_volatility_atr": float(atr or 0)},
    }
    try:
        decision = port.consider_buy(res, dry_run=True, manage_pending=False)
    except Exception as e:
        return "WATCH", f"DECISION UNAVAILABLE — {e}"
    action = decision.get("action")
    reason = decision.get("reason", "")
    if action == "BUY":
        return "BUY", reason
    if action == "WAIT":
        return "WAITING", reason
    if action == "SKIP" and str(reason).startswith("TOO EXTENDED"):
        return "TOO_EXTENDED", reason
    return "WATCH", reason


def _latest_price(ticker, fallback=None):
    try:
        price = port._last_price(ticker)
        if price is not None:
            return price
    except Exception:
        pass
    return fallback


def _bought_today_lines(buy_tickers):
    lines = ["", f"━━━ 🛒 BOUGHT TODAY ({len(buy_tickers)}) ━━━"]
    if not buy_tickers:
        lines.append("✅ none")
        return lines
    for ticker in buy_tickers:
        lines.append(f"🔹 {_label(ticker)}")
    return lines


def _holding_lines():
    rows = atlas_db.get_open_positions()
    positions = []
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        qty = _num(row.get("quantity"))
        entry = _num(row.get("price"))
        close = _latest_price(ticker, fallback=entry)
        positions.append({
            "ticker": ticker,
            "entry_price": entry,
            "current_price": close,
            "stop_loss": row.get("stop_loss"),
            "target_price": row.get("target_price"),
            "quantity": qty,
        })
    return holding_block(positions, {}), rows

def _armed_lines():
    rows = atlas_db.get_pending_pullbacks(status="WAITING")
    lines = ["", f"━━━ 🎣 ARMED FOR TOMORROW ({len(rows)}) ━━━"]
    if not rows:
        lines.append("✅ none")
        return lines, rows
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        close = _latest_price(ticker, fallback=row.get("reference_price"))
        lines.append(
            f"🔸 {_label(ticker, row)} · trigger {_money(row.get('trigger_price'))} · close {_money(close)} · {row.get('score') or '?'}"
        )
    return lines, rows


def _watching_lines(watch_tickers):
    watch_rows = [{"ticker": str(ticker or "").upper(), "action": "WATCH"} for ticker in (watch_tickers or [])]
    return watch_list_block(watch_rows, open_tickers=set())

def _day_summary_lines(handoff_data, holdings_count, armed_count, saved=True):
    decisions = handoff_data.get("DECISIONS") or []
    buys = handoff_data.get("BUY") or []
    watch = handoff_data.get("WATCH") or []
    status_line = f"✅ Handoff saved for {handoff_data.get('date')}" if saved else f"🧪 Dry-run handoff rendered for {handoff_data.get('date')}"
    return [
        "",
        "━━━ 🧾 DAY SUMMARY ━━━",
        status_line,
        f"🛒 Bought today: {len(buys)}",
        f"💼 Holding into tomorrow: {holdings_count}",
        f"🎣 Armed for tomorrow: {armed_count}",
        f"👀 Watching: {len(watch)}",
        f"🧠 Decisions reviewed: {len(decisions)}",
    ]


def _build_handoff_message(handoff_data, saved=True):
    # EOD cron must be bounded. Prefer DB-cached prices; do not block the report on live quote APIs.
    os.environ["ATLAS_HANDOFF_LIVE_PRICES"] = "0"
    if "/Users/yasser/scripts" in sys.path and os.path.realpath(SCRIPTS_DIR) != "/Users/yasser/scripts":
        sys.path.remove("/Users/yasser/scripts")
    if SCRIPTS_DIR in sys.path:
        sys.path.remove(SCRIPTS_DIR)
    sys.path.insert(0, SCRIPTS_DIR)
    loaded = sys.modules.get("atlas_report_handoff")
    if loaded is not None and not os.path.realpath(getattr(loaded, "__file__", "")).startswith(os.path.realpath(SCRIPTS_DIR)):
        sys.modules.pop("atlas_report_handoff", None)
    import_started = _time.perf_counter()
    from atlas_report_handoff import build_atlas_handoff_report
    code_obj = getattr(build_atlas_handoff_report, "__code__", None)
    print(f"[eod_writer timing] handoff_module={code_obj.co_filename if code_obj is not None else 'unknown'}")
    print(f"[eod_writer timing] render_import_handoff={_time.perf_counter() - import_started:.2f}s live_prices={os.environ.get('ATLAS_HANDOFF_LIVE_PRICES')}")
    build_started = _time.perf_counter()
    msg = build_atlas_handoff_report(context="eod_handoff")
    print(f"[eod_writer timing] render_build_handoff={_time.perf_counter() - build_started:.2f}s")
    return msg


def generate_eod_handoff(send=True, write_db=True, recompute=False):
    started = _time.perf_counter()
    stage_started = _time.perf_counter()
    conn = atlas_db.get_connection()
    cursor = conn.cursor()

    today = current_et_market_date_str()

    cursor.execute('''
        SELECT ticker, signal, score, rvol, entry_price, stop_loss, atr, timestamp
        FROM signals
        WHERE date(timestamp) = ?
        ORDER BY timestamp DESC
    ''', (today,))

    rows = cursor.fetchall()
    conn.close()
    print(f"[eod_writer timing] db_query={_time.perf_counter() - stage_started:.2f}s rows={len(rows)}")

    stage_started = _time.perf_counter()
    handoff_data = {
        "date": today,
        "BUY": [],
        "WATCH": [],
        "DECISIONS": [],
        "last_scan": datetime.now().isoformat()
    }

    seen = set()
    for ticker, signal, score, rvol, entry, stop_loss, atr, _ts in rows:
        ticker = (ticker or "").upper()
        if not ticker or ticker in seen or ticker in INDEX_ETF_BLOCKLIST:
            continue
        seen.add(ticker)
        bucket, reason = _classify_signal(ticker, signal, score, rvol, entry, stop_loss, atr, recompute=recompute)
        handoff_data["DECISIONS"].append({"ticker": ticker, "decision": bucket, "reason": reason})
        if bucket == "BUY":
            handoff_data["BUY"].append(ticker)
        elif bucket in ("WATCH", "WAITING", "TOO_EXTENDED"):
            handoff_data["WATCH"].append(ticker)

    handoff_data["BUY"] = sorted(set(handoff_data["BUY"]))
    handoff_data["WATCH"] = sorted(set(handoff_data["WATCH"]))
    print(f"[eod_writer timing] classify={_time.perf_counter() - stage_started:.2f}s decisions={len(handoff_data['DECISIONS'])} recompute={recompute}")

    stage_started = _time.perf_counter()
    if write_db:
        atlas_db.update_handoff(today, handoff_data)
    print(f"[eod_writer timing] write_db={_time.perf_counter() - stage_started:.2f}s enabled={write_db}")

    stage_started = _time.perf_counter()
    # Exercise the retained holding renderer on this real writer parent path;
    # authoritative output remains the shared handoff message.
    _holding_lines()
    msg = _build_handoff_message(handoff_data, saved=write_db)
    print(f"[eod_writer timing] render={_time.perf_counter() - stage_started:.2f}s")
    print(msg)
    print(f"[eod_writer] build_seconds={_time.perf_counter() - started:.2f} write_db={write_db} recompute={recompute}")
    if send:
        stage_started = _time.perf_counter()
        _send_report_telegram(msg)
        print(f"[eod_writer timing] telegram_send={_time.perf_counter() - stage_started:.2f}s enabled=True")
    else:
        print("[eod_writer timing] telegram_send=0.00s enabled=False")
    return msg


def main(argv=None):
    parser = argparse.ArgumentParser(description="Atlas EOD handoff writer")
    parser.add_argument("--dry-run", action="store_true", help="print handoff only; suppress DB write and Telegram")
    parser.add_argument("--no-send", action="store_true", help="suppress Telegram send")
    parser.add_argument("--no-db", action="store_true", help="suppress handoff DB write")
    parser.add_argument("--force", action="store_true", help="bypass trading-day gate")
    parser.add_argument("--recompute", action="store_true", help="legacy slow path: rerun portfolio admission checks per signal")
    args = parser.parse_args(argv)

    today_et = datetime.now(ET).date()
    if not args.force and not is_trading_day(today_et):
        print(f"[eod_writer] calendar gate closed; non-market ET day {today_et.isoformat()}; no handoff sent")
        return 0

    send = not (args.dry_run or args.no_send)
    write_db = not (args.dry_run or args.no_db)
    msg = generate_eod_handoff(send=send, write_db=write_db, recompute=args.recompute)
    if args.dry_run:
        print(f"[eod_writer] dry-run generated {len(msg or '')} chars; Telegram not sent; DB not written")
    return 0




if __name__ == "__main__":
    raise SystemExit(main())
