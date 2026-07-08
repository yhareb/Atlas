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

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import atlas_db
import atlas_portfolio as port
from atlas_symbol_meta import normalize_snapshot_fields, ticker_label
from atlas_report_blocks import holding_block
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

NYSE_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 25),
}


def _space_report_items(message: str) -> str:
    out = []
    prev_item = False
    for line in str(message).splitlines():
        stripped = line.strip()
        is_item = bool(re.match(r"^(?:\d+\.|[-•]|[🟢🟡🔴🔹🔸🚀📈🎣🔥])\s+", stripped))
        if is_item and prev_item and out and out[-1].strip():
            out.append("")
        out.append(line)
        prev_item = is_item
        if not stripped:
            prev_item = False
    return "\n".join(out)

# ── Helpers ───────────────────────────────────────────────────────────────────

def send_telegram(message):
    return _send_telegram(message, label="post_market", route="professor_dm", report_type="post_market")

def massive_get(path, params=None):
    headers = {"Authorization": f"Bearer {MASSIVE_API_KEY}"}
    p = params or {}
    p["apiKey"] = MASSIVE_API_KEY
    try:
        r = _audit_get(f"{MASSIVE_BASE}{path}", headers=headers, params=p, timeout=10)
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
        t = normalize_snapshot_fields(ticker, snap["ticker"])
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
            t = normalize_snapshot_fields(ticker, t)
            pct = t.get("todaysChangePerc", 0)
            price = (t.get("day") or {}).get("c")
            price_str = f"${price:.2f}" if price else "N/A"
            gainer_lines.append(f"  • {ticker} {price_str}  ▲ +{pct:.2f}%")

    if losers_data and losers_data.get("tickers"):
        for t in losers_data["tickers"][:5]:
            ticker = t.get("ticker", "?")
            t = normalize_snapshot_fields(ticker, t)
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
            stop = pos.get("stop_loss")
            stop_str = f"  Stop: ${float(stop):.2f}" if stop not in (None, "") else ""
            lines.append(
                f"  • {ticker}  Qty: {qty}  Entry: ${entry:.2f}{stop_str} → Close: ${close:.2f}  "
                f"{pct_arrow(pct)}{pnl_str}"
            )
        else:
            stop = pos.get("stop_loss")
            stop_str = f"  Stop: ${float(stop):.2f}" if stop not in (None, "") else ""
            lines.append(f"  • {ticker}  Qty: {qty}  Entry: ${entry:.2f}{stop_str}  Close: N/A")

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


def get_engine_catalyst_watchlist(market_date=None, limit=40, max_hits=12, now_et=None):
    tickers = get_postmarket_catalyst_universe(market_date=market_date, limit=limit)
    start_et, end_et = postmarket_news_window(now_et=now_et)
    now_utc = (now_et.astimezone(timezone.utc) if now_et else datetime.now(timezone.utc))
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

def _pm_num(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(',', ''))
    except Exception:
        return default


def _pm_money(value):
    n = _pm_num(value)
    return "N/A" if n is None else f"${n:,.2f}"


def _pm_pct(value, signed=True, width=0):
    n = _pm_num(value)
    if n is None:
        out = "—"
    elif signed:
        out = f"{n:+.2f}%"
    else:
        out = f"{n:.2f}%"
    return out.rjust(width) if width else out


def _pm_ticker(ticker, width=6):
    return str(ticker or "?").upper().ljust(width)


def _parse_close_line(line):
    m = re.search(r"•\s+(\S+)\s+Close:\s+\$([\d,.]+)\s+\(([+-]?[\d.]+)%\)", line or "")
    if m:
        return {"ticker": m.group(1).upper(), "close": _pm_num(m.group(2)), "pct": _pm_num(m.group(3))}
    m = re.search(r"•\s+(\S+)\s+Close:\s+N/A", line or "")
    if m:
        return {"ticker": m.group(1).upper(), "close": None, "pct": None}
    return None


def _parse_mover_line(line):
    m = re.search(r"•\s+(\S+)\s+\$([\d,.]+)\s+[▲▼]\s+([+-]?[\d.]+)%", line or "")
    if m:
        return {"ticker": m.group(1).upper(), "price": _pm_num(m.group(2)), "pct": _pm_num(m.group(3))}
    return None


def _parse_position_line(line):
    m = re.search(r"•\s+(\S+)\s+Qty:\s+([\d,.]+)\s+Entry:\s+\$([\d,.]+)(?:\s+Stop:\s+\$([\d,.]+))?\s+→\s+Close:\s+\$([\d,.]+).*?Total P&L:\s+([▲▼→])\s+([+-]?\$?[\d,.]+)", line or "")
    if m:
        pnl = _pm_num(str(m.group(7)).replace('$', ''))
        if m.group(6) == '▼' and pnl is not None:
            pnl = -abs(pnl)
        return {"ticker": m.group(1).upper(), "qty": _pm_num(m.group(2)), "entry": _pm_num(m.group(3)), "stop": _pm_num(m.group(4)), "close": _pm_num(m.group(5)), "pnl": pnl}
    m = re.search(r"•\s+(\S+)\s+Qty:\s+([\d,.]+)\s+Entry:\s+\$([\d,.]+)(?:\s+Stop:\s+\$([\d,.]+))?.*Close:\s+N/A", line or "")
    if m:
        return {"ticker": m.group(1).upper(), "qty": _pm_num(m.group(2)), "entry": _pm_num(m.group(3)), "stop": _pm_num(m.group(4)), "close": None, "pnl": None}
    m = re.search(r"•\s+(\S+)\s+Entry:\s+\$([\d,.]+)\s+→\s+Close:\s+\$([\d,.]+).*?Total P&L:\s+([▲▼→])\s+([+-]?\$?[\d,.]+)", line or "")
    if m:
        pnl = _pm_num(str(m.group(5)).replace('$', ''))
        if m.group(4) == '▼' and pnl is not None:
            pnl = -abs(pnl)
        return {"ticker": m.group(1).upper(), "entry": _pm_num(m.group(2)), "close": _pm_num(m.group(3)), "pnl": pnl}
    m = re.search(r"•\s+(\S+)\s+Entry:\s+\$([\d,.]+).*Close:\s+N/A", line or "")
    if m:
        return {"ticker": m.group(1).upper(), "entry": _pm_num(m.group(2)), "close": None, "pnl": None}
    return None


def _parse_decision_line(line):
    s = (line or "").strip()
    if not s.startswith("•"):
        return None
    m = re.search(r"BUY — (\S+) \((\d+)/4 Pillars\): entry \$([\d,.]+), stop \$([\d,.]+), size (\d+) sh, risk ([\d.]+)%", s)
    if m:
        return {"cat": "bought", "ticker": m.group(1).upper(), "score": int(m.group(2)), "entry": _pm_num(m.group(3)), "stop": _pm_num(m.group(4)), "shares": int(m.group(5)), "risk": _pm_num(m.group(6))}
    m = re.search(r"EARNINGS\s+in\s+(\d+)d", s, re.I)
    if "BLOCK" in s and m:
        tm = re.search(r"(?:BLOCK|—)\s+—?\s*(\S+)", s)
        ticker = tm.group(1).upper() if tm else "?"
        return {"cat": "blocked", "ticker": ticker, "days": int(m.group(1))}
    m = re.search(r"WAITING FOR PULLBACK — (\S+) \((\d+)/4 Pillars\): price \$([\d,.]+) = \+([\d.]+)% over 10-EMA\. Limit armed at \$([\d,.]+)", s)
    if m:
        return {"cat": "armed", "ticker": m.group(1).upper(), "score": int(m.group(2)), "price": _pm_num(m.group(3)), "over": _pm_num(m.group(4)), "limit": _pm_num(m.group(5))}
    m = re.search(r"TOO EXTENDED — (\S+) \(\+([\d.]+)% over 10-EMA\)", s)
    if m:
        return {"cat": "hot", "ticker": m.group(1).upper(), "over": _pm_num(m.group(2))}
    m = re.search(r"WAIT — (\S+) \((\d+)/4 Pillars\):\s*(.+)", s)
    if m:
        return {"cat": "nodata", "ticker": m.group(1).upper(), "score": int(m.group(2)), "reason": m.group(3)}
    m = re.search(r"DECISION UNAVAILABLE|NO BUY|WAIT|SKIP|BLOCK", s)
    if m:
        tm = re.search(r"•\s+(?:\S+\s+—\s+)?(\S+)", s)
        return {"cat": "nodata", "ticker": (tm.group(1).upper() if tm else "?"), "reason": s.lstrip('• ').strip()}
    return None


def _parse_catalyst_line(line):
    m = re.search(r"(?:\d+\.\s*)?🔥\s+(\S+)(?:\s+🚨 JUST IN)?\s+—\s+(?:\d\d/\d\d\s+\d\d:\d\d\s+ET\s+—\s+)?(.+)", line or "")
    if m:
        return {"ticker": m.group(1).upper(), "reason": m.group(2).strip()}
    return None


def _account_snapshot_for_display():
    conn = atlas_db.get_connection()
    cur = conn.cursor()
    cash = None
    equity = None
    try:
        row = cur.execute("SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            cash = row[0]
    except Exception:
        pass
    try:
        row = cur.execute("SELECT starting_cash FROM account ORDER BY id ASC LIMIT 1").fetchone()
        if row:
            equity = row[0]
            if cash is None:
                cash = row[0]
    except Exception:
        pass
    conn.close()
    return cash, equity


def _format_watch_close(row):
    pct = row.get("pct")
    icon = "⚪" if pct is None else ("🟢" if pct >= 0 else "🔴")
    price = "N/A" if row.get("close") is None else _pm_money(row.get("close"))
    return f"   {icon} {ticker_label(row.get('ticker')).ljust(32)} {price.rjust(10)}   {_pm_pct(pct, width=8)}"


def _format_mover(row, up=True):
    arrow = "▲" if up else "▼"
    pct = row.get("pct")
    pct_text = "—" if pct is None else f"{arrow} {pct:+.2f}%"
    return f"      • {ticker_label(row.get('ticker')).ljust(32)} {_pm_money(row.get('price')).rjust(10)}   {pct_text.rjust(10)}"


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
    from atlas_report_handoff import build_atlas_handoff_report
    message = _space_report_items(build_atlas_handoff_report(context="post_market", report_date=today))
    if send:
        send_telegram(message)
    return message

    buy_close_lines, watch_close_lines = get_handoff_close_performance(today)
    close_rows = []
    seen = set()
    for raw in (buy_close_lines or []) + (watch_close_lines or []):
        row = _parse_close_line(raw)
        if row and row["ticker"] not in seen:
            seen.add(row["ticker"])
            close_rows.append(row)
    close_rows.sort(key=lambda r: (_pm_num(r.get("pct"), -999999), r.get("ticker", "")), reverse=True)

    gainer_lines, loser_lines = get_top_movers()
    gainers = [r for r in (_parse_mover_line(x) for x in (gainer_lines or [])) if r]
    losers = [r for r in (_parse_mover_line(x) for x in (loser_lines or [])) if r]

    pos_lines = get_positions_pnl()
    positions = [r for r in (_parse_position_line(x) for x in (pos_lines or [])) if r]

    decision_lines = get_todays_buy_signals(today)
    decisions = [r for r in (_parse_decision_line(x) for x in (decision_lines or [])) if r]
    bought = [d for d in decisions if d.get("cat") == "bought"]
    blocked = [d for d in decisions if d.get("cat") == "blocked"]
    armed = sorted([d for d in decisions if d.get("cat") == "armed"], key=lambda d: (_pm_num(d.get("over"), 999999), d.get("ticker", "")))
    hot = sorted([d for d in decisions if d.get("cat") == "hot"], key=lambda d: (_pm_num(d.get("over"), -999999), d.get("ticker", "")), reverse=True)
    nodata = [d for d in decisions if d.get("cat") == "nodata"]

    catalyst_lines, checked, win_start, win_end = get_engine_catalyst_watchlist(today, now_et=now_et)
    catalysts = [r for r in (_parse_catalyst_line(x) for x in (catalyst_lines or [])) if r]
    cash, equity = _account_snapshot_for_display()

    lines = [
        "─────────────────────────────────────────",
        f"📊 POST-MARKET REPORT — {today_str}",
        "═══════════════════════════════",
        "",
        "1️⃣ ENGINE DECISIONS",
        f"   ✅ BOUGHT ({len(bought)})",
    ]
    for d in bought:
        lines.append(f"      • {ticker_label(d['ticker'])} — {d.get('score', 0)}/4 pillars · entry {_pm_money(d.get('entry'))} · stop {_pm_money(d.get('stop'))} · {d.get('shares', 'N/A')} sh · {_pm_pct(d.get('risk'), signed=False)} risk")
    lines.append(f"   ⛔ BLOCKED — EARNINGS ({len(blocked)})")
    for d in blocked:
        lines.append(f"      • {ticker_label(d['ticker'])} — earnings in {d.get('days', 'N/A')}d")
    lines.append(f"   🎣 ARMED — WAITING PULLBACK ({len(armed)})")
    for d in armed:
        lines.append(f"      • {ticker_label(d['ticker'])} — {_pm_money(d.get('price'))} (+{_pm_num(d.get('over'), 0):.2f}% > EMA) · limit {_pm_money(d.get('limit'))}")
    lines.append(f"   🚀 TOO HOT — SKIPPED ({len(hot)})")
    for d in hot:
        lines.append(f"      • {ticker_label(d['ticker'])} — +{_pm_num(d.get('over'), 0):.2f}% > EMA")
    lines.append(f"   ⏸️ NO DATA ({len(nodata)})")
    for d in nodata:
        lines.append(f"      • {ticker_label(d['ticker'])} — {d.get('reason') or 'N/A'}")
    lines.append("")

    lines.append("2️⃣ OPEN POSITIONS")
    holding_rows = []
    for p in positions:
        holding_rows.append({
            "ticker": p.get("ticker"),
            "entry_price": p.get("entry"),
            "current_price": p.get("close"),
            "stop_loss": p.get("stop"),
            "target_price": p.get("target"),
            "quantity": p.get("qty"),
            "unrealized_pl_usd": p.get("pnl"),
        })
    lines.extend(holding_block(holding_rows, {}))

    lines.append(f"3️⃣ WATCHLIST CLOSE ({len(close_rows)})")
    lines.extend([_format_watch_close(r) for r in close_rows] or ["   ⚪ N/A    N/A        —"])
    lines.append("")

    lines.append("4️⃣ MARKET MOVERS")
    lines.append("   🏆 Top Gainers")
    lines.extend([_format_mover(r, up=True) for r in gainers] or ["      • None"])
    lines.append("   💀 Top Losers")
    lines.extend([_format_mover(r, up=False) for r in losers] or ["      • None"])
    lines.append("")

    win_start_txt = win_start.strftime('%m/%d %H:%M ET') if win_start else 'N/A'
    win_end_txt = win_end.strftime('%m/%d %H:%M ET') if win_end else 'N/A'
    lines.append(f"5️⃣ CATALYST WATCH — TOMORROW ({len(catalysts)} hits / {len(checked)} checked)")
    lines.append(f"   ⏱️ Window: {win_start_txt} → {win_end_txt}")
    if catalysts:
        for c in catalysts:
            lines.append(f"   • {ticker_label(c['ticker'])} — {c['reason']}")
    else:
        lines.append("   • No strong per-ticker catalysts found.")
    lines.append("")

    lines.append("6️⃣ BOTTOM LINE")
    lines.append(f"   • 📈 Decisions: {len(decisions)}  ·  ✅ Bought: {len(bought)}  ·  🎣 Armed: {len(armed)}  ·  ⛔ Blocked: {len(blocked)}")
    lines.append(f"   • 💼 Open positions: {len(positions)}")
    lines.append(f"   • 💰 Cash: {_pm_money(cash)}  ·  Equity: {_pm_money(equity)}")
    lines.append("   • 🌙 Market closed. Handoff written. See you tomorrow, Prof.")
    lines.append("─────────────────────────────────────────")

    message = _space_report_items("\n".join(lines))
    if send:
        send_telegram(message)
    return message

if __name__ == "__main__":
    generate_post_market_report()
