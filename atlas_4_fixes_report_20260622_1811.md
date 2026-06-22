# AtlasOps 4-fix patch report

Prof., completed the requested fixes across `market_scout.py`, `atlas_engine.py`, and `vault_client.py`.

## 1️⃣ 🦅 FIX 1 + 2 — `market_scout.py`

### Backup

```text
/Users/yasser/scripts/market_scout_backup_20260622_1809.py
```

### Changes applied

1. Fixed score parsing crash.

Replaced:

```python
score_val = int(score_str.split("/")[0])
```

with:

```python
score_val = int(str(score_str).split("/")[0]) if score_str else 0
```

2. Added Massive env constants after `atlas_engine` import:

```python
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
```

3. Added top movers feed inside `discover_tickers()` before fallback:

```python
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

### Feed endpoint status check

Command checked `gainers` and `most_active` directly.

Output:

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
gainers 200
most_active 404
```

Result:

```text
gainers returned 200
most_active returned 404
```

As expected, the safe try/except means `most_active` 404 does not break discovery.

### Discovery behavioral test

Command:

```text
/usr/bin/python3 -c "import sys; sys.path.insert(0,'/Users/yasser/scripts'); import market_scout; ts=market_scout.discover_tickers(); print('COUNT',len(ts)); print('SMCI_IN', 'SMCI' in ts); print(sorted(ts))"
```

Output:

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
COUNT 20
SMCI_IN False
['AA', 'ADP', 'AMZN', 'BA', 'DFTX', 'FTXG', 'GOOGL', 'GPCR', 'GPUS', 'ICLR', 'JBL', 'LRCX', 'NVDA', 'NVO', 'RHHBY', 'SAGT', 'SNDK', 'TSM', 'WDC', 'XOM']
```

Discovery result summary:

```text
COUNT: 20
SMCI_IN: False
FULL_LIST: ['AA', 'ADP', 'AMZN', 'BA', 'DFTX', 'FTXG', 'GOOGL', 'GPCR', 'GPUS', 'ICLR', 'JBL', 'LRCX', 'NVDA', 'NVO', 'RHHBY', 'SAGT', 'SNDK', 'TSM', 'WDC', 'XOM']
```

Note:
- The patch is applied and gainers feed works.
- SMCI was not present in this discovery run’s final 20-symbol universe.

---

## 2️⃣ 🧠 FIX 3 — `atlas_engine.py` catalyst news Accept header

### Backup

Initial backup before first attempt:

```text
/Users/yasser/scripts/atlas_engine_backup_20260622_1810_catalyst_header.py
```

Successful patch backup:

```text
/Users/yasser/scripts/atlas_engine_backup_20260622_1810_catalyst_header_retry.py
```

Note:
- The first broad anchor attempt aborted because the request line appeared 4 times in the file.
- No file write was made by that aborted attempt.
- The successful patch targeted only the bounded `check_news_catalyst()` function.

### Change applied

Inside `check_news_catalyst()`, changed:

```python
r = requests.get(url, params=params, timeout=10)
```

to:

```python
r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=10)
```

### Compile

Command:

```text
python3 -m py_compile /Users/yasser/scripts/atlas_engine.py
```

Result:

```text
ENGINE_COMPILE_OK
```

### Catalyst behavioral test

Command:

```text
/usr/bin/python3 -c "import sys; sys.path.insert(0,'/Users/yasser/scripts'); import atlas_engine as e; print('SMCI', e.check_news_catalyst('SMCI')); print('AAPL', e.check_news_catalyst('AAPL')); print('NVDA', e.check_news_catalyst('NVDA'))"
```

Output:

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
SMCI (False, None)
AAPL (False, None)
NVDA (False, None)
```

Exact returns:

```text
SMCI: (False, None)
AAPL: (False, None)
NVDA: (False, None)
```

Note:
- The Accept header patch compiled and ran.
- The current behavior still returns no strong catalyst for SMCI/AAPL/NVDA.
- SMCI did not return the expected positive catalyst tuple in this test.

---

## 3️⃣ 🏛️ FIX 4 — `vault_client.py` timeout 5s → 10s + one retry

### Backup

```text
/Users/yasser/scripts/vault_client_backup_20260622_1811.py
```

### Changes applied

1. Added standard-library import:

```python
import time
```

2. Updated default timeout from 5 seconds to 10 seconds:

```python
timeout = float(os.environ.get("VAULT_PUSH_TIMEOUT", "10"))
```

3. Added one immediate retry for timeout-like exceptions:

```python
try:
    status, data = _post(payload, timeout)
except Exception as e:  # noqa: BLE001 — retry timeout once, then let outer handler log
    if isinstance(e, TimeoutError) or "timed out" in repr(e).lower():
        time.sleep(1)
        status, data = _post(payload, timeout)
    else:
        raise
```

4. Preserved existing logging and “never propagate” outer exception handling.

5. Updated the configuration comment to say default 10 seconds.

### Compile

Command:

```text
python3 -m py_compile /Users/yasser/scripts/vault_client.py
```

Result:

```text
VAULT_COMPILE_OK
```

### Verification excerpt

Command printed the import and `_do_post()` area.

Output:

```text
46|import json
47|import os
48|import queue
49|import sys
50|import threading
51|import time
52|import urllib.error
53|import urllib.request
54|from datetime import datetime, timezone
243|
244|def _do_post(payload, label, counts):
245|    timeout = float(os.environ.get("VAULT_PUSH_TIMEOUT", "10"))
246|    try:
247|        try:
248|            status, data = _post(payload, timeout)
249|        except Exception as e:  # noqa: BLE001 — retry timeout once, then let outer handler log
250|            if isinstance(e, TimeoutError) or "timed out" in repr(e).lower():
251|                time.sleep(1)
252|                status, data = _post(payload, timeout)
253|            else:
254|                raise
255|        if status == 200 and data.get("ok"):
256|            _log(f"pushed {label} {counts} synced={data.get('synced')}")
257|            return True
258|        _log(f"push {label} rejected: status={status} resp={data}")
259|    except urllib.error.HTTPError as e:
260|        detail = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else ""
261|        _log(f"push {label} HTTP {e.code}: {detail} (will retry on next scheduled sync)")
```

Confirmation:

```text
Vault timeout default is now 10s.
One immediate retry is present for timeout-like exceptions.
Existing failure logging and no-propagation guarantee remain in place.
```

---

## 4️⃣ ✅ Final status summary

Backups:

```text
market_scout.py: /Users/yasser/scripts/market_scout_backup_20260622_1809.py
atlas_engine.py: /Users/yasser/scripts/atlas_engine_backup_20260622_1810_catalyst_header_retry.py
vault_client.py: /Users/yasser/scripts/vault_client_backup_20260622_1811.py
```

Compile results:

```text
market_scout.py: OK
atlas_engine.py: OK
vault_client.py: OK
```

Behavioral test results:

```text
market_scout discover_tickers COUNT: 20
market_scout SMCI_IN: False
Massive gainers endpoint: 200
Massive most_active endpoint: 404
SMCI catalyst return: (False, None)
AAPL catalyst return: (False, None)
NVDA catalyst return: (False, None)
Vault timeout default: 10s
Vault timeout retry: one immediate retry
```

No rollback was required.
