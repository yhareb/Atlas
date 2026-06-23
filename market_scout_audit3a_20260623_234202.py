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


def discover_rs_leaders(top_n=RS_TOP_N):
    """Discover multi-day relative-strength leaders vs SPY using EODHD screener data."""
    if not EODHD_API_KEY:
        return []
    import json as _json

    spy_filters = [["code", "=", "SPY"]]
    spy_resp = requests.get(
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
    rs_resp = requests.get(
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
            response = requests.get(url, params=params, headers={"Accept": "application/json"})
            if response.status_code == 200:
                for item in response.json():
                    for stock in item.get("stocks", []):
                        if stock.get("name"):
                            tickers.add(stock["name"].upper())
        except Exception as e:
            print(f"[market_scout] Benzinga discovery failed: {e}")
            
    # --- Top movers feed: gainers + most-active (price >= $5), so breakout/volume leaders are always surfaced ---
    if MASSIVE_API_KEY:
        try:
            mr = requests.get(
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
                        tickers.add(sym)
                        if sym not in mover_order:
                            mover_order.append(sym)
        except Exception as e:
            print(f"[market_scout] gainers feed failed: {e}")

        # Massive has no working /most_active snapshot path on this plan; use the
        # all-tickers snapshot and rank locally by current-day volume.
        try:
            mr = requests.get(
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
                    tickers.add(sym)
                    if sym not in mover_order:
                        mover_order.append(sym)
        except Exception as e:
            print(f"[market_scout] most-active snapshot failed: {e}")

    # RS leaders: multi-day outperformers vs SPY
    try:
        rs_leaders = discover_rs_leaders(top_n=RS_TOP_N)
        for sym in rs_leaders:
            if _is_tradeable_equity(sym):
                tickers.add(sym)
                if sym not in mover_order:
                    mover_order.append(sym)
    except Exception:
        pass

    # EODHD screener: fresh liquid/moving US names, fed into the SAME normal engine scan.
    if EODHD_API_KEY:
        try:
            import json as _json
            filters = [["refund_1d_p", ">", 3], ["avgvol_200d", ">", 1000000], ["exchange", "=", "US"], ["market_capitalization", ">", 300000000]]
            sr = requests.get(
                "https://eodhd.com/api/screener",
                params={"api_token": EODHD_API_KEY, "fmt": "json", "filters": _json.dumps(filters), "limit": 50, "sort": "refund_1d_p.desc"},
                headers={"Accept": "application/json"}, timeout=10,
            )
            if sr.status_code == 200:
                for row in (sr.json().get("data") or [])[:50]:
                    sym = (row.get("code") or "").upper()
                    price = row.get("adjusted_close") or 0
                    if sym and price and float(price) >= 5:
                        tickers.add(sym)
                        if sym not in mover_order:
                            mover_order.append(sym)
        except Exception as e:
            print(f"[market_scout] EODHD screener failed: {e}")

    # Fallback high-liquidity universe if no news is found (e.g. weekend/pre-market)
    if not tickers:
        tickers = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
        
    movers_first = [t for t in mover_order if _is_tradeable_equity(t)]
    news_rest = [t for t in tickers if _is_tradeable_equity(t) and t not in movers_first]
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
