# Pre-market futures N/A diagnostic

Read-only probe. No edits were made to `pre_market_report.py`.

## Purpose

Diagnose why the pre-market brief prints futures as `N/A`.

Current code path in `pre_market_report.py` calls:

```python
massive_get("/futures/v1/snapshot", {"product_code": code, "limit": 1})
```

for product codes:

```text
ES, NQ, YM
```

## Raw probe output

Command run:

```bash
/usr/bin/python3 - <<'PY'
import os, json, requests
p=os.path.expanduser("~/.hermes/profiles/atlas/.env")
for line in open(p):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
KEY=os.environ.get("MASSIVE_API_KEY"); BASE="https://api.massive.com"
def get(path, params):
    params=dict(params); params["apiKey"]=KEY
    try:
        r=requests.get(BASE+path, params=params, timeout=10)
        print("PATH", path, params.get("product_code"), "->", r.status_code)
        print(r.text[:600]); print("----")
    except Exception as e:
        print("ERR", path, e)
# current call
for c in ["ES","NQ","YM"]:
    get("/futures/v1/snapshot", {"product_code": c, "limit": 1})
# alternative shapes to discover the right one
get("/futures/v1/snapshot", {})
get("/futures/snapshot", {})
get("/v2/snapshot/locale/us/markets/futures/tickers", {})
PY
```

Output:

```text
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
PATH /futures/v1/snapshot ES -> 403
{"status":"NOT_AUTHORIZED","request_id":"98dab30821207e869372d2e64e909613","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}
----
PATH /futures/v1/snapshot NQ -> 403
{"status":"NOT_AUTHORIZED","request_id":"9c144b4661199594e1733f88e80adca0","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}
----
PATH /futures/v1/snapshot YM -> 403
{"status":"NOT_AUTHORIZED","request_id":"f1bb2472330ac52e46f0f52bfb82ac86","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}
----
PATH /futures/v1/snapshot None -> 403
{"status":"NOT_AUTHORIZED","request_id":"6ba7c8ba0a4b919799706c5091aada15","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}
----
PATH /futures/snapshot None -> 404
404 page not found
----
PATH /v2/snapshot/locale/us/markets/futures/tickers None -> 404
404 page not found
----
```

## Endpoint read

No probed endpoint returned `200` with data.

Results:

```text
/futures/v1/snapshot with product_code=ES -> 403 NOT_AUTHORIZED
/futures/v1/snapshot with product_code=NQ -> 403 NOT_AUTHORIZED
/futures/v1/snapshot with product_code=YM -> 403 NOT_AUTHORIZED
/futures/v1/snapshot with no product_code -> 403 NOT_AUTHORIZED
/futures/snapshot -> 404 page not found
/v2/snapshot/locale/us/markets/futures/tickers -> 404 page not found
```

## Why futures show N/A

The current endpoint path appears valid enough to return a structured Massive auth response, but the current Massive plan/key is not entitled to futures data:

```json
{"status":"NOT_AUTHORIZED","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}
```

Because `massive_get()` only returns JSON when `r.status_code == 200`, these 403 responses become `None`, so `get_futures()` appends `N/A` for ES, NQ, and YM.

## Correct endpoint/fields

No endpoint/param shape from the requested probes returned a `200`, so I cannot verify live JSON keys for price/change from current data.

The existing code expects, if authorized, a shape like:

```text
results[0].session.close
results[0].session.change_percent
or fallback: results[0].last_trade.price
```

But this could not be confirmed from live data because all futures snapshot attempts either returned 403 or 404.

## Suggested next patch direction, pending Prof. exact patch

Since Massive futures entitlement is blocked, an operational patch should either:

1. Replace futures with ETF/index proxy snapshots already covered by the current stock entitlement, e.g. SPY / QQQ / DIA pre-market percent moves; or
2. Keep futures section but explicitly show `Not authorized by Massive plan` instead of silent `N/A`; or
3. Use a different authorized data source if available.

No edits made.
