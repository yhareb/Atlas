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


def _num(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _fmt_price(value, width=0):
    n = _num(value)
    s = "N/A" if n is None or n <= 0 else f"${n:,.2f}"
    return s.rjust(width) if width else s


def _fmt_pct(value, signed=True, width=0):
    n = _num(value)
    if n is None:
        s = "—"
    elif signed:
        s = f"{n:+.2f}%"
    else:
        s = f"{n:.2f}%"
    return s.rjust(width) if width else s


def _fmt_money(value):
    n = _num(value)
    return "N/A" if n is None else f"${n:,.2f}"


def _clean_score_num(score):
    txt = str(score or "")
    m = re.search(r"(\d+)", txt)
    return int(m.group(1)) if m else 0


def _ticker_col(ticker, width=6):
    return str(ticker or "?").upper().ljust(width)

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
        return []

    rows, seen = [], set()
    for bucket in ("BUY", "WATCH"):
        for ticker in data.get(bucket, []) or []:
            ticker = (ticker or "").upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            close, pct = get_close_price(ticker)
            rows.append({"ticker": ticker, "close": close, "pct": pct, "bucket": bucket})

    return sorted(rows, key=lambda r: (_num(r.get("pct"), -999999), r.get("ticker", "")), reverse=True)

def get_top_movers():
    """Get top 5 gainers and losers of the day."""
    gainers_data = massive_get("/v2/snapshot/locale/us/markets/stocks/gainers")
    losers_data = massive_get("/v2/snapshot/locale/us/markets/stocks/losers")

    gainers = []
    losers = []

    if gainers_data and gainers_data.get("tickers"):
        for t in gainers_data["tickers"][:5]:
            gainers.append({
                "ticker": t.get("ticker", "?"),
                "pct": t.get("todaysChangePerc"),
                "price": (t.get("day") or {}).get("c"),
            })

    if losers_data and losers_data.get("tickers"):
        for t in losers_data["tickers"][:5]:
            losers.append({
                "ticker": t.get("ticker", "?"),
                "pct": t.get("todaysChangePerc"),
                "price": (t.get("day") or {}).get("c"),
            })

    return gainers, losers

def get_positions_pnl():
    """Get open positions from atlas.db and calculate P&L vs today's close."""
    positions = atlas_db.get_open_positions()
    rows = []
    for pos in positions or []:
        ticker = pos["ticker"]
        entry = pos["price"]
        qty = pos.get("quantity", 0)
        stop = pos.get("stop_loss")
        close, pct = get_close_price(ticker)
        total_pnl = pnl_pct = None
        if close and entry:
            total_pnl = (close - entry) * qty if qty else None
            pnl_pct = ((close - entry) / entry) * 100 if entry else None
        rows.append({
            "ticker": ticker,
            "entry": entry,
            "stop": stop,
            "quantity": qty,
            "close": close,
            "day_pct": pct,
            "pnl": total_pnl,
            "pnl_pct": pnl_pct,
        })
    return rows


def get_account_snapshot(position_rows=None):
    """Return displayed cash/equity from the local account ledger and open positions."""
    conn = atlas_db.get_connection()
    cur = conn.cursor()
    cash = None
    try:
        row = cur.execute("SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            cash = row[0]
    except Exception:
        pass
    if cash is None:
        try:
            row = cur.execute("SELECT starting_cash FROM account ORDER BY id ASC LIMIT 1").fetchone()
            if row:
                cash = row[0]
        except Exception:
            pass
    conn.close()
    invested = 0.0
    for row in position_rows or []:
        close = _num(row.get("close"))
        qty = _num(row.get("quantity"), 0) or 0
        if close is not None:
            invested += close * qty
    equity = (cash + invested) if cash is not None else None
    return {"cash": cash, "equity": equity}


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


def get_engine_catalyst_watchlist(market_date=None, limit=40, max_hits=12, now_et=None):
    tickers = get_postmarket_catalyst_universe(market_date=market_date, limit=limit)
    start_et, end_et = postmarket_news_window(now_et=now_et)
    now_utc = (now_et.astimezone(timezone.utc) if now_et else datetime.now(timezone.utc))
    hits, checked = [], []
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
                hits.append({
                    "ticker": ticker,
                    "published": published,
                    "just_in": just_in,
                    "reason": _clean_catalyst_reason(reason),
                })
        if len(hits) >= max_hits:
            break
    return hits, checked, start_et, end_et

def _score_label(score):
    try:
        return f"{int(score)}/4 Pillars"
    except Exception:
        txt = str(score or "0/4 Pillars")
        return txt if "/" in txt else f"{txt}/4 Pillars"


def _decision_record_from_signal(ticker, signal, score, rvol, entry, stop_loss, atr):
    score_label = _score_label(score)
    rec = {"ticker": ticker, "score_label": score_label, "score_num": _clean_score_num(score_label)}
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
        rec.update({"category": "no_data", "reason": f"DECISION UNAVAILABLE — {e}"})
        return rec

    action = str(decision.get("action", "")).upper()
    reason = str(decision.get("reason", ""))
    rec.update({"action": action, "reason": reason, "decision": decision})

    if action == "BUY":
        rec.update({
            "category": "bought",
            "entry": decision.get("entry"),
            "stop": decision.get("stop"),
            "shares": decision.get("shares"),
            "risk_pct": decision.get("risk_pct"),
        })
        return rec

    earnings = re.search(r"EARNINGS\s+in\s+(\d+)d", reason, re.I)
    if action == "BLOCK" and earnings:
        rec.update({"category": "blocked_earnings", "days": int(earnings.group(1))})
        return rec

    wait = re.search(
        r"WAITING FOR PULLBACK\s+—\s+\S+\s+\([^)]*\):\s+price\s+\$([\d,.]+)\s+=\s+\+([\d.]+)%\s+over\s+10-EMA\.\s+Limit\s+armed\s+at\s+\$([\d,.]+)",
        reason,
    )
    if action == "WAIT" and wait:
        rec.update({
            "category": "armed",
            "price": float(wait.group(1).replace(',', '')),
            "pct_over_ema": float(wait.group(2)),
            "limit": float(wait.group(3).replace(',', '')),
        })
        return rec

    hot = re.search(r"TOO EXTENDED\s+—\s+\S+\s+\(\+([\d.]+)%\s+over\s+10-EMA\)", reason)
    if action == "SKIP" and hot:
        rec.update({"category": "too_hot", "pct_over_ema": float(hot.group(1))})
        return rec

    rec.update({"category": "no_data", "reason": reason or action or "No decision detail available"})
    return rec


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

    records = []
    for ticker in sorted(latest_by_ticker):
        t, signal, score, rvol, entry, stop_loss, atr, _ts = latest_by_ticker[ticker]
        records.append(_decision_record_from_signal(ticker, signal, score, rvol, entry, stop_loss, atr))
    return records

# ── Main ──────────────────────────────────────────────────────────────────────

def _append_decision_group(lines, title, rows, formatter):
    lines.append(f"   {title} ({len(rows)})")
    if rows:
        for row in rows:
            lines.append(formatter(row))


def _format_watchlist_row(row):
    close = _num(row.get("close"))
    pct = _num(row.get("pct")) if close is not None and close > 0 else None
    icon = "⚪" if pct is None else ("🟢" if pct >= 0 else "🔴")
    return f"   {icon} {_ticker_col(row.get('ticker'))} {_fmt_price(close, 10)}   {_fmt_pct(pct, width=8)}"


def _format_mover_row(row, up=True):
    arrow = "▲" if up else "▼"
    pct = _num(row.get("pct"))
    pct_abs = None if pct is None else abs(pct)
    sign = "+" if up else "-"
    pct_txt = "—" if pct_abs is None else f"{arrow} {sign}{pct_abs:.2f}%"
    return f"      • {_ticker_col(row.get('ticker'))} {_fmt_price(row.get('price'), 10)}   {pct_txt.rjust(10)}"


def generate_post_market_report(send=True, market_date=None, now_et=None):
    now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
    if market_date is None:
        today = current_et_market_date(now_et)
    elif isinstance(market_date, str):
        today = datetime.strptime(market_date, "%Y-%m-%d").date()
    else:
        today = market_date

    if today in NYSE_HOLIDAYS_2026 or today.weekday() >= 5:
        return  # Silent on holidays and weekends

    today_str = today.strftime("%Y-%m-%d")
    decision_rows = get_todays_buy_signals(today)
    bought = [r for r in decision_rows if r.get("category") == "bought"]
    blocked = [r for r in decision_rows if r.get("category") == "blocked_earnings"]
    armed = sorted([r for r in decision_rows if r.get("category") == "armed"], key=lambda r: (_num(r.get("pct_over_ema"), 999999), r.get("ticker", "")))
    too_hot = sorted([r for r in decision_rows if r.get("category") == "too_hot"], key=lambda r: (_num(r.get("pct_over_ema"), -999999), r.get("ticker", "")), reverse=True)
    no_data = [r for r in decision_rows if r.get("category") == "no_data"]

    positions = get_positions_pnl()
    watch_rows = get_handoff_close_performance(today)
    gainers, losers = get_top_movers()
    catalyst_hits, checked, win_start, win_end = get_engine_catalyst_watchlist(today, now_et=now_et)
    account = get_account_snapshot(positions)

    lines = [
        "─────────────────────────────────────────",
        f"📊 POST-MARKET REPORT — {today_str}",
        "═══════════════════════════════",
        "",
        "1️⃣ ENGINE DECISIONS",
    ]

    _append_decision_group(
        lines,
        "✅ BOUGHT",
        bought,
        lambda r: f"      • {r['ticker']} — {r.get('score_num', 0)}/4 pillars · entry {_fmt_price(r.get('entry'))} · stop {_fmt_price(r.get('stop'))} · {r.get('shares', 'N/A')} sh · {_fmt_pct(r.get('risk_pct'), signed=False)} risk",
    )
    _append_decision_group(
        lines,
        "⛔ BLOCKED — EARNINGS",
        blocked,
        lambda r: f"      • {r['ticker']} — earnings in {r.get('days', 'N/A')}d",
    )
    _append_decision_group(
        lines,
        "🎣 ARMED — WAITING PULLBACK",
        armed,
        lambda r: f"      • {r['ticker']} — {_fmt_price(r.get('price'))} (+{_num(r.get('pct_over_ema'), 0):.2f}% > EMA) · limit {_fmt_price(r.get('limit'))}",
    )
    _append_decision_group(
        lines,
        "🚀 TOO HOT — SKIPPED",
        too_hot,
        lambda r: f"      • {r['ticker']} — +{_num(r.get('pct_over_ema'), 0):.2f}% > EMA",
    )
    _append_decision_group(
        lines,
        "⏸️ NO DATA",
        no_data,
        lambda r: f"      • {r['ticker']} — {r.get('reason') or 'N/A'}",
    )
    lines.append("")

    if positions:
        lines.append(f"2️⃣ OPEN POSITIONS ({len(positions)})")
        for p in positions:
            base = f"   • {p['ticker']} — {p.get('quantity', 'N/A')} sh · entry {_fmt_price(p.get('entry'))} · stop {_fmt_price(p.get('stop'))} · close {_fmt_price(p.get('close'))}"
            if p.get("pnl") is not None and p.get("pnl_pct") is not None:
                base += f" · P/L {_fmt_money(p.get('pnl'))} ({_fmt_pct(p.get('pnl_pct'))})"
            lines.append(base)
    else:
        lines.append("2️⃣ OPEN POSITIONS — none")
    lines.append("")

    lines.append(f"3️⃣ WATCHLIST CLOSE ({len(watch_rows)})")
    if watch_rows:
        lines.extend(_format_watchlist_row(r) for r in watch_rows)
    else:
        lines.append("   ⚪ N/A    N/A        —")
    lines.append("")

    lines.append("4️⃣ MARKET MOVERS")
    lines.append("   🏆 Top Gainers")
    lines.extend([_format_mover_row(r, up=True) for r in gainers] or ["      • None"])
    lines.append("   💀 Top Losers")
    lines.extend([_format_mover_row(r, up=False) for r in losers] or ["      • None"])
    lines.append("")

    lines.append(f"5️⃣ CATALYST WATCH — TOMORROW ({len(catalyst_hits)} hits / {len(checked)} checked)")
    lines.append(f"   ⏱️ Window: {win_start.strftime('%m/%d %H:%M ET')} → {win_end.strftime('%m/%d %H:%M ET')}")
    if catalyst_hits:
        for hit in catalyst_hits:
            suffix = hit.get("just_in") or ""
            lines.append(f"   • {hit['ticker']}{suffix} — {_fmt_et(hit['published'])} — {hit['reason']}")
    else:
        lines.append("   • No strong per-ticker catalysts found.")
    lines.append("")

    lines.append("6️⃣ BOTTOM LINE")
    lines.append(f"   • 📈 Decisions: {len(decision_rows)}  ·  ✅ Bought: {len(bought)}  ·  🎣 Armed: {len(armed)}  ·  ⛔ Blocked: {len(blocked)}")
    lines.append(f"   • 💼 Open positions: {len(positions)}")
    lines.append(f"   • 💰 Cash: {_fmt_money(account.get('cash'))}  ·  Equity: {_fmt_money(account.get('equity'))}")
    lines.append("   • 🌙 Market closed. Handoff written. See you tomorrow, Prof.")
    lines.append("─────────────────────────────────────────")

    message = "\n".join(lines)
    if send:
        send_telegram(message)
    return message

if __name__ == "__main__":
    generate_post_market_report()
