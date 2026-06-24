import os
import sys
import requests
import datetime

# Symbols the engine must never trade as stock picks
ETF_BLOCKLIST = {
    "SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "IVV",
    "EWY", "EWZ", "EWJ", "FXI", "EEM", "EFA", "GLD", "SLV",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "TQQQ", "SQQQ", "SOXL", "SOXS", "UVXY", "VXX",
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
    if s in ETF_BLOCKLIST:
        return False
    return True

# Ensure it can find the engine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from atlas_engine import analyze_ticker
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
RS_MIN_SCORE = 1.5
RS_SCAN_UNIVERSE = 100
RS_TOP_N = 20
REVERSE_SPLIT_LOOKBACK_DAYS = 30
_REVERSE_SPLIT_CACHE = {}


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


def has_recent_reverse_split(sym, days=REVERSE_SPLIT_LOOKBACK_DAYS):
    """True if EODHD split data shows a reverse split in the recent lookback."""
    s = (sym or "").strip().upper()
    if not s or not EODHD_API_KEY:
        return False
    today = datetime.date.today()
    cache_key = f"{s}:{today.isoformat()}:{int(days)}"
    if cache_key in _REVERSE_SPLIT_CACHE:
        return _REVERSE_SPLIT_CACHE[cache_key]
    start = (today - datetime.timedelta(days=int(days))).isoformat()
    try:
        r = _audit_get(
            f"https://eodhd.com/api/splits/{s}.US",
            params={"api_token": EODHD_API_KEY, "fmt": "json", "from": start, "to": today.isoformat()},
            headers={"Accept": "application/json"}, timeout=8,
        )
        if r.status_code != 200:
            _REVERSE_SPLIT_CACHE[cache_key] = False
            return False
        rows = r.json()
        if not isinstance(rows, list):
            _REVERSE_SPLIT_CACHE[cache_key] = False
            return False
        for row in rows:
            ratio = _parse_split_ratio((row or {}).get("split"))
            if not ratio:
                continue
            new_shares, old_shares = ratio
            # EODHD reverse split example: 1.000000/6.000000 = 1 new share for 6 old shares.
            if new_shares > 0 and old_shares > 0 and new_shares < old_shares:
                _REVERSE_SPLIT_CACHE[cache_key] = True
                return True
    except Exception as e:
        print(f"[market_scout] reverse split check failed for {s}: {e}")
    _REVERSE_SPLIT_CACHE[cache_key] = False
    return False


def _add_candidate(sym, tickers, mover_order=None):
    s = (sym or "").strip().upper()
    if not _is_tradeable_equity(s):
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
    if spy_5d_return <= 0:
        return []

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
        rs_score = stock_5d_return / spy_5d_return
        if rs_score >= RS_MIN_SCORE:
            leaders.append((sym, rs_score))

    leaders.sort(key=lambda item: item[1], reverse=True)
    return [sym for sym, _score in leaders[:top_n]]


def discover_tickers():
    # Use Benzinga to find stocks with breaking news today
    benzinga_key = os.environ.get("BENZINGA_API_KEY")
    tickers = set()
    mover_order = []
    
    if benzinga_key:
        url = "https://api.benzinga.com/api/v2/news"
        params = {
            "token": benzinga_key,
            "dateFrom": datetime.date.today( ).strftime('%Y-%m-%d'),
            "pageSize": 50
        }
        try:
            response = _audit_get(url, params=params, headers={"Accept": "application/json"})
            if response.status_code == 200:
                for item in response.json():
                    for stock in item.get("stocks", []):
                        if stock.get("name"):
                            _add_candidate(stock["name"], tickers)
        except Exception as e:
            print(f"[market_scout] Benzinga discovery failed: {e}")
            
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
                        _add_candidate(sym, tickers, mover_order)
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
                for _volume, t in sorted(volume_rows, key=lambda item: item[0], reverse=True)[:15]:
                    sym = (t.get("ticker") or "").upper()
                    _add_candidate(sym, tickers, mover_order)
        except Exception as e:
            print(f"[market_scout] most-active snapshot failed: {e}")

    # RS leaders: multi-day outperformers vs SPY
    try:
        rs_leaders = discover_rs_leaders(top_n=RS_TOP_N)
        for sym in rs_leaders:
            if _is_tradeable_equity(sym):
                _add_candidate(sym, tickers, mover_order)
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
                        _add_candidate(sym, tickers, mover_order)
        except Exception as e:
            print(f"[market_scout] EODHD screener failed: {e}")

    # Fallback high-liquidity universe if no news is found (e.g. weekend/pre-market)
    if not tickers:
        fallback = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
        tickers = set()
        for sym in fallback:
            _add_candidate(sym, tickers)
        
    movers_first = [t for t in mover_order if _is_tradeable_equity(t) and not has_recent_reverse_split(t)]
    news_rest = [t for t in tickers if _is_tradeable_equity(t) and not has_recent_reverse_split(t) and t not in movers_first]
    ordered = movers_first + news_rest
    return ordered[:40]   # movers guaranteed in; cap raised slightly to 40

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
