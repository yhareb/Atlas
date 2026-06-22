"""
post_market_report.py
Runs at 4:15pm ET (00:15 Dubai next day) every trading day.
Delivers a post-market intelligence card to Telegram covering:
- How each active BUY/WATCH ticker closed vs entry price
- Top 5 gainers and losers of the day
- Open positions P&L snapshot ($ and %)
- Top BUY signals fired by Market Scout today
"""

import os
import sys
import requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
import atlas_portfolio as port

# ── Load .env if keys not already in environment ──────────────────────────────
_env_path = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MASSIVE_BASE = "https://api.massive.com"

NYSE_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 25),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[Telegram error] {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Telegram failed] {e}")

def massive_get(path, params=None):
    headers = {"Authorization": f"Bearer {MASSIVE_API_KEY}"}
    p = params or {}
    p["apiKey"] = MASSIVE_API_KEY
    try:
        r = requests.get(f"{MASSIVE_BASE}{path}", headers=headers, params=p, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[Massive error] {path}: {e}")
    return None

def pnl_arrow(chg):
    if chg is None:
        return "—"
    if chg > 0:
        return f"▲ +${chg:.2f}"
    elif chg < 0:
        return f"▼ -${abs(chg):.2f}"
    return f"→ ${chg:.2f}"

def pct_arrow(pct):
    if pct is None:
        return ""
    if pct > 0:
        return f"(+{pct:.2f}%)"
    elif pct < 0:
        return f"({pct:.2f}%)"
    return f"({pct:.2f}%)"

def get_close_price(ticker):
    snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
    if snap and snap.get("ticker"):
        t = snap["ticker"]
        close = (t.get("day") or {}).get("c")
        pct = t.get("todaysChangePerc")
        return close, pct
    return None, None

# ── Data Fetchers ─────────────────────────────────────────────────────────────

def get_handoff_close_performance(market_date=None):
    """Compare BUY/WATCH handoff tickers to their close price today."""
    market_date = market_date or datetime.now(ZoneInfo("America/New_York")).date()
    today = market_date.strftime('%Y-%m-%d')
    yesterday = (market_date - timedelta(days=1)).strftime('%Y-%m-%d')
    data = atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday)
    if not data:
        return [], []

    buy_lines = []
    watch_lines = []

    for ticker in data.get("BUY", []):
        close, pct = get_close_price(ticker)
        if close:
            buy_lines.append(f"  • {ticker}  Close: ${close:.2f}  {pct_arrow(pct)}")
        else:
            buy_lines.append(f"  • {ticker}  Close: N/A")

    for ticker in data.get("WATCH", []):
        close, pct = get_close_price(ticker)
        if close:
            watch_lines.append(f"  • {ticker}  Close: ${close:.2f}  {pct_arrow(pct)}")
        else:
            watch_lines.append(f"  • {ticker}  Close: N/A")

    return buy_lines, watch_lines

def get_top_movers():
    """Get top 5 gainers and losers of the day."""
    gainers_data = massive_get("/v2/snapshot/locale/us/markets/stocks/gainers")
    losers_data = massive_get("/v2/snapshot/locale/us/markets/stocks/losers")

    gainer_lines = []
    loser_lines = []

    if gainers_data and gainers_data.get("tickers"):
        for t in gainers_data["tickers"][:5]:
            ticker = t.get("ticker", "?")
            pct = t.get("todaysChangePerc", 0)
            price = (t.get("day") or {}).get("c")
            price_str = f"${price:.2f}" if price else "N/A"
            gainer_lines.append(f"  • {ticker} {price_str}  ▲ +{pct:.2f}%")

    if losers_data and losers_data.get("tickers"):
        for t in losers_data["tickers"][:5]:
            ticker = t.get("ticker", "?")
            pct = t.get("todaysChangePerc", 0)
            price = (t.get("day") or {}).get("c")
            price_str = f"${price:.2f}" if price else "N/A"
            loser_lines.append(f"  • {ticker} {price_str}  ▼ {pct:.2f}%")

    return gainer_lines, loser_lines

def get_positions_pnl():
    """Get open positions from atlas.db and calculate P&L vs today's close."""
    positions = atlas_db.get_open_positions()
    if not positions:
        return []

    lines = []
    for pos in positions:
        ticker = pos["ticker"]
        entry = pos["price"]
        qty = pos.get("quantity", 0)
        close, pct = get_close_price(ticker)
        if close and entry:
            chg_per_share = close - entry
            total_pnl = chg_per_share * qty if qty else None
            pnl_str = f"  Total P&L: {pnl_arrow(total_pnl)}" if total_pnl is not None else ""
            lines.append(
                f"  • {ticker}  Entry: ${entry:.2f} → Close: ${close:.2f}  "
                f"{pct_arrow(pct)}{pnl_str}"
            )
        else:
            lines.append(f"  • {ticker}  Entry: ${entry:.2f}  Close: N/A")

    return lines

def _score_label(score):
    try:
        return f"{int(score)}/4 Pillars"
    except Exception:
        txt = str(score or "0/4 Pillars")
        return txt if "/" in txt else f"{txt}/4 Pillars"


def _decision_line_from_signal(ticker, signal, score, rvol, entry, stop_loss, atr):
    score_label = _score_label(score)
    res = {
        "ticker": ticker,
        "signal": signal,
        "score": score_label,
        "entry_price": float(entry or 0),
        "rvol": float(rvol or 0),
        "risk_card": {
            "stop_loss": float(stop_loss or 0),
            "daily_volatility_atr": float(atr or 0),
        },
    }
    try:
        decision = port.consider_buy(res, dry_run=True, manage_pending=False)
    except Exception as e:
        return f"  • {ticker}  DECISION UNAVAILABLE — {e}"

    action = str(decision.get("action", "")).upper()
    reason = str(decision.get("reason", ""))
    if action == "BUY":
        return (f"  • BUY — {ticker} ({score_label}): entry ${float(decision.get('entry')):.2f}, "
                f"stop ${float(decision.get('stop')):.2f}, size {decision.get('shares')} sh, "
                f"risk {float(decision.get('risk_pct')):.1f}%")
    if action == "WAIT" and "WAITING FOR PULLBACK" in reason:
        return f"  • ⏳ {reason}"
    if action == "SKIP" and reason.startswith("TOO EXTENDED"):
        return f"  • 🚀 {reason}"
    if action == "BLOCK":
        return f"  • BLOCK — {ticker} ({score_label}): {reason}"
    return f"  • {action or 'NO BUY'} — {ticker} ({score_label}): {reason}"


def get_todays_buy_signals(market_date=None):
    """Classify today's engine BUY hits through the same entry decision layer used intraday."""
    market_date = market_date or datetime.now(ZoneInfo("America/New_York")).date()
    today = market_date.strftime('%Y-%m-%d')
    conn = atlas_db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT ticker, signal, score, rvol, entry_price, stop_loss, atr, timestamp
        FROM signals
        WHERE date(timestamp) = ?
        AND (signal LIKE '%BUY%')
        ORDER BY timestamp DESC, score DESC, rvol DESC
    ''', (today,))
    rows = cursor.fetchall()
    conn.close()

    latest_by_ticker = {}
    for row in rows:
        ticker = (row[0] or "").upper()
        if ticker and ticker not in latest_by_ticker:
            latest_by_ticker[ticker] = row

    lines = []
    for ticker in sorted(latest_by_ticker):
        t, signal, score, rvol, entry, stop_loss, atr, _ts = latest_by_ticker[ticker]
        lines.append(_decision_line_from_signal(ticker, signal, score, rvol, entry, stop_loss, atr))
    return lines

# ── Main ──────────────────────────────────────────────────────────────────────

def generate_post_market_report(send=True):
    now_et = datetime.now(ZoneInfo("America/New_York"))
    today = now_et.date()

    if today in NYSE_HOLIDAYS_2026 or today.weekday() >= 5:
        return  # Silent on holidays and weekends

    today_str = today.strftime("%Y-%m-%d")
    lines = [f"📊 *Post-Market Report — {today_str}*", ""]

    # BUY/WATCH close performance
    buy_lines, watch_lines = get_handoff_close_performance(today)
    if buy_lines:
        lines.append("*BUY Signals — End of Day:*")
        lines.extend(buy_lines)
        lines.append("")
    if watch_lines:
        lines.append("*WATCH List — End of Day:*")
        lines.extend(watch_lines)
        lines.append("")

    # Top movers
    gainers, losers = get_top_movers()
    lines.append("*Top Gainers Today:*")
    lines.extend(gainers if gainers else ["  None"])
    lines.append("")
    lines.append("*Top Losers Today:*")
    lines.extend(losers if losers else ["  None"])
    lines.append("")

    # Open positions P&L
    pos_lines = get_positions_pnl()
    if pos_lines:
        lines.append("*Open Positions — P&L Snapshot:*")
        lines.extend(pos_lines)
        lines.append("")
    else:
        lines.append("*Open Positions:* None\n")

    # Today's BUY signals from engine
    buy_signals = get_todays_buy_signals(today)
    if buy_signals:
        lines.append("*Engine Entry Decisions Today:*")
        lines.extend(buy_signals)
        lines.append("")

    lines.append("_Market closed. Handoff written. See you tomorrow, Prof._")

    message = "\n".join(lines)
    if send:
        send_telegram(message)
    return message

if __name__ == "__main__":
    generate_post_market_report()
