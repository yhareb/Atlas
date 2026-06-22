# pre_market_report.py read-only inspection

Read-only inspection. No files were modified.

## Full current source with line numbers

```text
1|import os, sys, requests
2|from datetime import datetime, timedelta, date
3|from zoneinfo import ZoneInfo
4|sys.path.insert(0, "/Users/yasser/scripts")
5|import atlas_db
6|
7|_env_path = os.path.expanduser("~/.hermes/profiles/atlas/.env")
8|if os.path.exists(_env_path):
9|    with open(_env_path) as _f:
10|        for _line in _f:
11|            _line = _line.strip()
12|            if _line and not _line.startswith("#") and "=" in _line:
13|                _k, _v = _line.split("=", 1)
14|                os.environ.setdefault(_k.strip(), _v.strip())
15|
16|MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
17|TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
18|TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
19|MASSIVE_BASE = "https://api.massive.com"
20|
21|NYSE_HOLIDAYS_2026 = {
22|    date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),
23|    date(2026,5,25),date(2026,6,19),date(2026,7,3),date(2026,9,7),
24|    date(2026,11,26),date(2026,11,27),date(2026,12,25),
25|}
26|
27|def send_telegram(message):
28|    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
29|        print(message); return
30|    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
31|    try:
32|        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
33|        if r.status_code != 200: print(f"[Telegram error] {r.status_code}: {r.text}")
34|    except Exception as e: print(f"[Telegram failed] {e}")
35|
36|def massive_get(path, params=None):
37|    p = params or {}
38|    p["apiKey"] = MASSIVE_API_KEY
39|    try:
40|        r = requests.get(f"{MASSIVE_BASE}{path}", params=p, timeout=10)
41|        if r.status_code == 200: return r.json()
42|    except Exception as e: print(f"[Massive error] {path}: {e}")
43|    return None
44|
45|def arrow(pct):
46|    if pct is None: return "—"
47|    return f"▲ +{pct:.2f}%" if pct > 0 else (f"▼ {pct:.2f}%" if pct < 0 else f"→ {pct:.2f}%")
48|
49|def get_futures():
50|    lines = []
51|    for code, label in [("ES","S&P 500"),("NQ","Nasdaq 100"),("YM","Dow Jones")]:
52|        data = massive_get("/futures/v1/snapshot", {"product_code": code, "limit": 1})
53|        if data and data.get("results"):
54|            r = data["results"][0]; s = r.get("session",{})
55|            price = s.get("close") or (r.get("last_trade") or {}).get("price")
56|            pct = s.get("change_percent")
57|            lines.append(f"  {label}: ${price:,.2f}  {arrow(pct)}" if price else f"  {label}: N/A")
58|        else: lines.append(f"  {label}: N/A")
59|    return lines
60|
61|def get_top_movers():
62|    gl, ll = [], []
63|    for direction, lst in [("gainers", gl), ("losers", ll)]:
64|        data = massive_get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
65|        if data and data.get("tickers"):
66|            for t in data["tickers"][:5]:
67|                ticker = t.get("ticker","?"); pct = t.get("todaysChangePerc",0)
68|                price = (t.get("day") or {}).get("c")
69|                sym = "▲ +" if direction == "gainers" else "▼ "
70|                lst.append(f"  • {ticker} {'$'+f'{price:.2f}' if price else 'N/A'}  {sym}{abs(pct):.2f}%")
71|    return gl, ll
72|
73|def get_handoff_snapshot():
74|    today = datetime.now().strftime('%Y-%m-%d')
75|    yesterday = (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d')
76|    data = atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday)
77|    if not data: return [], []
78|    bl, wl = [], []
79|    for ticker in data.get("BUY",[]):
80|        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
81|        if snap and snap.get("ticker"):
82|            t = snap["ticker"]; price = (t.get("day") or {}).get("c"); pct = t.get("todaysChangePerc")
83|            bl.append(f"  • {ticker} {'$'+f'{price:.2f}' if price else 'N/A'}  {arrow(pct)}")
84|        else: bl.append(f"  • {ticker}")
85|    for ticker in data.get("WATCH",[]):
86|        snap = massive_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
87|        if snap and snap.get("ticker"):
88|            t = snap["ticker"]; price = (t.get("day") or {}).get("c"); pct = t.get("todaysChangePerc")
89|            wl.append(f"  • {ticker} {'$'+f'{price:.2f}' if price else 'N/A'}  {arrow(pct)}")
90|        else: wl.append(f"  • {ticker}")
91|    return bl, wl
92|
93|def get_benzinga_headlines():
94|    since = (datetime.utcnow()-timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
95|    data = massive_get("/v2/reference/news", {"published_utc.gte": since, "limit": 5, "sort": "published_utc", "order": "desc"})
96|    if data and data.get("results"):
97|        return [f"  • {a.get('title','No title')}" for a in data["results"][:5]]
98|    return []
99|
100|def generate_pre_market_report():
101|    now_et = datetime.now(ZoneInfo("America/New_York"))
102|    today = now_et.date()
103|    if today in NYSE_HOLIDAYS_2026 or today.weekday() >= 5: return
104|    today_str = today.strftime("%Y-%m-%d")
105|    lines = [f"🌄 *Pre-Market Brief — {today_str}*", ""]
106|    lines.append("*Index Futures:*"); lines.extend(get_futures() or ["  N/A"]); lines.append("")
107|    gainers, losers = get_top_movers()
108|    lines.append("*Top Pre-Market Gainers:*"); lines.extend(gainers or ["  None yet"]); lines.append("")
109|    lines.append("*Top Pre-Market Losers:*"); lines.extend(losers or ["  None yet"]); lines.append("")
110|    buy_lines, watch_lines = get_handoff_snapshot()
111|    if buy_lines: lines.append("*Active BUY Signals (from last night):*"); lines.extend(buy_lines); lines.append("")
112|    if watch_lines: lines.append("*WATCH List (from last night):*"); lines.extend(watch_lines); lines.append("")
113|    headlines = get_benzinga_headlines()
114|    if headlines: lines.append("*Latest Headlines:*"); lines.extend(headlines); lines.append("")
115|    lines.append("_Ready for the open, Prof._")
116|    send_telegram("\n".join(lines))
117|
118|if __name__ == "__main__":
119|    generate_pre_market_report()
```

## Answers

1. Function that builds/sends the final message:

- Builder/orchestrator: `generate_pre_market_report()` at line 100.
- Sender: `send_telegram(message)` at line 27.
- Sender signature: `def send_telegram(message):`
- Final send call: line 116, `send_telegram("\n".join(lines))`

2. Does it read the handoff table?

- Yes.
- It calls `atlas_db.get_handoff(today) or atlas_db.get_handoff(yesterday)` at line 76 inside `get_handoff_snapshot()`.

3. grep for OpenAI/GPT/economic/calendar:

Command:
```text
grep -n -i -E "openai|gpt|chat.completions|economic|calendar" /Users/yasser/scripts/pre_market_report.py
```

Result:
```text
NONE
```

4. launchd plist check:

Command:
```text
ls -la /Users/yasser/Library/LaunchAgents/ | grep -i -E "pre|brief|morning"
```

Result:
```text
NONE
```

## Additional notes

- `pre_market_report.py` imports `requests`, `atlas_db`, `ZoneInfo`, and date/time helpers.
- It uses Massive API endpoints for futures, stock movers, ticker snapshots, and news.
- It sends via Telegram Bot API when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set; otherwise it prints the message.
- No OpenAI/LLM call is present in the current script.
- No matching user LaunchAgent plist was found for pre/brief/morning.
