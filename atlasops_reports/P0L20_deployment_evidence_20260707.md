# P0L-20 — Production valuation_marks Lot-ID Fix Deployment (Evidence)

**Date:** 2026-07-07 23:05–23:09 +04
**Scope:** PRODUCTION CODE DEPLOYMENT EXECUTED — `atlas_db.py` and
`atlas_intraday.py` replaced with the P0L-18 lot-id fix (real trade-id
resolution + defensive valuation-mark guard). No DB cleanup, no manual DB
writes, no forced trades, no Telegram test sends.

## ⚠️ Transparency note: first attempt rolled back due to a test-script flaw, not a deployment defect

**Attempt 1** ran a 124-second bounded idle poll (waiting for a live
`atlas_intraday.py` cycle still running the **old, unfixed** code to
finish), then successfully backed up, copied, SHA-verified, compiled, and
cleared cache — all correct. However, my own smoke-test script compared the
"bad marks count" measured **before the idle poll started** (6) against the
count measured **after the deploy+smoke sequence** (9), and treated the
increase as a failure. In reality: while the poll was waiting for the
already-running old-code cycle to exit, that cycle finished and legitimately
added 3 *more* bad marks (**using the still-deployed old code**, since the
new files hadn't been copied yet) — timestamped `2026-07-07 19:06:37`,
several seconds before the backup/copy at `19:07:04`. My comparison baseline
was captured at the wrong point in the timeline, so it incorrectly flagged
this as a new-code regression and triggered an automatic rollback (verified
successful — production was restored to the exact P0L-16 baseline SHA).

**Fix applied to the script:** re-captured the bad-marks baseline
*immediately before the file copy* (not before the idle poll), so any
growth attributable to the old code finishing its own cycle is correctly
excluded from the deployment's own pass/fail determination. **Attempt 2**
then ran cleanly with a genuinely idle window (0-second wait) and passed
all checks.

## Attempt 2 (successful) — Pre-deployment checks

| Check | Result |
|---|---|
| Production file SHAs match P0L-19 baseline | **PASS** — both exact match |
| Staged file SHAs match P0L-19 | **PASS** — both exact match |
| Bad `valuation_marks` count confirmed (not deleted) | **9** (grown from 6 due to the old code's last cycle during Attempt 1's wait — expected, not a regression) |

## Idle poll (Attempt 2)

Production was already at a clean idle state at the moment of retry (no
`atlas_intraday.py` process, no lock file) — **0-second wait, 1 poll tick**.

## Backups

| File | Backup path | SHA | Matches baseline |
|---|---|---|---|
| `atlas_db.py` | `/Users/yasser/scripts/archive/atlas_db.py_20260707_190931_p0l20_predeploy.bak.py` | `93cdb28d98d6879d1fd6d13e043af8b4609c1427a4d586620981edc301345a85` | ✅ |
| `atlas_intraday.py` | `/Users/yasser/scripts/archive/atlas_intraday.py_20260707_190931_p0l20_predeploy.bak.py` | `49e30aff620140df218dc515cc77b0e4b97fa99a5c517dad7f27946b5fc768d8` | ✅ |

(Attempt 1's backups at `..._190704_...` also exist and are equally valid
pre-fix-baseline backups, left in place as an additional rollback option.)

## Deployed file SHAs

| File | Deployed SHA | Matches staged |
|---|---|---|
| `atlas_db.py` | `518278bf7c5309b34d14c24354f10828cbaa963ce21ea625d6d9988f33111830` | ✅ |
| `atlas_intraday.py` | `f87071d3aa48741ec89618fc1c2fe19c684bb7906ac58861193be101eb966c29` | ✅ |

Independently re-verified via direct `sha256sum` on the live production
files after the script exited — identical.

## Compile result

Both files: `py_compile` → **OK** (inside the deployment script and
independently re-checked afterward directly against the live production
files).

## Pycache cleared

**YES.** 2 `com.apple.python` cache entries removed (only 2 remained since
Attempt 1's rollback-and-recopy cycle had already triggered most of the
cleanup once; a fresh recompile after the second copy caught the remainder).

## Smoke tests (zero production DB writes)

| Test | Result |
|---|---|
| `import atlas_db` | **PASS** |
| Helper symbol checks | **PASS** — all 5 present |
| Source check: no loop-index fallback | **PASS** — `enumerate(rows` absent from `_open_trades()`; `real_id_by_ticker` resolution via `get_trades(status='OPEN')` present; sentinel `-1` fallback present |
| Source check: valuation guard | **PASS** — literal clause `AND UPPER(ticker)=? AND status='OPEN'` present in `_dualwrite_valuation_mark()`; `valuation_mark_lot_mismatch` WARN logging present |
| Protected files untouched | **PASS** — `atlas_db.py`=0 refs, `atlas_intraday.py`=3 refs, byte-identical via `diff` |
| Bad marks still untouched (by this deployment) | **YES** — 9 before copy, 9 after smoke — zero change caused by this task |

**Production DB written during smoke: NO.** Legacy `trades`=70,
`cash_ledger`=21 confirmed unchanged throughout.

## Independent post-hoc verification (direct, outside the script)

- Production `atlas_db.py`/`atlas_intraday.py` SHAs: confirmed identical to the deployed/staged SHAs.
- `python3 -m py_compile` on the live production files: **OK**.
- `grep -c "enumerate(rows" atlas_intraday.py` → **0** (confirmed absent).
- `grep -c "AND UPPER(ticker)=? AND status='OPEN'" atlas_db.py` → **1** (confirmed present).
- `valuation_marks` count: **9**, unchanged by this deployment (no cleanup performed, as scoped).

## Rollback command (available, not needed for the final state)

```
cp /Users/yasser/scripts/archive/atlas_db.py_20260707_190931_p0l20_predeploy.bak.py /Users/yasser/scripts/atlas_db.py
cp /Users/yasser/scripts/archive/atlas_intraday.py_20260707_190931_p0l20_predeploy.bak.py /Users/yasser/scripts/atlas_intraday.py
sha256sum /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_intraday.py
# must equal 93cdb28d98d6879d1fd6d13e043af8b4609c1427a4d586620981edc301345a85 and 49e30aff620140df218dc515cc77b0e4b97fa99a5c517dad7f27946b5fc768d8 respectively
python3 -m py_compile /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_intraday.py
```

## Expected next live effect

The next scheduled `com.atlas.intraday` cycle runs with the P0L-18 lot-id
fix live:
- `_open_trades()` resolves REAL `trades.id` per ticker via
  `get_trades(status='OPEN')` instead of the removed loop-index fallback.
- `_cache_open_trade_prices()` → `_dualwrite_valuation_mark()` only attaches
  new `valuation_marks` rows to a `position_lots` row matching
  `legacy_trades_id` AND `ticker` AND `status='OPEN'` together.
- **Expected:** up to 4 new correctly-attributed marks for SYNA(18)→lot 63,
  RL(42)→lot 64, BAC(47)→lot 65, ABNB(48)→lot 66.
- **Zero** new marks should attach to the AAPL/PBXT/IBXT closed backfilled
  lots (53/54/55).
- The 9 existing bad marks from before this fix remain in the table
  untouched — cleanup is a separate deferred task, not part of this
  deployment.
- No change to `trades`, `cash_ledger`, Telegram delivery, TFE, stops,
  targets, or exits.

## Conclusion

Deployment completed successfully on the second attempt. The first
attempt's rollback was caused by a flaw in my own verification script's
baseline-timing logic (comparing against a stale pre-poll snapshot instead
of an immediately-pre-copy snapshot), not by any defect in the P0L-18 fix
itself or the deployment mechanics — disclosed transparently above rather
than omitted. The corrected script then deployed cleanly with a genuinely
idle window, all 5 smoke tests passing, deployed SHAs matching staged
exactly, and zero unintended production DB writes. A recommended follow-up
observation task (reading the next live cycle's `valuation_marks` output)
would confirm the fix's real-world effect, mirroring the P0L-17 pattern.
