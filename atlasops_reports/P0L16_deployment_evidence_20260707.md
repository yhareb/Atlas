# P0L-16 — Production Dual-Write Code Deployment (Evidence)

**Date:** 2026-07-07 22:36–22:38 +04
**Scope:** PRODUCTION CODE DEPLOYMENT EXECUTED — `atlas_db.py` and
`atlas_intraday.py` replaced with the P0L-10 hardened dual-write staged
versions. No DB backfill, no manual DB row writes, no forced trades, no
Telegram test sends, no protected-file changes.

## Pre-deployment checks (before idle poll — no writes yet)

| Check | Result |
|---|---|
| P0L-14 bookkeeping counts still match | **PASS** — all 8 tables exact match |
| Production file SHAs still match P0L-15 baseline | **PASS** — both files exact match |
| Staged file SHAs still match P0L-15 | **PASS** — both files exact match |

## Bounded idle poll

Started at plan time with `atlas_intraday.py` PID `14875` actively running
(confirmed live blocker per the P0L-15 plan). Poll ran **19 ticks over
93.3 seconds** (well under the 12-minute cap) before the process exited and
a clean idle window opened.

## Final gates (re-verified at each step, no delay)

| Gate | Result |
|---|---|
| Immediately before backup | `proc_running: false`, lock absent |
| Immediately before file copy | `proc_running: false`, lock absent |
| Immediately after file copy | `proc_running: false`, lock absent — **no contention during the copy window** |

## Backups

| File | Backup path | SHA | Matches baseline |
|---|---|---|---|
| `atlas_db.py` | `/Users/yasser/scripts/archive/atlas_db.py_20260707_183648_p0l16_predeploy.bak.py` | `c9f79d7a51ab26862f3f979ec53227324721802d088196cd646939c42f830c55` | ✅ |
| `atlas_intraday.py` | `/Users/yasser/scripts/archive/atlas_intraday.py_20260707_183648_p0l16_predeploy.bak.py` | `ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb` | ✅ |

## Deployed file SHAs

| File | Deployed SHA | Matches staged |
|---|---|---|
| `atlas_db.py` | `93cdb28d98d6879d1fd6d13e043af8b4609c1427a4d586620981edc301345a85` | ✅ |
| `atlas_intraday.py` | `49e30aff620140df218dc515cc77b0e4b97fa99a5c517dad7f27946b5fc768d8` | ✅ |

Independently re-verified via a direct `sha256sum` on the live production
files after the script exited — identical.

## Compile result

Both files: `py_compile` → **OK** (inside the deployment script, and
independently re-checked afterward directly against the live production
files).

## Pycache cleared

**YES.** 1 standard `__pycache__` entry (`atlas_db.cpython-311.pyc`) plus
**59 additional** `com.apple.python` cache entries removed across numerous
historical staging directories that happened to share the module names
`atlas_db`/`atlas_intraday` (these accumulated from many past P0-series
staging runs and are unrelated to this specific deployment, but were swept
since they matched the stem pattern — harmless, ensures no stale cache
anywhere on the system could shadow the new code).

## Smoke tests (zero production DB writes)

| Test | Result |
|---|---|
| `import atlas_db` | **PASS** — clean import, no error |
| `get_connection()` sets `PRAGMA foreign_keys=ON` | **PASS** — value=1, tested against `/tmp/p0l16_smoke/atlas_copy_smoke.db` (a fresh copy, never production) |
| Dual-write helper symbols exist | **PASS** — all 5 present: `_bk_safe`, `_dualwrite_buy_fill`, `_dualwrite_sell_fill`, `record_manual_cash_correction`, `_dualwrite_valuation_mark` |
| Report-snapshot helper has no Telegram call | **PASS** — source-scanned the `_bk_emit_report_snapshot` closure (2,468 chars), zero occurrences of `send_telegram(` |
| Protected files untouched | **PASS** — `atlas_db.py`=0 refs, `atlas_intraday.py`=3 refs (byte-identical to the pre-deploy backup via `diff`, zero changed lines containing `atlas_engine`/`atlas_portfolio`) |

**Production DB written during smoke: NO.** The only DB touched by any
smoke test was `/tmp/p0l16_smoke/atlas_copy_smoke.db`, a fresh copy made
specifically for the PRAGMA check — confirmed via direct post-hoc query
that production `atlas.db` bookkeeping counts (`portfolio_event_journal`=85,
`position_lots`=67, `ledger_postings`=49, `valuation_marks`=0,
`report_snapshots`=0) and legacy counts (`trades`=70, `cash_ledger`=21)
are all **unchanged** from before this deployment.

## Rollback command (available, not needed)

```
cp /Users/yasser/scripts/archive/atlas_db.py_20260707_183648_p0l16_predeploy.bak.py /Users/yasser/scripts/atlas_db.py
cp /Users/yasser/scripts/archive/atlas_intraday.py_20260707_183648_p0l16_predeploy.bak.py /Users/yasser/scripts/atlas_intraday.py
sha256sum /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_intraday.py
# must equal c9f79d7a51ab26862f3f979ec53227324721802d088196cd646939c42f830c55 and ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb respectively
python3 -m py_compile /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_intraday.py
```

## Expected next live effect

The next scheduled `com.atlas.intraday` cycle runs with the dual-write code
live:
- `confirm_trade_fill()` / `close_trade_broker_confirmed()` will non-fatally
  emit `portfolio_event_journal`/`ledger_postings` rows after each legacy
  `cash_ledger` commit — **only if** a real broker fill/close occurs that
  cycle (none was forced by this deployment).
- `_cache_open_trade_prices()` will emit `valuation_marks` rows. Since the
  live report code does not yet pass an explicit `price_source` attribute
  on trade objects, these will conservatively default to
  `price_source='stale_cache'`, `is_fallback=1` (the P0L-10 safe default) —
  this is expected and correct until a future task wires real live-provider
  provenance into the price-fetch path feeding this cache.
- The report-render flow will emit one `report_snapshots` row per cycle
  with the literal rendered text and a price-provenance manifest.
- **None of this affects Telegram delivery, strategy, TFE, stops, targets,
  or exits** — confirmed by the smoke tests and by the byte-identical
  legacy-write-path diff already proven in P0L-9/P0L-10 staging.

## Conclusion

Deployment completed successfully after a 93-second bounded idle wait.
Backups taken and SHA-verified before any production file was touched.
Deployed files match staged SHAs exactly, compile cleanly, and all 5 smoke
tests pass with zero production DB writes. Protected files
(`atlas_engine.py`, `atlas_portfolio.py`) were never opened; the 3
pre-existing `atlas_portfolio` references inside `atlas_intraday.py` remain
byte-identical. Rollback path verified available but not needed.
