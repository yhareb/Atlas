# Atlas read-only patch discovery

Read-only. No edits were made.

## 1. Discovery functions in market_scout.py

Full discovery function that builds the ticker universe, including Benzinga/news call and final list assembly:

```text
34|def discover_tickers():
35|    # Use Benzinga to find stocks with breaking news today
36|    benzinga_key = os.environ.get("BENZINGA_API_KEY")
37|    tickers = set()
38|    
39|    if benzinga_key:
40|        url = "https://api.benzinga.com/api/v2/news"
41|        params = {
42|            "token": benzinga_key,
43|            "dateFrom": datetime.date.today( ).strftime('%Y-%m-%d'),
44|            "pageSize": 50
45|        }
46|        try:
47|            response = requests.get(url, params=params, headers={"Accept": "application/json"})
48|            if response.status_code == 200:
49|                for item in response.json():
50|                    for stock in item.get("stocks", []):
51|                        if stock.get("name"):
52|                            tickers.add(stock["name"].upper())
53|        except Exception as e:
54|            print(f"[market_scout] Benzinga discovery failed: {e}")
55|            
56|    # Fallback high-liquidity universe if no news is found (e.g. weekend/pre-market)
57|    if not tickers:
58|        tickers = {"NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL", "NFLX", "SMCI", "PLTR", "COIN"}
59|        
60|    tickers = {t for t in tickers if _is_tradeable_equity(t)}
61|    return list(tickers)[:20] # Limit to 20 per scan for speed
```

Related filter and import context:

```text
6|# Symbols the engine must never trade as stock picks
7|ETF_BLOCKLIST = {
8|    "SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "IVV",
9|    "EWY", "EWZ", "EWJ", "FXI", "EEM", "EFA", "GLD", "SLV",
10|    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
11|    "TQQQ", "SQQQ", "SOXL", "SOXS", "UVXY", "VXX",
12|}
13|
14|def _is_tradeable_equity(sym):
15|    if not sym:
16|        return False
17|    s = sym.strip().upper()
18|    if s.startswith("$"):          # crypto like $BTC
19|        return False
20|    if "." in s or "-" in s:        # foreign/OTC/preferred classes
21|        return False
22|    if not s.isalpha():             # only clean alphabetic tickers
23|        return False
24|    if len(s) > 5:                  # US equities are 1-5 letters
25|        return False
26|    if s in ETF_BLOCKLIST:
27|        return False
28|    return True
29|
30|# Ensure it can find the engine
31|sys.path.append(os.path.dirname(os.path.abspath(__file__)))
32|from atlas_engine import analyze_ticker
```

## 2. Crashing split line in market_scout.py

`grep -n "split" /Users/yasser/scripts/market_scout.py` output:

```text
73:        score_val = int(score_str.split("/")[0])
```

Surrounding function:

```text
63|def run_scout():
64|    tickers = discover_tickers()
65|    results = {"4": [], "3": [], "2": [], "0-1": 0}
66|    
67|    for ticker in tickers:
68|        data = analyze_ticker(ticker)
69|        if "error" in data:
70|            continue
71|            
72|        score_str = data.get("score", "0/4")
73|        score_val = int(score_str.split("/")[0])
74|        
75|        if score_val == 4:
76|            results["4"].append(data)
77|        elif score_val == 3:
78|            results["3"].append(data)
79|        elif score_val == 2:
80|            results["2"].append(data)
81|        else:
82|            results["0-1"] += 1
83|            
84|    # Format Output
85|    print("🦅 **Market Scout: Interval Update**")
86|    print(f"Scanned {len(tickers)} Discovered Tickers (News-driven).\n")
87|    
88|    if results["4"]:
89|        print("**🟢 BUY (4/4):**")
90|        for r in results["4"]:
91|            print(f"• **{r['ticker']}** - Entry: ${r['entry_price']} | Stop Loss: ${r['risk_card']['stop_loss']} | Max Loss/Share: ${r['risk_card']['max_loss_per_share']}")
92|        print("")
93|        
94|    if results["3"]:
95|        print("**🟡 BUY (Small) (3/4):**")
96|        for r in results["3"]:
97|            print(f"• **{r['ticker']}** - Entry: ${r['entry_price']} | Stop Loss: ${r['risk_card']['stop_loss']} | Max Loss/Share: ${r['risk_card']['max_loss_per_share']}")
98|        print("")
99|        
100|    if results["2"]:
101|        print("**⚪ WATCH (2/4):**")
102|        watch_tickers = [r['ticker'] for r in results["2"]]
103|        print(f"• {', '.join(watch_tickers)}\n")
104|        
105|    print(f"**🔴 AVOID (0-1/4):** {results['0-1']} tickers.")
106|
107|if __name__ == "__main__":
108|    run_scout()
```

## 3. Massive gainers / most-active calls in market_scout.py

Search command:

```text
grep -n -i -E "gainers|most active|most_active|active|snapshot|benzinga|news" /Users/yasser/scripts/market_scout.py
```

Output:

```text
35:    # Use Benzinga to find stocks with breaking news today
36:    benzinga_key = os.environ.get("BENZINGA_API_KEY")
39:    if benzinga_key:
40:        url = "https://api.benzinga.com/api/v2/news"
42:            "token": benzinga_key,
54:            print(f"[market_scout] Benzinga discovery failed: {e}")
56:    # Fallback high-liquidity universe if no news is found (e.g. weekend/pre-market)
86:    print(f"Scanned {len(tickers)} Discovered Tickers (News-driven).\n")
```

Conclusion:

```text
NONE — market_scout.py does not currently have Massive gainers, most-active, or stock snapshot universe calls.
```

## 4. Per-ticker news fetch in atlas_engine.py

Exact code that fetches per-ticker news, including function name, URL, params, and request call:

```text
132|def check_news_catalyst(ticker):
133|    if not MASSIVE_API_KEY:
134|        return False, None
135|    url = f"{MASSIVE_BASE}/benzinga/v2/news"
136|    params = {
137|        "apiKey": MASSIVE_API_KEY,
138|        "ticker": ticker,
139|        "date.gte": (datetime.date.today() - timedelta(days=3)).strftime('%Y-%m-%d'),
140|        "limit": 5
141|    }
142|    try:
143|        r = requests.get(url, params=params, timeout=10)
144|        if r.status_code == 200:
145|            data = r.json()
146|            results = data.get("results", [])
147|            if results:
148|                headlines = [x.get("title", "") for x in results if x.get("title")]
149|                verdict = _llm_judge_catalyst(ticker, headlines)
150|                if verdict is not None:
151|                    rating, reason = verdict
152|                    if rating == "STRONG":
153|                        return True, f"LLM: {reason}" if reason else "LLM: strong catalyst"
154|                    else:
155|                        return False, None
156|                # Fallback (LLM unavailable): old behavior — news exists = catalyst
157|                return True, results[0].get("title", "Recent news found")
158|    except:
159|        pass
160|    return False, None
```

Headers:

```text
No headers are passed in this requests.get call.
```

Ticker filtering:

```text
The params dict includes "ticker": ticker.
```

## 5. _llm_judge_catalyst and call lines in atlas_engine.py

Full `_llm_judge_catalyst`:

```text
99|def _llm_judge_catalyst(ticker, headlines):
100|    """Ask the LLM if the headlines are a genuinely STRONG, tradeable bullish catalyst.
101|    Fails safe: on any error returns None so caller uses fallback logic."""
102|    api_key = os.environ.get("OPENAI_API_KEY")
103|    if not api_key or not headlines:
104|        return None
105|    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
106|    joined = "\n".join(f"- {h}" for h in headlines[:5])
107|    prompt = (
108|        f"You are a professional equity catalyst analyst. Ticker: {ticker}.\n"
109|        f"Recent headlines:\n{joined}\n\n"
110|        "Classify the bullish catalyst strength for a swing trade as exactly one word: "
111|        "STRONG, WEAK, or NONE. STRONG = a concrete, material, positive, price-moving "
112|        "event (e.g. major product/contract, earnings blowout, FDA approval, major upgrade). "
113|        "Mere mentions, neutral coverage, or negative news = WEAK or NONE. "
114|        "Respond in JSON: {\"rating\":\"STRONG|WEAK|NONE\",\"reason\":\"<8 words>\"}"
115|    )
116|    try:
117|        r = requests.post(
118|            f"{base}/chat/completions",
119|            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
120|            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
121|                  "temperature": 0, "response_format": {"type": "json_object"}},
122|            timeout=8,
123|        )
124|        if r.status_code == 200:
125|            content = r.json()["choices"][0]["message"]["content"]
126|            parsed = json.loads(content)
127|            return parsed.get("rating", "").upper(), parsed.get("reason", "")[:60]
128|    except Exception as e:
129|        print(f"[catalyst-llm] {ticker}: {e}")
130|    return None
```

Call inside `check_news_catalyst` showing what variable is passed:

```text
145|            data = r.json()
146|            results = data.get("results", [])
147|            if results:
148|                headlines = [x.get("title", "") for x in results if x.get("title")]
149|                verdict = _llm_judge_catalyst(ticker, headlines)
150|                if verdict is not None:
151|                    rating, reason = verdict
```

Catalyst pillar call site:

```text
300|    else:
301|        pillar_details.append(f"❌ Volume: NO (RVOL: {rvol:.2f} < {RVOL_MIN})")
302|
303|    # Pillar 4: Catalyst (News + Analyst Upgrade) — unchanged
304|    news_hit, news_title = check_news_catalyst(ticker)
305|    analyst_hit, analyst_detail = check_analyst_ratings(ticker)
306|    if analyst_hit:
307|        pillars_met += 1
308|        pillar_details.append(f"✅ Catalyst: YES — {analyst_detail}")
309|    elif news_hit:
310|        pillars_met += 1
311|        pillar_details.append(f"✅ Catalyst: YES — Recent news")
312|    else:
313|        pillar_details.append("❌ Catalyst: NO")
314|
315|    # Earnings Risk Warning
316|    earnings_soon, earnings_date = check_earnings_risk(ticker)
317|    if earnings_soon:
318|        warnings.append(f"⚠️ Earnings in next 7 days ({earnings_date}) — elevated risk")
```

## 6. Vault timeout and retry/backoff logic in vault_client.py

Search command:

```text
grep -n -i -E "timeout|retry|backoff|requests\.|post\(|Session|HTTPAdapter" /Users/yasser/scripts/vault_client.py
```

Output:

```text
17:  all exceptions (network down, bad token, timeout) and returns a bool. A Vault
31:    VAULT_PUSH_TIMEOUT optional; seconds (default 5) — kept short so a slow
215:def _post(payload, timeout):
230:    with urllib.request.urlopen(req, timeout=timeout) as resp:
243:def _do_post(payload, label, counts):
244:    timeout = float(os.environ.get("VAULT_PUSH_TIMEOUT", "5"))
246:        status, data = _post(payload, timeout)
253:        _log(f"push {label} HTTP {e.code}: {detail} (will retry on next scheduled sync)")
255:        _log(f"push {label} failed: {e!r} (will retry on next scheduled sync)")
263:            _do_post(payload, label, counts)
287:        return _do_post(payload, label, counts)
295:def flush(timeout=10):
309:    return done.wait(timeout)
```

Relevant code:

```text
215|def _post(payload, timeout):
216|    url = os.environ["VAULT_URL"].rstrip("/") + "/api/sync"
217|    token = os.environ["VAULT_SYNC_TOKEN"]
218|    body = json.dumps(payload).encode("utf-8")
219|    req = urllib.request.Request(
220|        url,
221|        data=body,
222|        method="POST",
223|        headers={
224|            "Content-Type": "application/json",
225|            "Authorization": f"Bearer {token}",
226|            "User-Agent": "Atlas-VaultSync/1.0",
227|            "Accept": "application/json",
228|        },
229|    )
230|    with urllib.request.urlopen(req, timeout=timeout) as resp:
231|        return resp.status, json.loads(resp.read().decode("utf-8"))
232|
233|
234|# A single ordered worker thread drains this queue. Serializing pushes this way
235|# guarantees they reach the Vault in CALL ORDER, so an earlier push (e.g. a lot
236|# at quantity 100) can never overwrite a later one (the same lot shrunk to 60).
237|# This removes the out-of-order race that independent daemon threads would have.
238|_push_q: "queue.Queue" = queue.Queue()
239|_worker_lock = threading.Lock()
240|_worker_started = False
241|
242|
243|def _do_post(payload, label, counts):
244|    timeout = float(os.environ.get("VAULT_PUSH_TIMEOUT", "5"))
245|    try:
246|        status, data = _post(payload, timeout)
247|        if status == 200 and data.get("ok"):
248|            _log(f"pushed {label} {counts} synced={data.get('synced')}")
249|            return True
250|        _log(f"push {label} rejected: status={status} resp={data}")
251|    except urllib.error.HTTPError as e:
252|        detail = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else ""
253|        _log(f"push {label} HTTP {e.code}: {detail} (will retry on next scheduled sync)")
254|    except Exception as e:  # noqa: BLE001 — must never propagate into Atlas
255|        _log(f"push {label} failed: {e!r} (will retry on next scheduled sync)")
256|    return False
257|
258|
259|def _worker():
260|    while True:
261|        payload, label, counts = _push_q.get()
262|        try:
263|            _do_post(payload, label, counts)
264|        except Exception:  # noqa: BLE001 — worker must never die
265|            pass
266|        finally:
267|            _push_q.task_done()
268|
269|
270|def _ensure_worker():
271|    global _worker_started
272|    with _worker_lock:
273|        if not _worker_started:
274|            threading.Thread(target=_worker, name="vault-push", daemon=True).start()
275|            _worker_started = True
276|
277|
278|def _send(payload, label, blocking):
279|    """Enqueue a payload for ordered delivery. Returns True on success (blocking)."""
280|    if not _enabled():
281|        return False
282|    counts = {k: len(v) for k, v in payload.items() if isinstance(v, list)}
283|    if not any(counts.values()):
284|        return False
285|
286|    if blocking:
287|        return _do_post(payload, label, counts)
288|    # Ordered async delivery: one worker drains the queue in FIFO (call) order,
289|    # so the Atlas command returns instantly but pushes never reorder.
290|    _ensure_worker()
291|    _push_q.put((payload, label, counts))
292|    return True
293|
294|
295|def flush(timeout=10):
296|    """Block until all queued pushes have been attempted (best-effort).
297|
298|    Useful for short-lived scripts that would otherwise exit before the daemon
299|    worker drains the queue. Returns True if the queue emptied in time."""
300|    if not _worker_started:
301|        return True
302|    done = threading.Event()
303|
304|    def waiter():
305|        _push_q.join()
306|        done.set()
307|
308|    threading.Thread(target=waiter, daemon=True).start()
309|    return done.wait(timeout)
```

Timeout / retry read:

```text
- Vault push timeout comes from VAULT_PUSH_TIMEOUT, default 5 seconds.
- It uses urllib.request.urlopen(..., timeout=timeout).
- There is no immediate retry loop or backoff inside _do_post().
- Failures are logged as "will retry on next scheduled sync".
- Async pushes are queued to one worker thread; failed pushes return False and are not retried immediately in that worker.
- Blocking push uses the same _do_post() path.
- flush(timeout=10) waits for queued pushes to be attempted, not retried.
```
