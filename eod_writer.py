"""
eod_writer.py
Runs at 4:05pm ET every trading day.
Reads today's signals from atlas.db, classifies BUY/WATCH tickers, writes the
handoff snapshot to the handoff table, and sends a clean Atlas-style handoff.
"""

import sys
from datetime import datetime

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
import atlas_portfolio as port
from atlas_time import current_et_market_date_str
from atlas_notify import send_telegram
from atlas_symbol_meta import ticker_label

INDEX_ETF_BLOCKLIST = {"SPY", "QQQ", "DIA"}


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


def _classify_signal(ticker, signal, score, rvol, entry, stop_loss, atr):
    if "BUY" not in str(signal):
        return "WATCH" if "WATCH" in str(signal) else "SKIP", str(signal)
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
    lines = ["", f"━━━ 💼 HOLDING INTO TOMORROW ({len(rows)}) ━━━"]
    if not rows:
        lines.append("📭 none")
        return lines, rows
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        qty = int(_num(row.get("quantity")))
        entry = _num(row.get("price"))
        close = _latest_price(ticker, fallback=entry)
        pnl = ((close or 0) - entry) * qty if entry and close is not None else 0
        roi = (((close or 0) / entry - 1.0) * 100) if entry and close is not None else 0
        icon = "🟢" if pnl >= 0 else "🔴"
        lines.append(
            f"{icon} {_label(ticker, row)} · {qty} sh · entry {_money(entry)} · close {_money(close)} · "
            f"P/L {_signed_money(pnl)} ({_pct(roi)}) · stop {_money(row.get('stop_loss'))} · target {_money(row.get('target_price'))}"
        )
    return lines, rows


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
    labels = [_label(ticker) for ticker in watch_tickers]
    return ["", f"━━━ 👀 WATCHING ({len(labels)}) ━━━", ", ".join(labels) if labels else "none"]


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
    buy_tickers = handoff_data.get("BUY") or []
    watch_tickers = handoff_data.get("WATCH") or []
    holding_lines, holdings = _holding_lines()
    armed_lines, armed = _armed_lines()
    lines = [
        f"🦅 ATLAS EOD WRITER HANDOFF — {handoff_data.get('date')}",
        "📬 Tomorrow handoff ready",
    ]
    lines += _bought_today_lines(buy_tickers)
    lines += holding_lines
    lines += armed_lines
    lines += _watching_lines(watch_tickers)
    lines += _day_summary_lines(handoff_data, len(holdings), len(armed), saved=saved)
    return "\n".join(lines)


def generate_eod_handoff(send=True, write_db=True):
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
        bucket, reason = _classify_signal(ticker, signal, score, rvol, entry, stop_loss, atr)
        handoff_data["DECISIONS"].append({"ticker": ticker, "decision": bucket, "reason": reason})
        if bucket == "BUY":
            handoff_data["BUY"].append(ticker)
        elif bucket in ("WATCH", "WAITING", "TOO_EXTENDED"):
            handoff_data["WATCH"].append(ticker)

    handoff_data["BUY"] = sorted(set(handoff_data["BUY"]))
    handoff_data["WATCH"] = sorted(set(handoff_data["WATCH"]))
    if write_db:
        atlas_db.update_handoff(today, handoff_data)

    msg = _build_handoff_message(handoff_data, saved=write_db)
    print(msg)
    if send:
        send_telegram(msg, label="eod_writer")
    return msg


if __name__ == "__main__":
    generate_eod_handoff()
