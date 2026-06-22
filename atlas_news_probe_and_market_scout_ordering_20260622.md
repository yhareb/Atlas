# AtlasOps A/B report — Massive news probe + market_scout ordering fix

## 1️⃣ 🧪 A) READ-ONLY Massive Benzinga news endpoint probe

No engine edits were made.

### Raw endpoint probe output

Command run:

```bash
/usr/bin/python3 - <<'PY'
import os, requests
p=os.path.expanduser("~/.hermes/profiles/atlas/.env")
for line in open(p):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
KEY=os.environ.get("MASSIVE_API_KEY"); BASE=os.environ.get("MASSIVE_BASE","https://api.massive.com")
import datetime
gte=(datetime.date.today()-datetime.timedelta(days=3)).strftime('%Y-%m-%d')
H={"Accept":"application/json"}
def probe(url, params):
    try:
        r=requests.get(url, params={**params,"apiKey":KEY}, headers=H, timeout=10)
        print("URL", url, "| params", {k:v for k,v in params.items()}, "->", r.status_code)
        print(r.text[:800]); print("KEYS", list(r.json().keys()) if r.headers.get("content-type","").startswith("application/json") else "n/a"); print("----")
    except Exception as e:
        print("ERR", url, e); print("----")
# current engine call
probe(f"{BASE}/benzinga/v2/news", {"ticker":"SMCI","date.gte":gte,"limit":5})
# param-name variants
probe(f"{BASE}/benzinga/v2/news", {"tickers":"SMCI","date.gte":gte,"limit":5})
probe(f"{BASE}/benzinga/v2/news", {"symbols":"SMCI","limit":5})
# no ticker filter (does the endpoint work at all?)
probe(f"{BASE}/benzinga/v2/news", {"limit":3})
# polygon-style news fallback already used by pre_market_report
probe(f"{BASE}/v2/reference/news", {"ticker":"SMCI","limit":5})
PY
```

Output:

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
URL https://api.massive.com/benzinga/v2/news | params {'ticker': 'SMCI', 'date.gte': '2026-06-19', 'limit': 5} -> 200
{"status":"OK","request_id":"1d43add563c1419492ff21502ba534c6","results":[{"benzinga_id":60016185,"author":"benzinga newsdesk","published":"2026-06-22T14:14:01Z","last_updated":"2026-06-22T14:14:01Z","title":"DA Davidson Maintains Neutral on Life360, Raises Price Target to $42","teaser":"DA Davidson  analyst Wyatt Swanson   maintains Life360 (NASDAQ:LIF) with a Neutral and raises the price target from $40 to $42.","body":"DA Davidson  analyst Wyatt Swanson   maintains Life360 (NASDAQ:<a class=\"ticker\" href=\"https://www.benzinga.com/quote/LIF\">LIF</a>) with a Neutral and raises the price target from $40 to $42.","url":"https://www.benzinga.com/news/26/06/60016185/da-davidson-maintains-neutral-life360-raises-price-target-42","images":[],"channels":["news","price target","analyst ratings"
KEYS ['status', 'request_id', 'results', 'next_url']
----
URL https://api.massive.com/benzinga/v2/news | params {'tickers': 'SMCI', 'date.gte': '2026-06-19', 'limit': 5} -> 200
{"status":"OK","request_id":"455b928606fe479db704b7df0563d331","results":[{"benzinga_id":60012877,"author":"benzinga newsdesk","published":"2026-06-22T13:09:05Z","last_updated":"2026-06-22T13:09:05Z","title":"Super Micro Computer Introduces The Data Center Building Block Solutions Blueprint for HPC Based On Nvidia's Vera Rubin NVL4 Platform","teaser":"Following Supermicro&#39;s DCBBS Blueprints for NVIDIA Vera Rubin NVL72 and NVIDIA HGX Rubin NVL8 introduced at Computex, the Blueprint for HPC and AI applies the same end-to-end methodology to scientific computing. The","body":"<p>Following Supermicro's DCBBS Blueprints for NVIDIA Vera Rubin NVL72 and NVIDIA HGX Rubin NVL8 introduced at Computex, the Blueprint for HPC and AI applies the same end-to-end methodology to scientific computing. Th
KEYS ['status', 'request_id', 'results', 'next_url']
----
URL https://api.massive.com/benzinga/v2/news | params {'symbols': 'SMCI', 'limit': 5} -> 200
{"status":"OK","request_id":"78f629ee3cce43d483123f85fe594062","results":[{"benzinga_id":60016216,"author":"benzinga newsdesk","published":"2026-06-22T14:14:38Z","last_updated":"2026-06-22T14:14:38Z","title":"&#39;SpaceX Bond Offering Expected to Raise at Least $20 Billion&#39; - Wall Street Journal","teaser":"https://www.wsj.com/livecoverage/stock-market-today-dow-sp-500-nasdaq-06-22-2026/card/spacex-launches-first-bond-offering-X0p8hrCvEQ2esAhchUBG","body":"<p>https://www.wsj.com/livecoverage/stock-market-today-dow-sp-500-nasdaq-06-22-2026/card/spacex-launches-first-bond-offering-X0p8hrCvEQ2esAhchUBG</p>","url":"https://www.benzinga.com/news/26/06/60016216/spacex-bond-offering-expected-raise-least-20-billion-wall-street-journal","images":[],"channels":["news"],"tickers":["SPCX"],"tags":[
KEYS ['status', 'request_id', 'results', 'next_url']
----
URL https://api.massive.com/benzinga/v2/news | params {'limit': 3} -> 200
{"status":"OK","request_id":"c0b0dc01088b497998c91e278b5556f5","results":[{"benzinga_id":60016216,"author":"benzinga newsdesk","published":"2026-06-22T14:14:38Z","last_updated":"2026-06-22T14:14:38Z","title":"&#39;SpaceX Bond Offering Expected to Raise at Least $20 Billion&#39; - Wall Street Journal","teaser":"https://www.wsj.com/livecoverage/stock-market-today-dow-sp-500-nasdaq-06-22-2026/card/spacex-launches-first-bond-offering-X0p8hrCvEQ2esAhchUBG","body":"<p>https://www.wsj.com/livecoverage/stock-market-today-dow-sp-500-nasdaq-06-22-2026/card/spacex-launches-first-bond-offering-X0p8hrCvEQ2esAhchUBG</p>","url":"https://www.benzinga.com/news/26/06/60016216/spacex-bond-offering-expected-raise-least-20-billion-wall-street-journal","images":[],"channels":["news"],"tickers":["SPCX"],"tags":[
KEYS ['status', 'request_id', 'results', 'next_url']
----
URL https://api.massive.com/v2/reference/news | params {'ticker': 'SMCI', 'limit': 5} -> 200
{"results":[{"id":"a721bc0d1ae797646fdca895984df110d5434daf8d2900fcf5d24ba0bf1ef5e4","publisher":{"name":"The Motley Fool","homepage_url":"https://www.fool.com/","logo_url":"https://s3.massive.com/public/assets/news/logos/themotleyfool.svg","favicon_url":"https://s3.massive.com/public/assets/news/favicons/themotleyfool.ico"},"title":"Super Micro Jumped More Than 10%. Is the AI Server Maker Finally Turning a Corner?","author":"Daniel Sparks","published_utc":"2026-06-20T15:06:00Z","article_url":"https://www.fool.com/investing/2026/06/20/super-micro-jumped-more-than-10-is-the-ai-server-m/?source=iedfolrf0000001","tickers":["SMCI","SMCIP","NVDA","DELL","HPE","HPEpC"],"image_url":"https://g.foolcdn.com/image/?url=https%3A%2F%2Fg.foolcdn.com%2Feditorial%2Fimages%2F875438%2Fsmci-stock.jpg&w=1200&
KEYS ['results', 'status', 'request_id', 'count', 'next_url']
----
```

## 2️⃣ 🔎 Endpoint read

Working SMCI-relevant shapes:

### ✅ Massive Benzinga endpoint

```text
URL: https://api.massive.com/benzinga/v2/news
Param shape: {"tickers": "SMCI", "date.gte": gte, "limit": 5}
Article list key: results
Title field: results[i].title
```

First returned title:

```text
Super Micro Computer Introduces The Data Center Building Block Solutions Blueprint for HPC Based On Nvidia's Vera Rubin NVL4 Platform
```

### ✅ Polygon-style / reference-news fallback

```text
URL: https://api.massive.com/v2/reference/news
Param shape: {"ticker": "SMCI", "limit": 5}
Article list key: results
Title field: results[i].title
```

First returned title:

```text
Super Micro Jumped More Than 10%. Is the AI Server Maker Finally Turning a Corner?
```

Broken / misleading shapes:

```text
/benzinga/v2/news with {"ticker":"SMCI"} returns 200 but generic/non-SMCI news.
/benzinga/v2/news with {"symbols":"SMCI"} returns 200 but generic/non-SMCI news.
/benzinga/v2/news with no ticker returns generic latest news.
```

Conclusion:

```text
Engine bug is likely param name: it uses "ticker", but Massive Benzinga v2 needs "tickers" for SMCI-specific filtering.
```

No engine edits were made.

---

## 3️⃣ 🛠️ B) market_scout.py ordering fix

### Backup

```text
/Users/yasser/scripts/market_scout_backup_20260622_1814_ordering.py
```

### Applied changes

```text
1. Added mover_order = [] after tickers = set()
2. When a qualifying mover sym is added to tickers, it is also appended to mover_order if not already present.
3. Replaced unordered set truncation with deterministic movers-first ordering:
   movers_first = [t for t in mover_order if _is_tradeable_equity(t)]
   news_rest = [t for t in tickers if _is_tradeable_equity(t) and t not in movers_first]
   ordered = movers_first + news_rest
   return ordered[:25]
```

### Compile

Command:

```text
python3 -m py_compile /Users/yasser/scripts/market_scout.py
```

Result:

```text
MARKET_SCOUT_COMPILE_OK
```

### Behavioral test

Command:

```text
/usr/bin/python3 -c "import sys; sys.path.insert(0,'/Users/yasser/scripts'); import market_scout; ts=market_scout.discover_tickers(); print('COUNT',len(ts)); print('first 10 (movers-first):', ts[:10]); print('SMCI_IN','SMCI' in ts)"
```

Output:

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
COUNT 25
first 10 (movers-first): ['NXTS', 'RTB', 'DFTX', 'APGE', 'BA', 'NKE', 'SSNLF', 'JNJ', 'MSFT', 'IBM']
SMCI_IN False
```

## 4️⃣ ✅ Summary

```text
1. Probe complete: tickers=SMCI is the correct Massive Benzinga v2 filter param.
2. /v2/reference/news?ticker=SMCI also returns SMCI-relevant results.
3. market_scout.py ordering fix applied.
4. market_scout.py compile OK.
5. discovery now returns 25 max, movers first.
6. No engine edits made yet.
```
