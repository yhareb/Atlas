import os, sys, re, requests
from atlas_notify import send_telegram as _send_telegram
from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
from atlas_time import current_et_market_date, current_et_market_date_str, previous_et_trading_date_str
from atlas_engine import _llm_judge_catalyst

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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MASSIVE_BASE = "https://api.massive.com"
INDEX_ETF_BLOCKLIST = {"SPY", "QQQ", "DIA"}

NYSE_HOLIDAYS_2026 = {
    date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),
    date(2026,5,25),date(2026,6,19),date(2026,7,3),date(2026,9,7),
    date(2026,11,26),date(2026,11,27),date(2026,12,25),
}

def send_telegram(message):
    return _send_telegram(message, label="pre_market")

def massive_get(path, params=None):
    p = params or {}
    p["apiKey"] = MASSIVE_API_KEY
    try:
        r = requests.get(f"{MASSIVE_BASE}{path}", params=p, timeout=10)
        if r.status_code == 200: return r.json()
    except Exception as e: print(f"[Massive error] {path}: {e}")
    return None

def arrow(pct):
    if pct is None: return "—"
    return f"▲ +{pct:.2f}%" if pct > 0 else (f"▼ {pct:.2f}%" if pct < 0 else f"→ {pct:.2f}%")

def get_futures():
    # Massive futures feed is not entitled on current plan, so use liquid index ETFs as proxies.
    lines = []
    for sym, label in [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("DIA", "Dow Jones")]:
        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{sym}")
        t = (snap or {}).get("ticker") if snap else None
        if t:
            price = (t.get("day") or {}).get("c") or (t.get("prevDay") or {}).get("c")
            pct = t.get("todaysChangePerc")
            lines.append(f"  {label} ({sym}): ${price:,.2f}  {arrow(pct)}" if price else f"  {label} ({sym}): N/A")
        else:
            lines.append(f"  {label} ({sym}): N/A")
    return lines

def get_top_movers():
    gl, ll = [], []
    for direction, lst in [("gainers", gl), ("losers", ll)]:
        data = massive_get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
        if data and data.get("tickers"):
            for t in data["tickers"][:5]:
                ticker = t.get("ticker","?"); pct = t.get("todaysChangePerc",0)
                price = (t.get("day") or {}).get("c")
                sym = "▲ +" if direction == "gainers" else "▼ "
                lst.append(f"  • {ticker} {'$'+f'{price:.2f}' if price else 'N/A'}  {sym}{abs(pct):.2f}%")
    return gl, ll

def get_handoff_snapshot():
    market_day = current_et_market_date()
    today = market_day.strftime('%Y-%m-%d')
    yesterday = previous_et_trading_date_str(market_day)
    data = atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday)
    if not data: return [], []
    bl, wl = [], []
    for ticker in data.get("BUY",[]):
        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        if snap and snap.get("ticker"):
            t = snap["ticker"]; price = (t.get("day") or {}).get("c"); pct = t.get("todaysChangePerc")
            bl.append(f"  • {ticker} {'$'+f'{price:.2f}' if price else 'N/A'}  {arrow(pct)}")
        else: bl.append(f"  • {ticker}")
    for ticker in data.get("WATCH",[]):
        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        if snap and snap.get("ticker"):
            t = snap["ticker"]; price = (t.get("day") or {}).get("c"); pct = t.get("todaysChangePerc")
            wl.append(f"  • {ticker} {'$'+f'{price:.2f}' if price else 'N/A'}  {arrow(pct)}")
        else: wl.append(f"  • {ticker}")
    return bl, wl

def get_benzinga_headlines():
    since = (datetime.utcnow()-timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    data = massive_get("/v2/reference/news", {"published_utc.gte": since, "limit": 5, "sort": "published_utc", "order": "desc"})
    if data and data.get("results"):
        return [f"  • {a.get('title','No title')}" for a in data["results"][:5]]
    return []


def _is_tradeable_symbol(sym):
    s = (sym or "").strip().upper()
    if not s or s in INDEX_ETF_BLOCKLIST:
        return False
    if s.startswith("$") or "." in s or "-" in s:
        return False
    return s.isalpha() and len(s) <= 5


def _dedupe_tickers(items, limit=35):
    out, seen = [], set()
    for sym in items or []:
        s = (sym or "").strip().upper()
        if _is_tradeable_symbol(s) and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _recent_signal_tickers(days=2):
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    conn = atlas_db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ticker FROM signals WHERE date(timestamp) >= ? ORDER BY ticker", (cutoff,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def get_discovery_universe(limit=35):
    names = []
    try:
        from market_scout import discover_tickers
        names.extend(discover_tickers() or [])
    except Exception as e:
        print(f"[pre-market] discovery skipped: {e}")
    try:
        market_day = current_et_market_date()
        today = market_day.strftime('%Y-%m-%d')
        yesterday = previous_et_trading_date_str(market_day)
        data = atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday) or {}
        names.extend(data.get("BUY", []) or [])
        names.extend(data.get("WATCH", []) or [])
    except Exception:
        pass
    names.extend(_recent_signal_tickers(days=2))
    try:
        from atlas_manage import DEFAULT_UNIVERSE
        names.extend(DEFAULT_UNIVERSE)
    except Exception:
        pass
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


def premarket_news_window(now_et=None):
    now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
    prev_close_day = _previous_trading_day(now_et.date())
    start_et = datetime.combine(prev_close_day, time(16, 0), ZoneInfo("America/New_York"))
    today_open_et = datetime.combine(now_et.date(), time(9, 30), ZoneInfo("America/New_York"))
    end_et = min(now_et, today_open_et)
    return start_et, end_et


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


def get_engine_catalyst_watchlist(limit=35, max_hits=12):
    tickers = get_discovery_universe(limit=limit)
    start_et, end_et = premarket_news_window()
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
            print(f"[pre-market] LLM catalyst judge failed for {ticker}: {e}")
            verdict = None
        if verdict is not None:
            rating, reason = verdict
            if str(rating).upper() == "STRONG":
                published = articles[0]["published_utc"]
                lines.append(f"  {len(lines)+1}. 🔥 {ticker} — {_fmt_et(published)} — {_clean_catalyst_reason(reason)}")
        if len(lines) >= max_hits:
            break
    return lines, checked, start_et, end_et

# --- Wave F comprehensive pre-market scout helpers -------------------------
def eodhd_get(path, params=None):
    key = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
    if not key:
        return None
    p = params or {}; p["api_token"] = key; p["fmt"] = "json"
    try:
        r = requests.get(f"https://eodhd.com/api{path}", params=p, timeout=10)
        if r.status_code == 200: return r.json()
        print(f"[EODHD pre-market] {path} HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e: print(f"[EODHD pre-market] {path}: {e}")
    return None


def _sentiment_line(ticker):
    data = eodhd_get("/sentiments", {"s": f"{ticker}.US"})
    try:
        rows = data.get(f"{ticker}.US") if isinstance(data, dict) else None
        row = rows[0] if rows else None
        val = float(row.get("normalized")) if row else None
        return f"{'🟢' if val >= 0 else '🔴'} {ticker} sentiment {val:+.1f}" if val is not None else None
    except Exception: return None


def get_wavef_screener_names(limit=20):
    import json as _json
    filters = [["refund_1d_p", ">", 3], ["avgvol_200d", ">", 1000000], ["exchange", "=", "US"], ["market_capitalization", ">", 300000000]]
    data = eodhd_get("/screener", {"filters": _json.dumps(filters), "limit": limit, "sort": "refund_1d_p.desc"}) or {}
    out=[]
    for row in data.get("data") or []:
        sym=(row.get("code") or "").upper(); price=row.get("adjusted_close")
        if _is_tradeable_symbol(sym) and price and float(price) >= 5:
            out.append(f"  • {sym} ${float(price):.2f}  ▲ +{float(row.get('refund_1d_p') or 0):.1f}%  {row.get('sector','')}")
    return out


def get_wavef_earnings(limit=8):
    today=current_et_market_date_str(); data=massive_get("/benzinga/v1/earnings", {"date.gte":today,"date.lte":today,"limit":limit}) or {}
    lines=[]
    for row in data.get("results") or []:
        t=row.get("ticker"); eps=row.get("eps_surprise_percent"); rev=row.get("revenue_surprise_percent"); bits=[]
        if eps is not None: bits.append(f"EPS {float(eps)*100:+.0f}%")
        if rev is not None: bits.append(f"Rev {float(rev)*100:+.0f}%")
        if t and bits: lines.append(f"  • {t} — {' / '.join(bits)}")
    return lines


def get_wavef_analyst_actions(limit=8):
    today=current_et_market_date_str(); data=massive_get("/benzinga/v1/ratings", {"date.gte":today,"limit":limit}) or {}
    lines=[]
    for row in data.get("results") or []:
        t=row.get("ticker"); firm=row.get("firm"); rating=row.get("rating"); pt=row.get("price_target") or row.get("adjusted_price_target"); act=row.get("price_target_action")
        if t: lines.append(f"  • {t} — {firm or 'Analyst'} {rating or ''} PT {'$'+str(int(float(pt))) if pt else 'N/A'} {act or ''}")
    return lines


def get_wavef_macro():
    today=current_et_market_date_str(); data=eodhd_get("/economic-events", {"from":today,"to":today,"country":"US"}) or []
    lines=[]
    for row in data[:12] if isinstance(data, list) else []:
        typ=row.get("type") or "Event"; when=row.get("date") or ""; flag="⚠️" if any(w in typ.lower() for w in ("fed","fomc","cpi","consumer price index")) else "•"
        lines.append(f"  {flag} {typ} — {when}")
    return lines


def get_wavef_insider_buys(limit=6):
    names=_dedupe_tickers(get_discovery_universe(limit=10), limit=10); lines=[]
    try:
        from atlas_engine import check_insider_buying
        for t in names:
            hit, detail = check_insider_buying(t)
            if hit: lines.append(f"  • {t} — {(detail or {}).get('note') if isinstance(detail, dict) else detail}")
            if len(lines) >= limit: break
    except Exception as e: print(f"[pre-market] insider scan skipped: {e}")
    return lines


def generate_wavef_pre_market_brief(send=False):
    today_str=current_et_market_date_str(); futures=get_futures(); gainers,losers=get_top_movers(); screen=get_wavef_screener_names(); earnings=get_wavef_earnings(); analysts=get_wavef_analyst_actions(); macro=get_wavef_macro(); buy_lines,watch_lines=get_handoff_snapshot(); catalysts,checked,win_start,win_end=get_engine_catalyst_watchlist(limit=25,max_hits=8); insiders=get_wavef_insider_buys()
    sent=[]
    for line in (gainers[:3]+screen[:3]):
        parts=line.replace('•','').split(); sent.append(_sentiment_line(parts[0]) if parts else None)
    sent=[x for x in sent if x]
    lines=[f"🌄 *PRE-MARKET BRIEF — {today_str}*", "", "*🧭 Market Sentiment Overview:*"]
    lines.extend(futures or ["  N/A"])
    if sent: lines.append("  News sentiment: " + " | ".join(sent[:4]))
    lines += ["", "*🚀 Pre-Market Movers / Gappers:*"] + (gainers[:8] or ["  None yet"])
    lines += ["", "*🧪 Screener Fresh Names:*"] + (screen or ["  None found"])
    lines += ["", "*📰 News + Sentiment Catalysts:*"] + (catalysts or ["  No strong fresh catalysts found"])
    lines += ["", "*📊 Overnight Earnings:*"] + (earnings or ["  No EPS/revenue surprise rows found"])
    lines += ["", "*🏦 Analyst Actions / PT Changes:*"] + (analysts or ["  No fresh analyst rows found"])
    lines += ["", "*🏛 Insider Buys:*"] + (insiders or ["  No notable open-market insider buys found in scanned names"])
    lines += ["", "*⚠️ Macro Events Today:*"] + (macro or ["  No macro events returned"])
    if buy_lines or watch_lines: lines += ["", "*🎯 Setups Armed For The Day:*"] + (buy_lines[:6] + watch_lines[:8])
    lines += ["", "_Scouting only — no pre-market trades._"]
    msg="\n".join(lines)
    if send: send_telegram(msg)
    return msg
# --------------------------------------------------------------------------

def _llm_brief(futures, gainers, losers, buy_lines, watch_lines, headlines):
    if not OPENAI_API_KEY:
        return None
    facts = []
    if futures:    facts.append("Futures:\n" + "\n".join(futures))
    if gainers:    facts.append("Top gainers:\n" + "\n".join(gainers))
    if losers:     facts.append("Top losers:\n" + "\n".join(losers))
    if buy_lines:  facts.append("Active BUY signals:\n" + "\n".join(buy_lines))
    if watch_lines:facts.append("WATCH list:\n" + "\n".join(watch_lines))
    if headlines:  facts.append("Per-ticker engine catalysts:\n" + "\n".join(headlines))
    if not facts:
        return None
    prompt = (
        "You are Atlas, a systematic swing-trading advisor briefing your principal 15 minutes "
        "before the US market open. Using ONLY the data below, write a tight 3-4 sentence "
        "pre-market read. Lead with the overall risk tone (risk-on / risk-off / mixed) based on "
        "futures. Note anything notable in movers, the BUY/WATCH names, or headlines that affects "
        "today's plan. Be concrete and use numbers. Start each sentence with a relevant emoji. "
        "NO links, NO URLs, NO disclaimers, NO greeting, NO sign-off. Plain text only.\n\n"
        + "\n\n".join(facts)
    )
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 220,
            },
            timeout=8,
        )
        if r.status_code == 200:
            txt = r.json()["choices"][0]["message"]["content"].strip()
            return txt or None
        print(f"[LLM brief] HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[LLM brief] failed: {e}")
    return None

def generate_pre_market_report(send=True):
    now_et = datetime.now(ZoneInfo("America/New_York"))
    today = current_et_market_date(now_et)
    if today in NYSE_HOLIDAYS_2026 or today.weekday() >= 5: return
    today_str = today.strftime("%Y-%m-%d")
    # Wave F comprehensive scout replaces the older idle-style brief.
    return generate_wavef_pre_market_brief(send=send)
    lines = [f"🌄 *Pre-Market Brief — {today_str}*", ""]
    lines.append("*Index Proxies (ETF):*"); lines.extend(get_futures() or ["  N/A"]); lines.append("")
    gainers, losers = get_top_movers()
    lines.append("*Top Pre-Market Gainers:*"); lines.extend(gainers or ["  None yet"]); lines.append("")
    lines.append("*Top Pre-Market Losers:*"); lines.extend(losers or ["  None yet"]); lines.append("")
    buy_lines, watch_lines = get_handoff_snapshot()
    if buy_lines: lines.append("*Active BUY Signals (from last night):*"); lines.extend(buy_lines); lines.append("")
    if watch_lines: lines.append("*WATCH List (from last night):*"); lines.extend(watch_lines); lines.append("")
    catalyst_lines, checked, win_start, win_end = get_engine_catalyst_watchlist()
    lines.append(f"*🔥 Engine Per-Ticker Catalysts ({len(catalyst_lines)} hits / {len(checked)} checked):*")
    lines.append(f"  Window: {win_start.strftime('%m/%d %H:%M ET')} → {win_end.strftime('%m/%d %H:%M ET')}")
    lines.extend(catalyst_lines or ["  0. No strong per-ticker catalysts found."])
    lines.append("")
    headlines = catalyst_lines
    _narr = _llm_brief(get_futures(), gainers, losers, buy_lines, watch_lines, headlines)
    if _narr:
        lines.insert(2, ""); lines.insert(2, _narr); lines.insert(2, "*🧠 Atlas Read:*")
    lines.append("_Ready for the open, Prof._")
    message = "\n".join(lines)
    if send:
        send_telegram(message)
    return message

if __name__ == "__main__":
    generate_pre_market_report()