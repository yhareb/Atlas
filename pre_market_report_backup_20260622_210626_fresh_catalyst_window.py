import os, sys, re, requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
sys.path.insert(0, "/Users/yasser/scripts")
import atlas_db
from atlas_engine import check_news_catalyst

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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message); return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        if r.status_code != 200: print(f"[Telegram error] {r.status_code}: {r.text}")
    except Exception as e: print(f"[Telegram failed] {e}")

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
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d')
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
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
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


def get_engine_catalyst_watchlist(limit=35, max_hits=12):
    tickers = get_discovery_universe(limit=limit)
    lines, checked = [], []
    for ticker in tickers:
        checked.append(ticker)
        try:
            hit, reason = check_news_catalyst(ticker)
        except Exception as e:
            print(f"[pre-market] catalyst check failed for {ticker}: {e}")
            continue
        if hit:
            lines.append(f"  {len(lines)+1}. 🔥 {ticker} — {_clean_catalyst_reason(reason)}")
        if len(lines) >= max_hits:
            break
    return lines, checked

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
    today = now_et.date()
    if today in NYSE_HOLIDAYS_2026 or today.weekday() >= 5: return
    today_str = today.strftime("%Y-%m-%d")
    lines = [f"🌄 *Pre-Market Brief — {today_str}*", ""]
    lines.append("*Index Proxies (ETF):*"); lines.extend(get_futures() or ["  N/A"]); lines.append("")
    gainers, losers = get_top_movers()
    lines.append("*Top Pre-Market Gainers:*"); lines.extend(gainers or ["  None yet"]); lines.append("")
    lines.append("*Top Pre-Market Losers:*"); lines.extend(losers or ["  None yet"]); lines.append("")
    buy_lines, watch_lines = get_handoff_snapshot()
    if buy_lines: lines.append("*Active BUY Signals (from last night):*"); lines.extend(buy_lines); lines.append("")
    if watch_lines: lines.append("*WATCH List (from last night):*"); lines.extend(watch_lines); lines.append("")
    catalyst_lines, checked = get_engine_catalyst_watchlist()
    lines.append(f"*🔥 Engine Per-Ticker Catalysts ({len(catalyst_lines)} hits / {len(checked)} checked):*")
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