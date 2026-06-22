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

def discover_tickers():
    # Use Benzinga to find stocks with breaking news today
    benzinga_key = os.environ.get("BENZINGA_API_KEY")
    tickers = set()
    
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
        for direction in ("gainers", "most_active"):
            try:
                mr = requests.get(
                    f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/{direction}",
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
            except Exception as e:
                print(f"[market_scout] {direction} feed failed: {e}")

    # Fallback high-liquidity universe if no news is found (e.g. weekend/pre-market)
    if not tickers:
        tickers = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
        
    tickers = {t for t in tickers if _is_tradeable_equity(t)}
    return list(tickers)[:20] # Limit to 20 per scan for speed

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
