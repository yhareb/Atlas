import os
import sys
import requests
import datetime
import json
import time
import pathlib

# Symbols the engine must never trade as stock picks
ETF_BLOCKLIST = {
    # broad index / sector / commodity ETFs
    "SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "IVV",
    "EWY", "EWZ", "EWJ", "FXI", "EEM", "EFA", "GLD", "SLV",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "SOXX", "SMH", "XSD", "FTXL", "DRAM",
    # leveraged / inverse equity and sector ETFs that commonly appear in momentum/volume scans
    "TQQQ", "SQQQ", "SOXL", "SOXS", "UVXY", "VXX",
    "NVD", "NVDL", "NVDS", "NVDU", "NVDD",
    "TSLL", "TSLQ", "TSLS", "TSLT",
    "AMDL", "AMDS", "AAPU", "AAPD", "MSFU", "MSFD", "GGLL", "GGLS", "CONL",
    "SPXL", "SPXS", "UPRO", "SPXU", "QLD", "QID", "TNA", "TZA", "UWM", "TWM",
    "FAS", "FAZ", "LABU", "LABD", "NUGT", "DUST", "GUSH", "DRIP", "BOIL", "KOLD",
    "TECL", "TECS", "USD", "SSG",
    # crypto ETFs/trusts
    "BITO", "IBIT", "BITI", "GBTC", "FBTC", "BITB", "ARKB", "HODL", "BTCO", "EZBC",
    "ETHA", "ETHE", "FETH",
}

# Non-ETF symbols unsuitable for Atlas even if they are technically common stock.
PERMANENT_SCAN_REMOVED_TICKERS = {"CWAN"}
EXCLUDED_TICKERS = PERMANENT_SCAN_REMOVED_TICKERS | {
    "FNMA",  # Fannie Mae: OTC/government conservatorship entity
    "FMCC",  # Freddie Mac: OTC/government conservatorship entity
    "SUUN",  # invalid/non-tradeable ticker surfaced by discovery feeds
    "MUZ",   # Nuveen bond ETF slipping through provider metadata
    "PRA",   # ProAssurance: active reference, but Massive snapshot 404; exclude from active scan universe
    "AMED",  # Amedisys: delisted in Massive/EODHD; exclude from active scan universe
    "TTNI",  # EODHD TTNI.US fundamentals/splits 404; exclude from active scan universe
}

def _is_tradeable_equity(sym):
    if not sym:
        return False
    s = sym.strip().upper()
    if s.startswith("$"):          # crypto like $BTC
        return False
    if "." in s or "-" in s:        # foreign/OTC/preferred classes
        return False
    if not s.isalpha():             # only clean alphabetic tickers
        return False
    if len(s) > 5:                  # US equities are 1-5 letters
        return False
    if s in EXCLUDED_TICKERS:
        return False
    if s in ETF_BLOCKLIST:
        return False
    return True

# Ensure it can find the engine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from atlas_engine import analyze_ticker
try:
    import atlas_fda_calendar
except Exception:
    atlas_fda_calendar = None
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
RS_MIN_SCORE = 1.5
RS_SCAN_UNIVERSE = 100
RS_TOP_N = 20
REVERSE_SPLIT_LOOKBACK_DAYS = 30
SPLIT_CACHE_PATH = "/tmp/atlas_split_cache.json"
SPLIT_CACHE_TTL_SEC = 24 * 60 * 60
_REVERSE_SPLIT_CACHE = {}
_ETF_TYPE_CACHE = {}
_REFERENCE_TICKER_CACHE = {}
_LAST_DISCOVERY_BUCKETS = {}


def last_discovery_buckets():
    return {k:list(v) for k,v in _LAST_DISCOVERY_BUCKETS.items()}


def _discovery_cache_path():
    value=os.environ.get("ATLAS_DISCOVERY_CACHE_PATH")
    return pathlib.Path(value) if value else None


def _load_discovery_cache():
    path=_discovery_cache_path()
    if not path or os.environ.get("ATLAS_PROVIDER_WARMUP") == "1" or not path.is_file():
        return None
    try:
        payload=json.loads(path.read_text())
        generated=datetime.datetime.fromisoformat(str(payload["generated_at"]).replace("Z","+00:00"))
        now=datetime.datetime.now(datetime.timezone.utc)
        unsigned={k:v for k,v in payload.items() if k!="content_sha256"}
        expected=__import__('hashlib').sha256(json.dumps(unsigned,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        if payload.get("schema")!="atlas.provider_discovery_cache.v1" or payload.get("content_sha256")!=expected or now>generated+datetime.timedelta(seconds=int(payload.get("ttl_seconds") or 0)):
            return None
        global _LAST_DISCOVERY_BUCKETS
        _LAST_DISCOVERY_BUCKETS={k:list(v) for k,v in (payload.get("buckets") or {}).items()}
        return list(payload.get("tickers") or [])
    except Exception:
        return None


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


def _parse_split_ratio(split_value):
    txt = str(split_value or "").strip()
    if not txt or "/" not in txt:
        return None
    try:
        left, right = txt.split("/", 1)
        return float(left), float(right)
    except Exception:
        return None


def _reference_ticker(sym):
    """Cached Massive reference metadata. 404 is cached as None and kept silent."""
    s = (sym or "").strip().upper()
    if not s or not MASSIVE_API_KEY:
        return None
    if s in _REFERENCE_TICKER_CACHE:
        return _REFERENCE_TICKER_CACHE[s]
    try:
        r = _REQUESTS_GET(
            f"{MASSIVE_BASE}/v3/reference/tickers/{s}",
            params={"apiKey": MASSIVE_API_KEY},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if r.status_code == 404:
            _REFERENCE_TICKER_CACHE[s] = None
            return None
        if r.status_code == 200:
            result = (r.json() or {}).get("results") or {}
            _REFERENCE_TICKER_CACHE[s] = result if result else None
            return _REFERENCE_TICKER_CACHE[s]
    except Exception as e:
        print(f"[market_scout] reference ticker check failed for {s}: {e}")
    _REFERENCE_TICKER_CACHE[s] = None
    return None


def _is_known_etf(sym):
    s = (sym or "").strip().upper()
    if not s:
        return False
    if s in ETF_BLOCKLIST:
        _ETF_TYPE_CACHE[s] = True
        return True
    if s in _ETF_TYPE_CACHE:
        return _ETF_TYPE_CACHE[s]

    is_etf = False
    massive_has_type = False
    result = _reference_ticker(s)
    if result:
        ticker_type = str(result.get("type") or "").strip().upper()
        if ticker_type:
            massive_has_type = True
            is_etf = ticker_type == "ETF"

    if not massive_has_type and EODHD_API_KEY:
        try:
            r = _audit_get(
                f"https://eodhd.com/api/fundamentals/{s}.US",
                params={"api_token": EODHD_API_KEY, "fmt": "json"},
                headers={"Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 200:
                payload = r.json() or {}
                general = payload.get("General") if isinstance(payload, dict) else {}
                eodhd_type = str((general or {}).get("Type") or "").strip().upper()
                is_etf = eodhd_type == "ETF" or bool(payload.get("ETF_Data"))
        except Exception as e:
            print(f"[market_scout] EODHD ETF fallback failed for {s}: {e}")

    _ETF_TYPE_CACHE[s] = bool(is_etf)
    return _ETF_TYPE_CACHE[s]


def _load_split_disk_cache():
    try:
        with open(SPLIT_CACHE_PATH, "r") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_split_disk_cache(payload):
    try:
        tmp = f"{SPLIT_CACHE_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, sort_keys=True)
        os.replace(tmp, SPLIT_CACHE_PATH)
    except Exception:
        pass


def _split_disk_cache_get(cache_key):
    payload = _load_split_disk_cache()
    row = payload.get(cache_key)
    if not isinstance(row, dict):
        return None
    try:
        if (time.time() - float(row.get("ts", 0))) > SPLIT_CACHE_TTL_SEC:
            return None
        return bool(row.get("value"))
    except Exception:
        return None


def _split_disk_cache_set(cache_key, value):
    payload = _load_split_disk_cache()
    now = time.time()
    # Opportunistic pruning keeps /tmp cache small.
    pruned = {}
    for key, row in payload.items():
        try:
            if (now - float((row or {}).get("ts", 0))) <= SPLIT_CACHE_TTL_SEC:
                pruned[key] = row
        except Exception:
            pass
    pruned[cache_key] = {"ts": now, "value": bool(value)}
    _save_split_disk_cache(pruned)


def has_recent_reverse_split(sym, days=REVERSE_SPLIT_LOOKBACK_DAYS):
    """True if EODHD split data shows a reverse split in the recent lookback."""
    s = (sym or "").strip().upper()
    if not s or not EODHD_API_KEY:
        return False
    today = datetime.date.today()
    cache_key = f"{s}:{today.isoformat()}:{int(days)}"
    if cache_key in _REVERSE_SPLIT_CACHE:
        return _REVERSE_SPLIT_CACHE[cache_key]
    disk_value = _split_disk_cache_get(cache_key)
    if disk_value is not None:
        _REVERSE_SPLIT_CACHE[cache_key] = disk_value
        return disk_value
    start = (today - datetime.timedelta(days=int(days))).isoformat()
    try:
        r = _audit_get(
            f"https://eodhd.com/api/splits/{s}.US",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "from": start, "to": today.isoformat()},
            headers={"Accept": "application/json"}, timeout=8,
        )
        if r.status_code != 200:
            _REVERSE_SPLIT_CACHE[cache_key] = False
            _split_disk_cache_set(cache_key, False)
            return False
        rows = r.json()
        if not isinstance(rows, list):
            _REVERSE_SPLIT_CACHE[cache_key] = False
            _split_disk_cache_set(cache_key, False)
            return False
        for row in rows:
            ratio = _parse_split_ratio((row or {}).get("split"))
            if not ratio:
                continue
            new_shares, old_shares = ratio
            # EODHD reverse split example: 1.000000/6.000000 = 1 new share for 6 old shares.
            if new_shares > 0 and old_shares > 0 and new_shares < old_shares:
                _REVERSE_SPLIT_CACHE[cache_key] = True
                _split_disk_cache_set(cache_key, True)
                return True
    except Exception as e:
        print(f"[market_scout] reverse split check failed for {s}: {e}")
    _REVERSE_SPLIT_CACHE[cache_key] = False
    _split_disk_cache_set(cache_key, False)
    return False


def _add_candidate(sym, tickers, mover_order=None):
    s = (sym or "").strip().upper()
    if not _is_tradeable_equity(s):
        return False
    if _is_known_etf(s):
        return False
    if has_recent_reverse_split(s):
        print(f"[market_scout] excluded {s}: reverse split within {REVERSE_SPLIT_LOOKBACK_DAYS}d")
        return False
    tickers.add(s)
    if mover_order is not None and s not in mover_order:
        mover_order.append(s)
    return True


def discover_rs_leaders(top_n=RS_TOP_N):
    """Discover multi-day relative-strength leaders vs SPY using EODHD screener data."""
    if not EODHD_API_KEY:
        return []
    import json as _json

    spy_filters = [["code", "=", "SPY"]]
    spy_resp = _audit_get(
        "https://eodhd.com/api/screener",
        params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": _json.dumps(spy_filters), "limit": 1},
        headers={"Accept": "application/json"}, timeout=10,
    )
    if spy_resp.status_code != 200:
        return []
    spy_rows = spy_resp.json().get("data") or []
    if not spy_rows:
        return []
    try:
        spy_5d_return = float(spy_rows[0].get("refund_5d_p"))
    except Exception:
        return []
    spy_down_or_flat = spy_5d_return <= 0

    filters = [["avgvol_200d", ">", 500000], ["exchange", "=", "US"], ["market_capitalization", ">", 300000000], ["refund_5d_p", ">", 0]]
    rs_resp = _audit_get(
        "https://eodhd.com/api/screener",
        params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": _json.dumps(filters), "limit": RS_SCAN_UNIVERSE, "sort": "refund_5d_p.desc"},
        headers={"Accept": "application/json"}, timeout=10,
    )
    if rs_resp.status_code != 200:
        return []

    leaders = []
    for row in (rs_resp.json().get("data") or [])[:RS_SCAN_UNIVERSE]:
        sym = (row.get("code") or "").upper()
        price = row.get("adjusted_close") or 0
        try:
            stock_5d_return = float(row.get("refund_5d_p"))
            adjusted_close = float(price)
        except Exception:
            continue
        if adjusted_close < 5:
            continue
        if not _is_tradeable_equity(sym):
            continue
        if spy_down_or_flat:
            if stock_5d_return > 0:
                leaders.append((sym, stock_5d_return - spy_5d_return))
        else:
            rs_score = stock_5d_return / spy_5d_return
            if rs_score >= RS_MIN_SCORE:
                leaders.append((sym, rs_score))

    leaders.sort(key=lambda item: item[1], reverse=True)
    return [sym for sym, _score in leaders[:top_n]]


def _next_trading_day(day):
    d = day + datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d


def _previous_trading_day(day):
    d = day - datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def _trading_day_offset(day, offset):
    d = day
    step = 1 if offset >= 0 else -1
    for _ in range(abs(int(offset))):
        d = _next_trading_day(d) if step > 0 else _previous_trading_day(d)
    return d


def _is_us_exchange_symbol(sym):
    s = (sym or "").strip().upper()
    if not s or not MASSIVE_API_KEY:
        return False
    try:
        result = _reference_ticker(s) or {}
        if not result:
            return False
        ticker_type = str(result.get("type") or "").strip().upper()
        market = str(result.get("market") or "").strip().lower()
        locale = str(result.get("locale") or "").strip().lower()
        exchange = str(result.get("primary_exchange") or "").strip().lower()
        return bool(
            result.get("active", True)
            and locale == "us"
            and market == "stocks"
            and ticker_type != "ETF"
            and exchange not in {"otc link", "pinx", "ootc", "otc"}
        )
    except Exception as e:
        print(f"[market_scout] US exchange check failed for {s}: {e}")
        return False


def discover_large_cap_quality(limit=40):
    """Large-cap liquid US names with no 1-day momentum requirement."""
    if not EODHD_API_KEY:
        return []
    import json as _json
    filters = [
        ["exchange", "=", "US"],
        ["market_capitalization", ">", 50000000000],
        ["avgvol_200d", ">", 5000000],
        ["adjusted_close", ">", 5],
    ]
    try:
        r = _audit_get(
            "https://eodhd.com/api/screener",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": _json.dumps(filters), "limit": limit, "sort": "market_capitalization.desc"},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        out = []
        for row in (r.json().get("data") or [])[:limit]:
            sym = (row.get("code") or "").upper()
            price = row.get("adjusted_close") or 0
            try:
                if sym and float(price) > 5:
                    out.append(sym)
            except Exception:
                continue
        return out
    except Exception as e:
        print(f"[market_scout] large-cap quality screener failed: {e}")
        return []


def discover_earnings_calendar(limit=20):
    """Tickers with earnings from previous trading day through next 3 trading days."""
    if not MASSIVE_API_KEY:
        return []
    today = datetime.date.today()
    start = _trading_day_offset(today, -1)
    end = _trading_day_offset(today, 3)
    try:
        r = _audit_get(
            f"{MASSIVE_BASE}/benzinga/v1/earnings",
            params={"apiKey": MASSIVE_API_KEY, "date.gte": start.isoformat(), "date.lte": end.isoformat(), "limit": 200},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        out = []
        for row in (r.json().get("results") or []):
            sym = (row.get("ticker") or "").upper()
            if not sym or sym in out:
                continue
            if not _is_tradeable_equity(sym):
                continue
            if _is_known_etf(sym):
                continue
            if not _is_us_exchange_symbol(sym):
                continue
            out.append(sym)
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"[market_scout] earnings calendar discovery failed: {e}")
        return []


def discover_tickers():
    cached=_load_discovery_cache()
    if cached is not None:
        return cached
    # Use Benzinga to find stocks with breaking news today
    benzinga_key = os.environ.get("BENZINGA_API_KEY")
    catalyst_order = []
    earnings_order = []
    large_cap_quality_order = []
    mover_order = []
    volume_order = []
    rs_order = []
    momentum_order = []
    fda_order = []

    def _add_to_bucket(bucket, sym):
        tmp = set()
        if not _add_candidate(sym, tmp):
            return False
        s = (sym or "").strip().upper()
        if s not in bucket:
            bucket.append(s)
        return True
    
    if benzinga_key:
        url = "https://api.benzinga.com/api/v2/news"
        params = {
            "token": benzinga_key,
            "dateFrom": datetime.date.today().strftime('%Y-%m-%d'),
            "pageSize": 50,
            "sort": "created",
            "sortDir": "desc",
        }
        try:
            response = _audit_get(url, params=params, headers={"Accept": "application/json"})
            if response.status_code == 200:
                for item in response.json():
                    for stock in item.get("stocks", []):
                        if stock.get("name"):
                            _add_to_bucket(catalyst_order, stock["name"])
        except Exception as e:
            print(f"[market_scout] Benzinga discovery failed: {e}")

    # Earnings calendar: previous trading day through next 3 trading days.
    try:
        for sym in discover_earnings_calendar(limit=20):
            _add_to_bucket(earnings_order, sym)
    except Exception as e:
        print(f"[market_scout] earnings calendar discovery failed: {e}")

    # FDA calendar discovery: metadata/discovery only, capped and deduped. No scoring change.
    try:
        if atlas_fda_calendar is not None:
            for sym in atlas_fda_calendar.discover_fda_tickers(days=60, limit=10):
                _add_to_bucket(fda_order, sym)
    except Exception as e:
        print(f"[market_scout] FDA calendar discovery skipped: {type(e).__name__}: {e}")

    # Large-cap quality: liquid US mega/large caps without a same-day momentum requirement.
    try:
        for sym in discover_large_cap_quality(limit=40):
            _add_to_bucket(large_cap_quality_order, sym)
    except Exception as e:
        print(f"[market_scout] large-cap quality discovery failed: {e}")
            
    # --- Top movers feed: gainers + most-active (price >= $5), so breakout/volume leaders are always surfaced ---
    if MASSIVE_API_KEY:
        try:
            mr = _audit_get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/gainers",
                params={"apiKey": MASSIVE_API_KEY},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if mr.status_code == 200:
                for t in (mr.json().get("tickers") or [])[:15]:
                    sym = (t.get("ticker") or "").upper()
                    price = (t.get("day") or {}).get("c") or 0
                    if sym and price >= 5:
                        _add_to_bucket(mover_order, sym)
        except Exception as e:
            print(f"[market_scout] gainers feed failed: {e}")

        # Massive has no working /most_active snapshot path on this plan; use the
        # all-tickers snapshot and rank locally by current-day volume.
        try:
            mr = _audit_get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"apiKey": MASSIVE_API_KEY},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if mr.status_code == 200:
                volume_rows = []
                for t in (mr.json().get("tickers") or []):
                    sym = (t.get("ticker") or "").upper()
                    day = t.get("day") or {}
                    prev = t.get("prevDay") or {}
                    last = t.get("lastTrade") or {}
                    price = day.get("c") or last.get("p") or prev.get("c") or 0
                    volume = day.get("v") or day.get("volume") or prev.get("v") or prev.get("volume") or 0
                    if sym and price and float(price) >= 5 and volume:
                        volume_rows.append((float(volume), t))
                for _volume, t in sorted(volume_rows, key=lambda item: item[0], reverse=True)[:50]:
                    sym = (t.get("ticker") or "").upper()
                    _add_to_bucket(volume_order, sym)
        except Exception as e:
            print(f"[market_scout] most-active snapshot failed: {e}")

    # RS leaders: multi-day outperformers vs SPY
    try:
        rs_leaders = discover_rs_leaders(top_n=RS_TOP_N)
        for sym in rs_leaders:
            if _is_tradeable_equity(sym):
                _add_to_bucket(rs_order, sym)
    except Exception:
        pass

    # EODHD screener: fresh liquid/moving US names, fed into the SAME normal engine scan.
    if EODHD_API_KEY:
        try:
            import json as _json
            filters = [["refund_1d_p", ">", 3], ["avgvol_200d", ">", 1000000], ["exchange", "=", "US"], ["market_capitalization", ">", 300000000]]
            sr = _audit_get(
                "https://eodhd.com/api/screener",
                params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": _json.dumps(filters), "limit": 50, "sort": "refund_1d_p.desc"},
                headers={"Accept": "application/json"}, timeout=10,
            )
            if sr.status_code == 200:
                for row in (sr.json().get("data") or [])[:50]:
                    sym = (row.get("code") or "").upper()
                    price = row.get("adjusted_close") or 0
                    if sym and price and float(price) >= 5:
                        _add_to_bucket(momentum_order, sym)
        except Exception as e:
            print(f"[market_scout] EODHD screener failed: {e}")

    # Fallback high-liquidity universe if no discovery feeds return names (e.g. weekend/pre-market)
    if not any((catalyst_order, earnings_order, fda_order, large_cap_quality_order, mover_order, volume_order, rs_order, momentum_order)):
        fallback = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
        for sym in fallback:
            _add_to_bucket(catalyst_order, sym)

    def _dedupe_ordered(*buckets):
        out, seen = [], set()
        for bucket in buckets:
            for t in bucket:
                if t in seen:
                    continue
                if _is_tradeable_equity(t):
                    seen.add(t)
                    out.append(t)
        return out

    full_order = _dedupe_ordered(catalyst_order, earnings_order, fda_order, large_cap_quality_order, mover_order, volume_order, rs_order, momentum_order)
    capped_order = _dedupe_ordered(
        catalyst_order[:20],
        earnings_order[:20],
        fda_order[:10],
        large_cap_quality_order[:30],
        mover_order[:20],
        volume_order[:20],
        rs_order[:10],
        momentum_order[:10],
    )
    final_order = capped_order[:80] if len(full_order) > 80 else full_order[:80]
    global _LAST_DISCOVERY_BUCKETS
    _LAST_DISCOVERY_BUCKETS = {
        "catalyst": list(catalyst_order),
        "earnings": list(earnings_order),
        "fda": list(fda_order),
        "large_cap_quality": list(large_cap_quality_order),
        "movers": list(mover_order),
        "volume": list(volume_order),
        "rs": list(rs_order),
        "momentum": list(momentum_order),
        "final": list(final_order),
    }
    return final_order

def run_scout():
    tickers = discover_tickers()
    results = {"4": [], "3": [], "2": [], "0-1": 0}
    
    for ticker in tickers:
        data = analyze_ticker(ticker)
        if "error" in data:
            continue
            
        score_str = data.get("score", "0/4")
        score_val = int(str(score_str).split("/")[0]) if score_str else 0
        
        if score_val == 4:
            results["4"].append(data)
        elif score_val == 3:
            results["3"].append(data)
        elif score_val == 2:
            results["2"].append(data)
        else:
            results["0-1"] += 1
            
    # Format Output
    print("🦅 **Market Scout: Interval Update**")
    print(f"Scanned {len(tickers)} Discovered Tickers (News-driven).\n")
    
    if results["4"]:
        print("**🟢 BUY (4/4):**")
        for r in results["4"]:
            print(f"• **{r['ticker']}** - Entry: ${r['entry_price']} | Stop Loss: ${r['risk_card']['stop_loss']} | Max Loss/Share: ${r['risk_card']['max_loss_per_share']}")
        print("")
        
    if results["3"]:
        print("**🟡 BUY (Small) (3/4):**")
        for r in results["3"]:
            print(f"• **{r['ticker']}** - Entry: ${r['entry_price']} | Stop Loss: ${r['risk_card']['stop_loss']} | Max Loss/Share: ${r['risk_card']['max_loss_per_share']}")
        print("")
        
    if results["2"]:
        print("**⚪ WATCH (2/4):**")
        watch_tickers = [r['ticker'] for r in results["2"]]
        print(f"• {', '.join(watch_tickers)}\n")
        
    print(f"**🔴 AVOID (0-1/4):** {results['0-1']} tickers.")

if __name__ == "__main__":
    run_scout()
