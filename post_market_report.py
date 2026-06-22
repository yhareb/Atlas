"""
post_market_report.py
Runs at 4:45pm ET (00:15 Dubai next day) every trading day.
Delivers a post-market intelligence card to Telegram covering:
- How each active BUY/WATCH ticker closed vs entry price
- Top 5 gainers and losers of the day
- Open positions P&L snapshot ($ and %)
- Top BUY signals fired by Market Scout today
"""

import os
import sys
import re
import requests
from atlas_notify import send_telegram as _send_telegram
from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
import atlas_portfolio as port
from atlas_time import current_et_market_date, previous_et_trading_date_str
from atlas_engine import _llm_judge_catalyst

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
INDEX_ETF_BLOCKLIST = {"SPY", "QQQ", "DIA"}

NYSE_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 25),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def send_telegram(message):
    return _send_telegram(message, label="post_market")

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
    market_date = market_date or current_et_market_date()
    today = market_date.strftime('%Y-%m-%d')
    yesterday = previous_et_trading_date_str(market_date)
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


def _is_tradeable_symbol(sym):
    s = (sym or "").strip().upper()
    if not s or s in INDEX_ETF_BLOCKLIST:
        return False
    if s.startswith("$") or "." in s or "-" in s:
        return False
    return s.isalpha() and len(s) <= 5


def _dedupe_tickers(items, limit=40):
    out, seen = [], set()
    for sym in items or []:
        s = (sym or "").strip().upper()
        if _is_tradeable_symbol(s) and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _todays_signal_tickers(market_date=None):
    market_date = market_date or current_et_market_date()
    today = market_date.strftime('%Y-%m-%d')
    conn = atlas_db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ticker FROM signals WHERE date(timestamp) = ? ORDER BY ticker", (today,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def get_postmarket_catalyst_universe(market_date=None, limit=40):
    names = []
    names.extend(_todays_signal_tickers(market_date))
    try:
        today = (market_date or current_et_market_date()).strftime('%Y-%m-%d')
        data = atlas_db.get_handoff(today) or {}
        names.extend(data.get("BUY", []) or [])
        names.extend(data.get("WATCH", []) or [])
    except Exception:
        pass
    try:
        from market_scout import discover_tickers
        names.extend(discover_tickers() or [])
    except Exception as e:
        print(f"[post-market] discovery skipped: {e}")
    return _dedupe_tickers(names, limit=limit)


def _clean_catalyst_reason(reason):
    txt = re.sub(r'https?://\S+', '', str(reason or '')).strip()
    txt = txt.replace('LLM:', '').strip()
    return txt or 'Strong ticker-specific catalyst detected'


def _parse_published_utc(value):
    if not value:
        return None
    txt = str(value).replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_et(dt_utc):
    return dt_utc.astimezone(ZoneInfo("America/New_York")).strftime('%m/%d %H:%M ET')


def _previous_trading_day(day):
    d = day - timedelta(days=1)
    while d.weekday() >= 5 or d in NYSE_HOLIDAYS_2026:
        d -= timedelta(days=1)
    return d


def postmarket_news_window(now_et=None):
    now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
    close_et = datetime.combine(now_et.date(), time(16, 0), ZoneInfo("America/New_York"))
    if now_et < close_et:
        close_day = _previous_trading_day(now_et.date())
        close_et = datetime.combine(close_day, time(16, 0), ZoneInfo("America/New_York"))
    return close_et, now_et


def _ticker_news_in_window(ticker, start_et, end_et, limit=10):
    params = {
        "ticker": ticker,
        "published_utc.gte": start_et.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "published_utc.lte": end_et.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "sort": "published_utc",
        "order": "desc",
        "limit": limit,
    }
    data = massive_get("/v2/reference/news", params)
    articles = []
    for item in (data or {}).get("results") or []:
        title = (item.get("title") or "").strip()
        published = _parse_published_utc(item.get("published_utc"))
        if title and published:
            articles.append({"title": title, "published_utc": published})
    return articles


def get_engine_catalyst_watchlist(market_date=None, limit=40, max_hits=12):
    tickers = get_postmarket_catalyst_universe(market_date=market_date, limit=limit)
    start_et, end_et = postmarket_news_window()
    now_utc = datetime.now(timezone.utc)
    lines, checked = [], []
    for ticker in tickers:
        checked.append(ticker)
        articles = _ticker_news_in_window(ticker, start_et, end_et)
        if not articles:
            continue
        headlines = [a["title"] for a in articles]
        try:
            verdict = _llm_judge_catalyst(ticker, headlines)
        except Exception as e:
            print(f"[post-market] LLM catalyst judge failed for {ticker}: {e}")
            verdict = None
        if verdict is not None:
            rating, reason = verdict
            if str(rating).upper() == "STRONG":
                published = articles[0]["published_utc"]
                just_in = " 🚨 JUST IN" if (now_utc - published) <= timedelta(hours=1) else ""
                lines.append(f"  {len(lines)+1}. 🔥 {ticker}{just_in} — {_fmt_et(published)} — {_clean_catalyst_reason(reason)}")
        if len(lines) >= max_hits:
            break
    return lines, checked, start_et, end_et

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
    market_date = market_date or current_et_market_date()
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
        if ticker in INDEX_ETF_BLOCKLIST:
            continue
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
    today = current_et_market_date(now_et)

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

    catalyst_lines, checked, win_start, win_end = get_engine_catalyst_watchlist(today)
    lines.append(f"*🔥 Tomorrow Catalyst Watchlist ({len(catalyst_lines)} hits / {len(checked)} checked):*")
    lines.append(f"  Window: {win_start.strftime('%m/%d %H:%M ET')} → {win_end.strftime('%m/%d %H:%M ET')}")
    lines.extend(catalyst_lines or ["  0. No strong per-ticker catalysts found."])
    lines.append("")

    lines.append("_Market closed. Handoff written. See you tomorrow, Prof._")

    message = "\n".join(lines)
    if send:
        send_telegram(message)
    return message

if __name__ == "__main__":
    generate_post_market_report()
