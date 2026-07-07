# P0I-2 Deployment Package (Corrected v2) — Atlas DM Routing Consolidation

**Prepared:** 2026-07-07 19:36:51 +0400
**DEPLOYMENT_READY:** YES — all 5 target scripts confirmed idle
**approval_required:** YES
**production changes:** NONE (package prep only, nothing deployed)

## Predeploy Process Check (final, confirmed clean)

| Script | Status |
|---|---|
| pre_market_report.py | idle — no live process |
| atlas_macro_premarket.py | idle — no live process |
| atlas_intraday.py | idle — no live process (was live PID `96467`, exited between 19:36:15–19:36:45) |
| atlas_macro_postmarket.py | idle — no live process |
| atlas_eod_positions.py | idle — no live process |

`launchctl list \| grep -i com.atlas` — `com.atlas.intraday` shows `-` (not running).

**Re-run this exact check immediately before executing the deploy commands, since idle state can change on the next intraday tick:**

```bash
for f in pre_market_report.py atlas_macro_premarket.py atlas_intraday.py atlas_macro_postmarket.py atlas_eod_positions.py; do
  pgrep -fl "$f" || echo "$f: no live process"
done
launchctl list | grep -i com.atlas
```

## Corrected Pycache / Cache Clear Commands (per-file + macOS system cache path)

```bash
# Per-file script cache removal (local __pycache__, targets only the 5 deployed modules)
rm -f /Users/yasser/scripts/__pycache__/pre_market_report.*.pyc
rm -f /Users/yasser/scripts/__pycache__/atlas_macro_premarket.*.pyc
rm -f /Users/yasser/scripts/__pycache__/atlas_intraday.*.pyc
rm -f /Users/yasser/scripts/__pycache__/atlas_macro_postmarket.*.pyc
rm -f /Users/yasser/scripts/__pycache__/atlas_eod_positions.*.pyc

# macOS system-level Python bytecode cache clear (CommandLineTools Python 3.9 cache dir)
rm -f "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/pre_market_report.cpython-"*.pyc
rm -f "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_macro_premarket.cpython-"*.pyc
rm -f "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_intraday.cpython-"*.pyc
rm -f "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_macro_postmarket.cpython-"*.pyc
rm -f "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_eod_positions.cpython-"*.pyc
```

## Files to Deploy

1. `pre_market_report.py`
2. `atlas_macro_premarket.py`
3. `atlas_intraday.py` (main report send call only)
4. `atlas_macro_postmarket.py`
5. `atlas_eod_positions.py`

## Backup Paths to Create

```
/Users/yasser/scripts/archive/pre_market_report_20260707_193651_p0i2_predeploy.bak.py
/Users/yasser/scripts/archive/atlas_macro_premarket_20260707_193651_p0i2_predeploy.bak.py
/Users/yasser/scripts/archive/atlas_intraday_20260707_193651_p0i2_predeploy.bak.py
/Users/yasser/scripts/archive/atlas_macro_postmarket_20260707_193651_p0i2_predeploy.bak.py
/Users/yasser/scripts/archive/atlas_eod_positions_20260707_193651_p0i2_predeploy.bak.py
```

## Current Production SHA256

| File | SHA256 |
|---|---|
| pre_market_report.py | `0b14e361ec5081545b0f073cebeea22c1d5bddc2ef833f43e81a46ef48725c36` |
| atlas_macro_premarket.py | `4bd95cd14c892393ce8dc7c5d083c1630c44897220c9762a40b915991b58133c` |
| atlas_intraday.py | `00c525f9ba7ff1a54306e52fb02c72502a91f76ed63101d0051144f7fc26a0a8` |
| atlas_macro_postmarket.py | `dd884f872a2bb61fc659037c5aea575a4f7ca172e25d68c8a6be8300f6f79a64` |
| atlas_eod_positions.py | `62cc1b9dabf05931835120741e377b91210c1ee047a39f96b4094fdfbe43b896` |

## Staging SHA256

| File | SHA256 |
|---|---|
| pre_market_report.py | `5ca4a1c4a29860212b147eaaa81146225002463f6f802a3c5b9976a85def4275` |
| atlas_macro_premarket.py | `c8ab2c023c3ca2317148c0b586fe6e97a88b4e702944ef7a87c93aab172c1e9b` |
| atlas_intraday.py | `ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb` |
| atlas_macro_postmarket.py | `0ec35e26f11a73d8d6ef0daf7cd1b8d8d044bb53ebd89cc092e4b7aa781bbdba` |
| atlas_eod_positions.py | `28d2dd2c9868170d5ee5c611bfe66ea29aa88eee7ff0f5e0743605512ed91ed6` |

## Exact Deploy Commands

```bash
# Backups
cp /Users/yasser/scripts/pre_market_report.py /Users/yasser/scripts/archive/pre_market_report_20260707_193651_p0i2_predeploy.bak.py
cp /Users/yasser/scripts/atlas_macro_premarket.py /Users/yasser/scripts/archive/atlas_macro_premarket_20260707_193651_p0i2_predeploy.bak.py
cp /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/archive/atlas_intraday_20260707_193651_p0i2_predeploy.bak.py
cp /Users/yasser/scripts/atlas_macro_postmarket.py /Users/yasser/scripts/archive/atlas_macro_postmarket_20260707_193651_p0i2_predeploy.bak.py
cp /Users/yasser/scripts/atlas_eod_positions.py /Users/yasser/scripts/archive/atlas_eod_positions_20260707_193651_p0i2_predeploy.bak.py

# Deploy
cp /tmp/atlas_p0i2/staging/pre_market_report.py /Users/yasser/scripts/pre_market_report.py
cp /tmp/atlas_p0i2/staging/atlas_macro_premarket.py /Users/yasser/scripts/atlas_macro_premarket.py
cp /tmp/atlas_p0i2/staging/atlas_intraday.py /Users/yasser/scripts/atlas_intraday.py
cp /tmp/atlas_p0i2/staging/atlas_macro_postmarket.py /Users/yasser/scripts/atlas_macro_postmarket.py
cp /tmp/atlas_p0i2/staging/atlas_eod_positions.py /Users/yasser/scripts/atlas_eod_positions.py
```

## Production Compile Command

```bash
python3 -m py_compile \
  /Users/yasser/scripts/pre_market_report.py \
  /Users/yasser/scripts/atlas_macro_premarket.py \
  /Users/yasser/scripts/atlas_intraday.py \
  /Users/yasser/scripts/atlas_macro_postmarket.py \
  /Users/yasser/scripts/atlas_eod_positions.py
```

## Post-Deploy SHA Verify Command

```bash
shasum -a 256 \
  /Users/yasser/scripts/pre_market_report.py \
  /Users/yasser/scripts/atlas_macro_premarket.py \
  /Users/yasser/scripts/atlas_intraday.py \
  /Users/yasser/scripts/atlas_macro_postmarket.py \
  /Users/yasser/scripts/atlas_eod_positions.py
```
Expected: each matches the corresponding **Staging SHA256** value above.

## Rollback Plan

```bash
cp /Users/yasser/scripts/archive/pre_market_report_20260707_193651_p0i2_predeploy.bak.py /Users/yasser/scripts/pre_market_report.py
cp /Users/yasser/scripts/archive/atlas_macro_premarket_20260707_193651_p0i2_predeploy.bak.py /Users/yasser/scripts/atlas_macro_premarket.py
cp /Users/yasser/scripts/archive/atlas_intraday_20260707_193651_p0i2_predeploy.bak.py /Users/yasser/scripts/atlas_intraday.py
cp /Users/yasser/scripts/archive/atlas_macro_postmarket_20260707_193651_p0i2_predeploy.bak.py /Users/yasser/scripts/atlas_macro_postmarket.py
cp /Users/yasser/scripts/archive/atlas_eod_positions_20260707_193651_p0i2_predeploy.bak.py /Users/yasser/scripts/atlas_eod_positions.py

rm -f /Users/yasser/scripts/__pycache__/pre_market_report.*.pyc /Users/yasser/scripts/__pycache__/atlas_macro_premarket.*.pyc /Users/yasser/scripts/__pycache__/atlas_intraday.*.pyc /Users/yasser/scripts/__pycache__/atlas_macro_postmarket.*.pyc /Users/yasser/scripts/__pycache__/atlas_eod_positions.*.pyc
rm -f "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/pre_market_report.cpython-"*.pyc "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_macro_premarket.cpython-"*.pyc "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_intraday.cpython-"*.pyc "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_macro_postmarket.cpython-"*.pyc "/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/atlas_eod_positions.cpython-"*.pyc

python3 -m py_compile /Users/yasser/scripts/pre_market_report.py /Users/yasser/scripts/atlas_macro_premarket.py /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/atlas_macro_postmarket.py /Users/yasser/scripts/atlas_eod_positions.py

shasum -a 256 /Users/yasser/scripts/pre_market_report.py /Users/yasser/scripts/atlas_macro_premarket.py /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/atlas_macro_postmarket.py /Users/yasser/scripts/atlas_eod_positions.py
```
Verify each SHA matches **Current Production SHA256** above.

## Mocked Route Smoke Test Plan (real Telegram sends = 0)

1. Re-import each deployed production module fresh (post cache clear, both local and macOS system cache) with `atlas_notify.send_telegram` / `_send_telegram` monkey-patched to a capture-only stub — no network call, returns `True`.
2. Build the same minimal synthetic `summary`/`ctx` fixtures used in P0I-2 staging validation.
3. Invoke each report's send path once per module against the now-production code.
4. Assert captured `chat_id` resolves via env var **NAME** `TELEGRAM_ADMIN_CHAT_ID` (no value read/printed) for all 5.
5. Assert captured `message_thread_id is None` for all 5.
6. Assert zero real network calls occurred (stub call count == send attempt count).
7. Record pass/fail per report in an evidence table; no DB writes, no live Telegram traffic.

## Summary Status

| Field | Value |
|---|---|
| DEPLOYMENT_READY | YES |
| blocking_processes | NONE — all 5 confirmed idle at 19:36:51+0400 |
| approval_required | YES |
| production changes | NONE |
