import os, sys, re, json, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from atlas_notify import send_telegram as _send_telegram, _admin_chat_id as _owner_chat_id
from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo
SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
from atlas_provider_guard import (
    BENZINGA_UNCOVERED as PROVIDER_BENZINGA_UNCOVERED,
    benzinga_get_json as _guard_benzinga_get_json,
    massive_get_json as _guard_massive_get_json,
)
import atlas_db
try:
    import atlas_rag
except Exception:
    atlas_rag = None
if os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB"):
    atlas_db.DB_PATH = os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB")
from atlas_symbol_meta import normalize_price, normalize_snapshot_fields, ticker_label
from atlas_report_blocks import holding_block, pullback_block, watch_list_block
from atlas_time import current_et_market_date, is_trading_day, current_et_market_date_str, previous_et_trading_date_str
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
BENZINGA_API_KEY = os.environ.get("BENZINGA_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MASSIVE_BASE = "https://api.massive.com"
INDEX_ETF_BLOCKLIST = {"SPY", "QQQ", "DIA"}


try:
    from atlas_audit import log_api_call as _atlas_log_api_call
except Exception:
    _atlas_log_api_call = None

import time as _audit_time
_REQUESTS_GET = requests.get
PRE_MARKET_HTTP_TIMEOUT = float(os.environ.get("PRE_MARKET_HTTP_TIMEOUT", "5"))
PRE_MARKET_MASSIVE_TIMEOUT = float(os.environ.get("PRE_MARKET_MASSIVE_TIMEOUT", str(PRE_MARKET_HTTP_TIMEOUT)))
PRE_MARKET_EARLY_MOVER_UNIVERSE_LIMIT = int(os.environ.get("PRE_MARKET_EARLY_MOVER_UNIVERSE_LIMIT", "40"))
PRE_MARKET_EARLY_MOVER_ENRICH_LIMIT = int(os.environ.get("PRE_MARKET_EARLY_MOVER_ENRICH_LIMIT", "6"))
PRE_MARKET_CATALYST_LIMIT = int(os.environ.get("PRE_MARKET_CATALYST_LIMIT", "15"))
PRE_MARKET_CATALYST_MAX_HITS = int(os.environ.get("PRE_MARKET_CATALYST_MAX_HITS", "6"))
BENZINGA_UNCOVERED = {"FCEL", "ZURA", "PCLA", "CNVS", "WSHP", "SDOT"}
BENZINGA_SKIP_SET = set()
PRE_MARKET_HANDOFF_BUY_LIMIT = int(os.environ.get("PRE_MARKET_HANDOFF_BUY_LIMIT", "6"))
PRE_MARKET_HANDOFF_WATCH_LIMIT = int(os.environ.get("PRE_MARKET_HANDOFF_WATCH_LIMIT", "8"))


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
                _atlas_log_api_call(
                    provider=provider,
                    file=os.path.basename(__file__),
                    function=sys._getframe(1).f_code.co_name,
                    endpoint=str(url),
                    http_status=status,
                    latency_ms=latency_ms,
                    ok=bool(status is not None and 200 <= int(status) < 400),
                    error=None,
                    metadata=None,
                )
            except Exception:
                pass
        return response
    except Exception as e:
        if provider and _atlas_log_api_call:
            try:
                latency_ms = int((_audit_time.perf_counter() - start) * 1000)
                _atlas_log_api_call(
                    provider=provider,
                    file=os.path.basename(__file__),
                    function=sys._getframe(1).f_code.co_name,
                    endpoint=str(url),
                    http_status=None,
                    latency_ms=latency_ms,
                    ok=False,
                    error=str(e)[:500],
                    metadata=None,
                )
            except Exception:
                pass
        raise

NYSE_HOLIDAYS_2026 = {
    date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),
    date(2026,5,25),date(2026,6,19),date(2026,7,3),date(2026,9,7),
    date(2026,11,26),date(2026,11,27),date(2026,12,25),
}

def _env_int(name):
    try:
        value = os.environ.get(name)
        return int(value) if value not in (None, "") else None
    except Exception:
        return None


def _reports_group_chat_id():
    # Retained for reference only; P0I-2 consolidates pre-market sends to Atlas DM.
    # Not used by send_telegram() below.
    return os.environ.get("ATLAS_REPORTS_GROUP_CHAT_ID")


def send_telegram(message):
    return _send_telegram(
        message,
        label="pre_market",
        chat_id=_owner_chat_id(),
        message_thread_id=None,
    )

def massive_get(path, params=None):
    p = params or {}
    p["apiKey"] = MASSIVE_API_KEY
    return _guard_massive_get_json(
        f"{MASSIVE_BASE}{path}",
        params=p,
        timeout=PRE_MARKET_MASSIVE_TIMEOUT,
        request_tag=f"pre_market_massive:{path}",
    )

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
                ticker = t.get("ticker", "?")
                label = ticker_label(ticker, t)
                pct = t.get("todaysChangePerc", 0)
                price = normalize_price(ticker, (t.get("day") or {}).get("c"))
                sym = "▲ +" if direction == "gainers" else "▼ "
                lst.append(f"  • {label} {'$'+f'{price:.2f}' if price else 'N/A'}  {sym}{abs(pct):.2f}%")
    return gl, ll

def get_handoff_snapshot(max_buy=PRE_MARKET_HANDOFF_BUY_LIMIT, max_watch=PRE_MARKET_HANDOFF_WATCH_LIMIT):
    market_day = current_et_market_date()
    today = market_day.strftime('%Y-%m-%d')
    yesterday = previous_et_trading_date_str(market_day)
    data = atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday)
    if not data: return [], []
    bl, wl = [], []
    # The Telegram report displays only a small armed subset; avoid snapshotting the full WATCH roster.
    for ticker in (data.get("BUY",[]) or [])[:max_buy]:
        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        if snap and snap.get("ticker"):
            t = normalize_snapshot_fields(ticker, snap["ticker"]); price = (t.get("day") or {}).get("c"); pct = t.get("todaysChangePerc")
            bl.append(f"  • {ticker_label(ticker, t)} {'$'+f'{price:.2f}' if price else 'N/A'}  {arrow(pct)}")
        else: bl.append(f"  • {ticker}")
    for ticker in (data.get("WATCH",[]) or [])[:max_watch]:
        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        if snap and snap.get("ticker"):
            t = normalize_snapshot_fields(ticker, snap["ticker"]); price = (t.get("day") or {}).get("c"); pct = t.get("todaysChangePerc")
            wl.append(f"  • {ticker_label(ticker, t)} {'$'+f'{price:.2f}' if price else 'N/A'}  {arrow(pct)}")
        else: wl.append(f"  • {ticker}")
    return bl, wl

def _parse_benzinga_dt(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    txt = str(value).strip()
    for parser in (
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
        lambda x: datetime.strptime(x, "%Y-%m-%dT%H:%M:%S"),
    ):
        try:
            dt = parser(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(txt)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        return dt.astimezone(timezone.utc) if dt else None
    except Exception:
        return None


def _headline_score(item):
    if isinstance(item, dict):
        title = str(item.get("title") or "")
        teaser = str(item.get("teaser") or "")
        channels = [str(c.get("name") if isinstance(c, dict) else c).lower() for c in (item.get("channels") or [])]
        tags = [str(t.get("name") if isinstance(t, dict) else t).lower() for t in (item.get("tags") or [])]
        rank = item.get("importance_rank")
    else:
        title, teaser, channels, tags, rank = str(item or ""), "", [], [], None
    text = f"{title} {teaser}".lower()
    keywords = (
        "fed", "fomc", "rate", "yield", "treasury", "inflation", "cpi", "pce", "jobs", "gdp",
        "stress test", "earnings", "guidance", "tariff", "china", "oil", "opec",
        "geopolitical", "war", "israel", "iran", "russia", "ukraine", "premarket",
        "futures", "nasdaq", "s&p", "dow", "chips", "chip", "semiconductor", "nvidia", "micron",
        "buyback", "dividend", "shares rise", "shares are trading", "soaring", "higher", "lower",
    )
    score = sum(1 for word in keywords if word in text)
    if any(c in {"movers", "top stories", "wiim", "after-hours center", "economics", "equities"} for c in channels):
        score += 5
    if any("why it's moving" in t for t in tags):
        score += 4
    try:
        score += max(0, 3 - int(rank or 3))
    except Exception:
        pass
    if any(c in {"analyst ratings", "price target"} for c in channels):
        score -= 3
    if "exploring the competitive space" in text:
        score -= 4
    return score


def get_benzinga_headlines(limit=5, hours=12):
    if not BENZINGA_API_KEY:
        return []
    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)
    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": BENZINGA_API_KEY,
        "dateFrom": since_utc.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
        "dateTo": now_utc.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
        "pageSize": 50,
        "displayOutput": "full",
        "sort": "created",
        "sortDir": "desc",
    }
    rows = _guard_benzinga_get_json(
        None,
        url,
        params=params,
        headers={"Accept": "application/json"},
        request_tag="pre_market_benzinga_headlines",
    ) or []
    candidates, seen = [], set()
    for item in rows if isinstance(rows, list) else []:
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        if not title or title.lower() in seen:
            continue
        published = _parse_benzinga_dt(item.get("created") or item.get("updated") or item.get("published"))
        if published and published < since_utc:
            continue
        seen.add(title.lower())
        candidates.append((published or now_utc, _headline_score(item), title))
    candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
    strong = [c for c in candidates if c[1] >= 4]
    selected = strong if len(strong) >= 3 else candidates
    return [f"  • {title}" for _published, _score, title in selected[:limit]]


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


def _parse_event_datetime_et(value):
    if not value:
        return None
    txt = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None
    if dt.tzinfo is None:
        # EODHD economic-event timestamps are delivered in UTC; convert before display/filtering.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("America/New_York"))


def _is_briefing_hours_et(dt_et):
    if not dt_et:
        return False
    return time(4, 0) <= dt_et.time() <= time(16, 0)


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
                lines.append(f"  {len(lines)+1}. 🔥 {ticker_label(ticker)} — {_fmt_et(published)} — {_clean_catalyst_reason(reason)}")
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
        r = _audit_get(f"https://eodhd.com/api{path}", params=p, timeout=PRE_MARKET_HTTP_TIMEOUT)
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
        return f"{'🟢' if val >= 0 else '🔴'} {ticker_label(ticker)} sentiment {val:+.1f}" if val is not None else None
    except Exception: return None


def get_wavef_screener_names(limit=20):
    import json as _json
    try:
        from atlas_engine import check_fundamentals
    except Exception:
        check_fundamentals = None
    filters = [["refund_1d_p", ">", 3], ["avgvol_200d", ">", 1000000], ["exchange", "=", "US"], ["market_capitalization", ">", 300000000]]
    data = eodhd_get("/screener", {"filters": _json.dumps(filters), "limit": limit, "sort": "refund_1d_p.desc"}) or {}
    out=[]; added=0
    for row in data.get("data") or []:
        sym=(row.get("code") or "").upper(); price=row.get("adjusted_close")
        if _is_tradeable_symbol(sym) and price and float(price) >= 5:
            tag=""
            if check_fundamentals and added < 5:
                try:
                    f = check_fundamentals(sym) or {}
                    tag = f"  {f.get('tag') or f.get('note') or ''}".rstrip()
                except Exception:
                    tag = ""
            out.append(f"  • {sym} ${float(price):.2f}  ▲ +{float(row.get('refund_1d_p') or 0):.1f}%  {row.get('sector','')}{tag}")
            added += 1
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


def _normalise_analyst_firm(name):
    value = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    words = [w for w in value.split() if w not in {"the", "and", "co", "company", "companies", "llc", "inc", "corp", "corporation", "securities", "capital", "markets"}]
    return "".join(words)


def _same_analyst_firm(action_firm, quote_firm):
    left = _normalise_analyst_firm(action_firm)
    right = _normalise_analyst_firm(quote_firm)
    return bool(left and right and left == right)


def get_wavef_analyst_actions(limit=8):
    today=current_et_market_date_str(); data=massive_get("/benzinga/v1/ratings", {"date.gte":today,"limit":limit}) or {}
    lines=[]
    for row in data.get("results") or []:
        t=(row.get("ticker") or "").upper(); firm=row.get("firm") or row.get("firm_name"); rating=row.get("rating"); pt=row.get("price_target") or row.get("adjusted_price_target"); act=row.get("price_target_action")
        if t:
            try:
                pt_txt = "$" + str(int(float(pt))) if pt is not None and str(pt).strip() != "" else "N/A"
            except Exception:
                pt_txt = "$" + str(pt).strip() if str(pt or "").strip() else "N/A"
            firm_txt = re.sub(r"\s+", " ", str(firm or "Analyst")).strip()
            rating_txt = re.sub(r"\s+", " ", str(rating or act or "Rating")).strip()
            lines.append(f"  • {t} - {firm_txt} {rating_txt} PT {pt_txt}")
    return lines


def get_wavef_macro():
    today=current_et_market_date_str(); data=eodhd_get("/economic-events", {"from":today,"to":today,"country":"US"}) or []
    events=[]
    for row in data if isinstance(data, list) else []:
        typ=row.get("type") or "Event"
        when_et = _parse_event_datetime_et(row.get("date"))
        if when_et is None or not _is_briefing_hours_et(when_et):
            continue
        flag="⚠️" if any(w in typ.lower() for w in ("fed","fomc","cpi","consumer price index")) else "•"
        events.append((when_et, f"  {flag} {when_et.strftime('%H:%M ET')} — {typ}"))
    events.sort(key=lambda item: item[0])
    return [line for _when_et, line in events[:12]]


def _fda_event_date(row):
    for key in ("target_date", "date", "event_date"):
        value = row.get(key)
        if value:
            try:
                return date.fromisoformat(str(value)[:10])
            except Exception:
                pass
    return None


def _fda_tickers(row):
    symbols=[]
    for company in row.get("companies") or []:
        for sec in company.get("securities") or []:
            sym=str(sec.get("symbol") or "").upper().strip()
            if sym: symbols.append(sym)
    return sorted(set(symbols))


def _armed_watchlist_symbols():
    symbols=set()
    try:
        market_day=current_et_market_date(); today=market_day.strftime('%Y-%m-%d'); yesterday=previous_et_trading_date_str(market_day)
        data=atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday) or {}
        symbols.update(str(x).upper() for x in (data.get("BUY") or []) if x)
        symbols.update(str(x).upper() for x in (data.get("WATCH") or []) if x)
    except Exception:
        pass
    try:
        symbols.update(str(r.get("ticker") or "").upper() for r in atlas_db.get_pending_pullbacks(status="WAITING") if r.get("ticker"))
    except Exception:
        pass
    return symbols


def get_wavef_fda_warnings():
    try:
        from atlas_engine import _load_fda_calendar_window
        payload = _load_fda_calendar_window() or {}
    except Exception:
        return []
    today = current_et_market_date(); end = today + timedelta(days=5)
    out=[]
    for row in payload.get("rows") or []:
        d = _fda_event_date(row)
        if not d or d < today or d > end:
            continue
        drug = row.get("drug") or {}
        drug_name = drug.get("name") if isinstance(drug, dict) else None
        event_type = row.get("event_type") or row.get("status") or row.get("outcome") or "FDA event"
        for ticker in _fda_tickers(row) or [""]:
            out.append({"ticker": ticker, "event_type": event_type, "event_date": d.isoformat(), "drug_name": drug_name})
    return out


def _fda_warning_lines(events):
    armed = _armed_watchlist_symbols()
    if not events:
        return ["*⚕️ FDA EVENTS — none in next 5 days*"]
    lines=["*⚕️ FDA EVENTS (next 5 days)*"]
    for ev in events[:12]:
        ticker=(ev.get("ticker") or "?").upper(); prefix="🚨" if ticker in armed else "-"
        drug=f" ({ev.get('drug_name')})" if ev.get("drug_name") else ""
        lines.append(f"{prefix} {ticker} {ev.get('event_date')} — {ev.get('event_type')}{drug}")
    return lines


def get_wavef_insider_buys(limit=6):
    names=[]
    try:
        market_day=current_et_market_date(); today=market_day.strftime('%Y-%m-%d'); yesterday=previous_et_trading_date_str(market_day)
        data=atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday) or {}
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
    names=_dedupe_tickers(names, limit=max(limit, 4)); lines=[]
    try:
        from atlas_engine import check_insider_buying
        for t in names:
            hit, detail = check_insider_buying(t)
            if hit: lines.append(f"  • {t} — {(detail or {}).get('note') if isinstance(detail, dict) else detail}")
            if len(lines) >= limit: break
    except Exception as e: print(f"[pre-market] insider scan skipped: {e}")
    return lines



def _to_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return default


def _fmt_price(value):
    val = _to_float(value)
    return "N/A" if val is None else f"${val:,.2f}"


def _fmt_pct(value, decimals=1, signed=True):
    val = _to_float(value)
    if val is None:
        return "N/A"
    sign = "+" if signed and val >= 0 else ""
    return f"{sign}{val:.{decimals}f}%"


def _section(title):
    return f"━━━ {title} ━━━"


def _eodhd_vix_quote():
    """Secondary VIX source for Massive/Polygon entitlement failures (403/plan gaps)."""
    try:
        rows = eodhd_get("/eod/VIX.INDX", {"limit": 2}) or []
        if isinstance(rows, list) and len(rows) >= 2:
            rows = sorted(rows, key=lambda x: str(x.get("date") or ""))
            prev_close = _to_float(rows[-2].get("close"))
            price = _to_float(rows[-1].get("close"))
            pct = ((price / prev_close) - 1.0) * 100.0 if price and prev_close else None
            return {"ticker": "VIX.INDX", "price": price, "prev_close": prev_close, "pct": pct, "volume": None, "prev_volume": None}
    except Exception:
        return None
    return None


def _yahoo_vix_quote():
    """Fallback quote for VIX only when Polygon/Massive I:VIX is unavailable."""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
            params={"range": "5d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        payload = r.json() or {}
        result = ((payload.get("chart") or {}).get("result") or [])
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = _to_float(meta.get("regularMarketPrice"))
        prev_close = _to_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        if not prev_close:
            closes = (((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
            valid = [_to_float(x) for x in closes if _to_float(x) is not None]
            if len(valid) >= 2:
                prev_close = valid[-2]
        pct = ((price / prev_close) - 1.0) * 100.0 if price and prev_close else None
        return {"ticker": "^VIX", "price": price, "prev_close": prev_close, "pct": pct, "volume": None, "prev_volume": None}
    except Exception:
        return None


def _snapshot_quote(sym):
    sym = (sym or "").upper()
    if sym in {"VIX", "I:VIX"}:
        # Polygon/Massive VIX is an index ticker. If entitlement blocks it (403),
        # fall through to secondary sources instead of rendering N/A.
        rows = []
        data = _guard_massive_get_json(
            f"{MASSIVE_BASE}/v2/aggs/ticker/I:VIX/prev",
            params={"apiKey": MASSIVE_API_KEY, "adjusted": "true"},
            timeout=PRE_MARKET_MASSIVE_TIMEOUT,
            request_tag="pre_market_massive:vix_prev",
        ) or {}
        rows = data.get("results") or []
        row = rows[0] if rows else {}
        price = _to_float(row.get("c"))
        open_price = _to_float(row.get("o"))
        pct = ((price / open_price) - 1.0) * 100.0 if price and open_price else None
        if price:
            return {"ticker": "I:VIX", "price": price, "prev_close": open_price, "pct": pct, "volume": _to_float(row.get("v")), "prev_volume": None}
        return _eodhd_vix_quote() or _yahoo_vix_quote() or {"ticker": "^VIX", "price": None, "prev_close": None, "pct": None, "volume": None, "prev_volume": None}

    data = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{sym}") or {}
    t = normalize_snapshot_fields(sym, data.get("ticker") or {})
    day = t.get("day") or {}
    prev = t.get("prevDay") or {}
    last_trade = t.get("lastTrade") or {}
    price = _to_float(day.get("c")) or _to_float(last_trade.get("p")) or _to_float(prev.get("c"))
    prev_close = _to_float(prev.get("c"))
    pct = _to_float(t.get("todaysChangePerc"))
    if pct is None and price and prev_close:
        pct = ((price / prev_close) - 1.0) * 100.0
    volume = _to_float(day.get("v")) or _to_float(t.get("volume"))
    prev_volume = _to_float(prev.get("v"))
    return {"ticker": sym, "price": price, "prev_close": prev_close, "pct": pct, "volume": volume, "prev_volume": prev_volume}


def _sentiment_value(ticker):
    data = eodhd_get("/sentiments", {"s": f"{ticker}.US"})
    try:
        rows = data.get(f"{ticker}.US") if isinstance(data, dict) else None
        row = rows[0] if rows else None
        return float(row.get("normalized")) if row else None
    except Exception:
        return None


def _latest_signal_score(ticker):
    conn = atlas_db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT score FROM signals WHERE ticker=? ORDER BY timestamp DESC, id DESC LIMIT 1", ((ticker or "").upper(),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _macro_relevant_note(ticker, macro_lines):
    text = " ".join(str(x).lower() for x in (macro_lines or []))
    ticker = (ticker or "").upper()
    semis = {"LRCX", "NVDA", "AMD", "MU", "TSM", "AVGO", "SMCI", "ASML", "AMAT"}
    banks = {"JPM", "BAC", "WFC", "C", "GS", "MS", "XLF"}
    if ticker in semis and any(k in text for k in ("semi", "chip", "semiconductor")):
        return "semis macro sensitivity"
    if ticker in banks and any(k in text for k in ("fed", "stress", "bank", "fomc", "rate")):
        return "banks/Fed macro sensitivity"
    if any(k in text for k in ("fed", "fomc", "cpi", "consumer price index")):
        return "watch macro event risk"
    return None


def _open_position_lines(macro_lines):
    rows = atlas_db.get_open_positions()
    positions = []
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        shares = _to_float(row.get("quantity"), 0) or 0
        entry = _to_float(row.get("price"))
        now = _snapshot_quote(ticker).get("price") or entry
        positions.append({
            "ticker": ticker,
            "entry_price": entry,
            "current_price": now,
            "stop_loss": row.get("stop_loss"),
            "target_price": row.get("target_price"),
            "quantity": shares,
        })
    return holding_block(positions, {})

def _overnight_headlines(limit=5):
    return [re.sub(r"^\s*•\s*", "", str(x)).strip() for x in get_benzinga_headlines()[:limit] if str(x).strip()]


def _benzinga_catalyst_for_ticker(ticker, hours=24):
    ticker = (ticker or "").upper()
    if not ticker or ticker in BENZINGA_UNCOVERED or ticker in PROVIDER_BENZINGA_UNCOVERED or ticker in BENZINGA_SKIP_SET or not BENZINGA_API_KEY:
        return None
    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)
    endpoint = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": BENZINGA_API_KEY,
        "tickers": ticker,
        "dateFrom": since_utc.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
        "dateTo": now_utc.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
        "pageSize": 5,
    }
    data = _guard_benzinga_get_json(
        ticker,
        endpoint,
        params=params,
        request_tag=f"pre_market_benzinga_catalyst:{ticker}",
    ) or []
    articles = data if isinstance(data, list) else (data.get("data") or data.get("articles") or [])
    for item in articles:
        title = (item.get("title") or item.get("headline") or "").strip()
        if title:
            return title
    if articles:
        return None

    fallback_params = dict(params)
    fallback_params.pop("tickers", None)
    fallback_params["pageSize"] = 15
    fallback_data = _guard_benzinga_get_json(
        ticker,
        endpoint,
        params=fallback_params,
        request_tag=f"pre_market_benzinga_catalyst_fallback:{ticker}",
    ) or []
    fallback_articles = fallback_data if isinstance(fallback_data, list) else (fallback_data.get("data") or fallback_data.get("articles") or [])
    for item in fallback_articles:
        stocks = item.get("stocks") or []
        stock_names = {str(s.get("name") or "").upper() for s in stocks if isinstance(s, dict)}
        if ticker not in stock_names:
            continue
        title = (item.get("title") or item.get("headline") or "").strip()
        if title:
            return title
    return None


def _early_movers_candidates(limit=12):
    """Visibility-only early momentum screen from bulk Massive gainers only.

    P0b: this must never call market_scout.discover_tickers() or per-ticker
    snapshot fanout from the pre-market critical path.
    """
    data = massive_get("/v2/snapshot/locale/us/markets/stocks/gainers") or {}
    gainers = data.get("tickers") or []
    rows = []
    for item in gainers:
        ticker = str(item.get("ticker") or "").upper()
        if not _is_tradeable_symbol(ticker):
            continue
        pct = _to_float(item.get("todaysChangePerc"))
        day = item.get("day") or {}
        prev = item.get("prevDay") or {}
        last_trade = item.get("lastTrade") or {}
        price = _to_float(day.get("c")) or _to_float(last_trade.get("p")) or _to_float(prev.get("c"))
        vol = _to_float(day.get("v"))
        prev_vol = _to_float(prev.get("v"))
        rvol = (vol / prev_vol) if vol and prev_vol else None
        if pct is None or price is None or rvol is None:
            continue
        if pct >= 10.0 and rvol > 1.5:
            rows.append({"ticker": ticker, "pct": pct, "price": price, "rvol": rvol, "catalyst": "No catalyst found"})
    rows.sort(key=lambda x: x.get("pct") or 0, reverse=True)
    return rows[:min(limit, PRE_MARKET_EARLY_MOVER_ENRICH_LIMIT)]


def _has_display_catalyst(row):
    catalyst = str((row or {}).get("catalyst") or "").strip()
    return bool(catalyst) and catalyst.lower() != "no catalyst found"


def _append_spaced(lines, items):
    for item in items:
        if item is None:
            continue
        text = str(item).rstrip()
        if not text:
            continue
        lines.append(text)
        lines.append("")


def _early_movers_lines(rows):
    if not rows:
        return []
    display_rows = [row for row in rows if _has_display_catalyst(row)]
    if not display_rows:
        return ["No catalyst-confirmed movers pre-market"]
    lines = []
    for i, row in enumerate(display_rows, 1):
        catalyst = str(row.get("catalyst") or "").strip()
        lines.append(
            f"{i}. {ticker_label(row['ticker'], row)} {_fmt_pct(row.get('pct'), decimals=0)} · {_fmt_price(row.get('price'))} · RVOL {row.get('rvol'):.1f}x · Catalyst: {catalyst}"
        )
        lines.append("")
    return lines


def _gapper_candidates(limit=6):
    data = massive_get("/v2/snapshot/locale/us/markets/stocks/gainers") or {}
    start_et, end_et = premarket_news_window()
    try:
        from market_scout import has_recent_reverse_split
    except Exception:
        has_recent_reverse_split = lambda _ticker: False

    base_rows = []
    for row in data.get("tickers") or []:
        ticker = (row.get("ticker") or "").upper()
        if not _is_tradeable_symbol(ticker):
            continue
        day = row.get("day") or {}
        prev = row.get("prevDay") or {}
        price = normalize_price(ticker, _to_float(day.get("c")) or _to_float((row.get("lastTrade") or {}).get("p")))
        if not price or price < 5:
            continue
        prev_close = normalize_price(ticker, _to_float(prev.get("c")))
        gap = _to_float(row.get("todaysChangePerc"))
        if gap is None and price and prev_close:
            gap = ((price / prev_close) - 1.0) * 100.0
        if gap is None or gap <= 4:
            continue
        vol = _to_float(day.get("v"))
        prev_vol = _to_float(prev.get("v"))
        rvol = (vol / prev_vol) if vol and prev_vol else None
        if rvol is None or rvol <= 1.5:
            continue
        base_rows.append({"ticker": ticker, "price": price, "gap": gap, "rvol": rvol, "trigger": price})
        if len(base_rows) >= max(limit * 2, limit):
            break

    def _enrich(c):
        ticker = c["ticker"]
        try:
            if has_recent_reverse_split(ticker):
                return None
        except Exception:
            return None
        sent = _sentiment_value(ticker)
        articles = _ticker_news_in_window(ticker, start_et, end_et, limit=1)
        catalyst = (articles[0].get("title") if articles else None) or "fresh catalyst pending"
        c.update({"sentiment": sent, "catalyst": catalyst, "score": _latest_signal_score(ticker)})
        return c

    out = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(base_rows)))) as pool:
        future_map = {pool.submit(_enrich, dict(c)): c for c in base_rows}
        for fut in as_completed(future_map):
            item = fut.result()
            if item:
                out.append(item)
    order = {c["ticker"]: i for i, c in enumerate(base_rows)}
    out.sort(key=lambda c: order.get(c["ticker"], 999))
    return out[:limit]


def _gap_breakout_lines(candidates):
    lines = []
    for c in candidates:
        if (c.get("gap") or 0) > 4 and (c.get("rvol") or 0) > 1.5 and (c.get("sentiment") or 0) > 0.5:
            score = str(c.get("score") or "")
            if score.startswith("2/"):
                continue
            lines.append(
                f"🔹 {ticker_label(c['ticker'], c)} Gap {_fmt_pct(c.get('gap'))} · RVOL {c.get('rvol'):.1f}x · Sentiment {c.get('sentiment'):.1f} · Trigger {_fmt_price(c.get('trigger'))}"
            )
            lines.append(f"   Catalyst: {_clean_catalyst_reason(c.get('catalyst'))}")
    return lines


def _catalyst_override_lines(candidates):
    lines = []
    for c in candidates:
        score = str(c.get("score") or "")
        if not score.startswith("2/"):
            continue
        if (c.get("gap") or 0) > 4 and (c.get("rvol") or 0) > 3 and (c.get("sentiment") or 0) > 0.5:
            lines.append(
                f"🔸 {ticker_label(c['ticker'], c)} Gap {_fmt_pct(c.get('gap'))} · RVOL {c.get('rvol'):.1f}x · Sentiment {c.get('sentiment'):.1f} · Trigger {_fmt_price(c.get('trigger'))} · 5% stop"
            )
            lines.append(f"   Catalyst: {_clean_catalyst_reason(c.get('catalyst'))}")
    return lines


def _pending_stop_target(row):
    trigger = _to_float(row.get("trigger_price"))
    if trigger is None:
        return None, None
    sig = row.get("signal_result") or {}
    rc = sig.get("risk_card") or {}
    entry_ref = _to_float(sig.get("entry_price"), _to_float(row.get("reference_price"), trigger))
    stop_ref = _to_float(rc.get("stop_loss"))
    stop = None
    if entry_ref is not None and stop_ref is not None:
        risk_ref = entry_ref - stop_ref
        if risk_ref > 0:
            stop = round(trigger - risk_ref, 2)
    if stop is None:
        return None, None
    target = round(trigger + (2 * (trigger - stop)), 2)
    return stop, target


def _pullback_detail_flags(sig):
    flags = []
    fundamentals = sig.get("fundamentals") if isinstance(sig, dict) else None
    if isinstance(fundamentals, dict):
        flags.append(fundamentals.get("tag") or "fundamentals")
    elif fundamentals:
        flags.append("fundamentals")
    if isinstance(sig, dict) and sig.get("warnings"):
        flags.append("warnings")
    return " · ".join([str(x) for x in flags if x]) or "—"


def _pullback_and_hot_lines():
    pullback_rows, hot = [], []
    for row in atlas_db.get_pending_pullbacks(status="WAITING"):
        ticker = str(row.get("ticker") or "?").upper()
        trigger = _to_float(row.get("trigger_price"))
        now = _snapshot_quote(ticker).get("price") or _to_float(row.get("reference_price"))
        pct = (((now / trigger) - 1.0) * 100.0) if now and trigger else None
        if pct is not None and pct > 10:
            hot.append(f"{ticker_label(ticker, row)} +{pct:.0f}%")
            continue
        item = dict(row)
        import json as _json
        try:
            sj = _json.loads(row.get("signal_json") or "{}")
            item["rvol"] = sj.get("rvol")
            item["rsi"] = sj.get("indicator_info", {}).get("rsi")
            item["macd_hist"] = sj.get("indicator_info", {}).get("macd_histogram")
        except Exception:
            pass  # leave as None — formatter handles gracefully
        item.update({
            "action": "WAIT",
            "reason": "PULLBACK — pre-market candidate",
            "entry": trigger,
            "entry_price": trigger,
            "current_price": now,
            "price": now,
        })
        pullback_rows.append(item)
    rendered = pullback_block(pullback_rows)
    # Keep this function's historical contract: return card lines for caller's PULLBACK CANDIDATES section.
    cards = [line for line in rendered if line not in ("", f"━━━ 🎣 WAITING FOR DIP ({len(pullback_rows)}) ━━━", "✅ none")]
    return cards, hot

def _sector_pulse_lines():
    labels = {"XLF":"financials", "XLK":"technology", "XLE":"energy", "XLV":"healthcare", "XLI":"industrials"}
    rows = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_map = {pool.submit(_snapshot_quote, sym): sym for sym in labels}
        for fut in as_completed(future_map):
            sym = future_map[fut]
            q = fut.result()
            if q.get("pct") is not None:
                rows.append((sym, q["pct"], labels.get(sym, "sector")))
    rows.sort(key=lambda x: abs(x[1]), reverse=True)
    lines = []
    for sym, pct, label in rows[:4]:
        reason = f"{label} leading" if pct >= 0 else f"{label} under pressure"
        lines.append(f"{sym} {_fmt_pct(pct)} — {reason}")
    return lines


def _first_compact(items, fallback="none"):
    if not items:
        return fallback
    cleaned = [re.sub(r"^\s*[•\-]\s*", "", str(x)).strip() for x in items if str(x).strip()]
    return " | ".join(cleaned[:3]) if cleaned else fallback


def _current_premarket_day(now_et=None):
    now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
    day = now_et.date()
    if day in NYSE_HOLIDAYS_2026 or day.weekday() >= 5:
        return None
    return day


def generate_wavef_pre_market_brief(send=False, market_day=None):
    _t0 = _audit_time.perf_counter()
    try:
        rag_hits = atlas_rag.query_knowledge_base("Atlas pre-market report context open positions risk gaps catalysts", n_results=3) if atlas_rag else []
        print(f"[pre-market] rag query hits={len(rag_hits)}")
    except Exception as e:
        print(f"[pre-market] rag query failed: {type(e).__name__}: {e}")

    def _timed(label, fn):
        st = _audit_time.perf_counter()
        try:
            return fn()
        finally:
            print(f"[pre-market timing] {label}: {_audit_time.perf_counter() - st:.2f}s")

    market_day = market_day or _current_premarket_day()
    if market_day is None:
        print("[pre-market] no report generated; non-trading ET calendar day")
        return None
    date_label = market_day.strftime("%B %-d, %Y")
    tasks = {
        "spy_snapshot": lambda: _snapshot_quote("SPY"),
        "qqq_snapshot": lambda: _snapshot_quote("QQQ"),
        "vix_snapshot": lambda: _snapshot_quote("VIX"),
        "macro": get_wavef_macro,
        "overnight_headlines": _overnight_headlines,
        "top_movers": get_top_movers,
        "gapper_candidates": _gapper_candidates,
        "earnings": get_wavef_earnings,
        "analyst_actions": lambda: get_wavef_analyst_actions(limit=4),
        "insider_buys": lambda: get_wavef_insider_buys(limit=2),
        "fda": get_wavef_fda_warnings,
        "pullbacks": _pullback_and_hot_lines,
        "sector_pulse": _sector_pulse_lines,
    }
    results = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_map = {pool.submit(_timed, label, fn): label for label, fn in tasks.items()}
        for fut in as_completed(future_map):
            label = future_map[fut]
            try:
                results[label] = fut.result()
            except Exception as exc:
                print(f"[pre-market] task {label} failed: {type(exc).__name__}: {exc}")
                results[label] = None

    spy = results.get("spy_snapshot") or {}
    qqq = results.get("qqq_snapshot") or {}
    vix = results.get("vix_snapshot") or {}
    macro = results.get("macro") or []
    headlines = results.get("overnight_headlines") or []
    gainers, losers = results.get("top_movers") or ([], [])
    early_movers = []
    print("[pre-market timing] early_movers_skipped=timeout_budget")
    gappers = results.get("gapper_candidates") or []
    earnings = results.get("earnings") or []
    analysts = results.get("analyst_actions") or []
    insiders = results.get("insider_buys") or []
    fda_events = results.get("fda") or []
    pullbacks, too_hot = results.get("pullbacks") or ([], [])
    sectors = results.get("sector_pulse") or []
    open_positions = _timed("open_positions", lambda: _open_position_lines(macro))
    gap_breakouts = _timed("gap_breakouts", lambda: _gap_breakout_lines(gappers))
    catalyst_overrides = _timed("catalyst_overrides", lambda: _catalyst_override_lines(gappers))

    avg_idx = sum(x for x in [spy.get("pct"), qqq.get("pct")] if x is not None)
    idx_count = len([x for x in [spy.get("pct"), qqq.get("pct")] if x is not None])
    avg_idx = avg_idx / idx_count if idx_count else 0
    if avg_idx > 0.3:
        sentiment = "risk-on tone"
    elif avg_idx < -0.3:
        sentiment = "risk-off tone"
    else:
        sentiment = "mixed/neutral tone"
    if macro:
        sentiment += "; macro events on deck"

    lines = [
        f"🦅 ATLAS PRE-MARKET BRIEF — {date_label} · SPY {_fmt_price(spy.get('price'))} ({_fmt_pct(spy.get('pct'))}) | QQQ {_fmt_price(qqq.get('price'))} ({_fmt_pct(qqq.get('pct'))}) | VIX {_fmt_price(vix.get('price'))} ({_fmt_pct(vix.get('pct'))}) · {sentiment}",
        "",
        _section("MACRO BRIEFING"),
    ]
    lines.append("Overnight Headlines")
    if headlines:
        for item in headlines[:5]:
            lines.append(f"📰 {item}")
    else:
        lines.append("No overnight Benzinga headlines returned")
    lines.append("Scheduled Events (4 AM–4 PM ET)")
    _append_spaced(lines, macro[:8] if macro else ["No scheduled macro events returned"])

    if open_positions:
        lines += ["", _section("OPEN POSITIONS")]
        _append_spaced(lines, open_positions)

    early_mover_lines = _early_movers_lines(early_movers)
    if early_mover_lines:
        early_mover_count = sum(1 for x in early_mover_lines if str(x).strip())
        lines += ["", _section(f"🔥 EARLY MOVERS ({early_mover_count})"), "Visibility only — on your radar, not a buy recommendation."]
        _append_spaced(lines, early_mover_lines)

    if gap_breakouts:
        lines += ["", _section("GAP-UP BREAKOUTS")]
        _append_spaced(lines, gap_breakouts)

    if pullbacks:
        lines += ["", _section("PULLBACK CANDIDATES")]
        _append_spaced(lines, pullbacks)

    if catalyst_overrides:
        lines += ["", _section("CATALYST OVERRIDES — HALF SIZE")]
        _append_spaced(lines, catalyst_overrides)

    if too_hot:
        lines += ["", _section("TOO HOT SKIP"), " | ".join(too_hot[:12])]

    if sectors:
        lines += ["", _section("SECTOR PULSE")]
        _append_spaced(lines, sectors)

    scouting = []
    if earnings:
        scouting.append("Earnings tonight: " + _first_compact(earnings))
    if analysts:
        scouting.append("Analyst actions: " + _first_compact(analysts))
    if insiders:
        scouting.append("Insider buys: " + _first_compact(insiders))
    if fda_events:
        fda_bits = [f"{(ev.get('ticker') or '?').upper()} {ev.get('event_date')} {ev.get('event_type')}" for ev in fda_events[:3]]
        scouting.append("FDA calendar: " + " | ".join(fda_bits))
    if scouting:
        lines += ["", _section("SCOUTING")]
        _append_spaced(lines, scouting)

    msg = "\n".join(lines)
    # Telegram delivery is centralized in generate_pre_market_report().
    # This renderer must only render, otherwise a single pre-market session can send twice.
    print(f"[pre-market timing] total: {_audit_time.perf_counter() - _t0:.2f}s")
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
                "model": os.environ.get("ATLAS_MACRO_LLM_MODEL", "gpt-4o-mini"),
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

def _write_premarket_run_marker(market_date, sent=True):
    try:
        payload = {
            "market_date": str(market_date),
            "ran_at_et": datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds"),
            "sent": bool(sent),
        }
        tmp = "/tmp/atlas_pre_market_report_last_run.json.tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, sort_keys=True)
        os.replace(tmp, "/tmp/atlas_pre_market_report_last_run.json")
    except Exception:
        pass


def generate_pre_market_report(send=True):
    now_et = datetime.now(ZoneInfo("America/New_York"))
    today = _current_premarket_day(now_et)
    if today is None:
        print("[pre_market] no report generated; non-trading ET calendar day")
        return None
    message = generate_wavef_pre_market_brief(send=False, market_day=today)
    if not message:
        return None
    # `generate_wavef_pre_market_brief()` already computes and renders early movers.
    # Do not run that scan a second time here; it was the dominant timeout source.
    if send:
        _write_premarket_run_marker(today, sent=True)
    if send:
        send_telegram(message)
    return message
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

def _launchd_market_open_window(now_et=None):
    """Optional launchd guard: allow the market-open pre-market send once near 09:15 ET."""
    now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
    if _current_premarket_day(now_et) is None:
        return False
    t = now_et.time().replace(tzinfo=None)
    return time(9, 15) <= t < time(9, 20)


PREMARKET_LOCK_PATH = "/tmp/atlas_premarket.lock"
PREMARKET_LOCK_STALE_SECONDS = 2 * 60 * 60


def _acquire_premarket_lock(path=PREMARKET_LOCK_PATH, stale_seconds=PREMARKET_LOCK_STALE_SECONDS):
    now_ts = datetime.now(timezone.utc).timestamp()
    try:
        existing_age = now_ts - os.path.getmtime(path)
        if existing_age > stale_seconds:
            os.unlink(path)
            print(f"[pre_market] stale lock cleared: {path} age={existing_age:.0f}s")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[pre_market] lock stale-check warning: {type(e).__name__}: {e}")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({
                "pid": os.getpid(),
                "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, sort_keys=True))
        return True
    except FileExistsError:
        try:
            age = now_ts - os.path.getmtime(path)
        except Exception:
            age = -1
        print(f"[pre_market] duplicate run suppressed by lock: {path} age={age:.0f}s")
        return False


def _release_premarket_lock(path=PREMARKET_LOCK_PATH):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[pre_market] lock release warning: {type(e).__name__}: {e}")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Atlas pre-market report")
    parser.add_argument("--dry-run", action="store_true", help="Build and print report without sending Telegram")
    parser.add_argument("--force", action="store_true", help="Bypass launchd market-open gate")
    args = parser.parse_args(argv)

    from zoneinfo import ZoneInfo
    import datetime as _dt
    _et_today = _dt.date.today()
    try:
        _et_today = _dt.datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        pass
    if not args.force and not args.dry_run and not is_trading_day(_et_today):
        print(f"[pre_market] calendar gate closed; non-market ET day {_et_today.isoformat()}; no report sent")
        return 0

    gated = os.environ.get("ATLAS_PREMARKET_LAUNCHD_GATED") == "1"
    if gated and not args.force and not args.dry_run and not _launchd_market_open_window():
        print("[pre_market] launchd gate closed; outside 09:15-09:20 ET trading window")
        return 0

    lock_acquired = _acquire_premarket_lock()
    if not lock_acquired:
        return 0
    try:
        message = generate_pre_market_report(send=not args.dry_run)
        if not message:
            print("[pre_market] no report generated")
            return 1
        if args.dry_run:
            print(message)
            print(f"[pre_market] dry-run generated {len(message)} chars; Telegram not sent")
        return 0
    finally:
        _release_premarket_lock()


if __name__ == "__main__":
    raise SystemExit(main())