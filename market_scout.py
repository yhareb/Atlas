import os
import sys
import requests
import datetime

# Ensure it can find the engine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from atlas_engine import analyze_ticker

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
            response = requests.get(url, params=params)
            if response.status_code == 200:
                for item in response.json():
                    for stock in item.get("stocks", []):
                        if stock.get("name"):
                            tickers.add(stock["name"].upper())
        except:
            pass
            
    # Fallback high-liquidity universe if no news is found (e.g. weekend/pre-market)
    if not tickers:
        tickers = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
        
    return list(tickers)[:20] # Limit to 20 per scan for speed

def run_scout():
    tickers = discover_tickers()
    results = {"4": [], "3": [], "2": [], "0-1": 0}
    
    for ticker in tickers:
        data = analyze_ticker(ticker)
        if "error" in data:
            continue
            
        score_str = data.get("score", "0/4")
        score_val = int(score_str.split("/")[0])
        
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
