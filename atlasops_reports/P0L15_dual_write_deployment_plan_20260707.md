# P0L-15 — Production Dual-Write Code Deployment PLAN (Evidence)

**Date:** 2026-07-07 22:30 +04
**Scope:** PLANNING ONLY. No execution. No production file edit. No
production DB write. No deploy. This document is the plan for Prof's
review and explicit authorization before any execution step is taken.

## 1. Production bookkeeping row counts (confirmed current)

| Table | Rows |
|---|---|
| `portfolio_event_journal` | 85 |
| `position_lots` | 67 |
| `ledger_postings` | 49 |
| `evidence_attachments` | 1 |
| `invariant_checks` | 13 |
| `valuation_marks` | 0 |
| `broker_reconciliation` | 0 |
| `report_snapshots` | 0 |

Matches the P0L-14 backfill result exactly — no drift since backfill.

## 2. Production file SHA baseline (confirmed current)

| File | SHA256 |
|---|---|
| `atlas_db.py` | `c9f79d7a51ab26862f3f979ec53227324721802d088196cd646939c42f830c55` |
| `atlas_intraday.py` | `ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb` |

These match the baseline captured at the start of P0L-9 — production code
has not changed since staging began. This is the pre-deploy rollback
anchor.

## 3. Staged file SHA (confirmed current, post-P0L-10 hardening)

| File | SHA256 |
|---|---|
| `/tmp/p0l9/src/atlas_db.py` | `93cdb28d98d6879d1fd6d13e043af8b4609c1427a4d586620981edc301345a85` |
| `/tmp/p0l9/src/atlas_intraday.py` | `49e30aff620140df218dc515cc77b0e4b97fa99a5c517dad7f27946b5fc768d8` |

Both files: `python3 -m py_compile` → **PASS** (verified again just now,
fresh, not relying on the earlier P0L-10 result).

## 4. Backup + SHA verification plan

1. `BACKUP_TAG=$(date -u +%Y%m%d_%H%M%S)_p0l15_predeploy`
2. `cp /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/archive/atlas_db.py_${BACKUP_TAG}.bak.py`
3. `cp /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/archive/atlas_intraday.py_${BACKUP_TAG}.bak.py`
4. `sha256sum` both backups, confirm each matches the corresponding production baseline SHA in §2 exactly, before touching either production file.
5. Archive directory confirmed writable (`drwxr-xr-x`, owner `yasser`).

## 5. Deployment method (planned, not executed)

1. `cp /tmp/p0l9/src/atlas_db.py /Users/yasser/scripts/atlas_db.py`
2. `cp /tmp/p0l9/src/atlas_intraday.py /Users/yasser/scripts/atlas_intraday.py`
3. `sha256sum` both production files — confirm each now matches the staged SHA in §3 exactly.
4. `python3 -m py_compile /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_intraday.py` — expect clean PASS on the production copies too (same content as staged, already proven to compile).
5. Clear stale bytecode caches: remove `/Users/yasser/scripts/__pycache__/atlas_db*.pyc` and `__pycache__/atlas_intraday*.pyc` (both standard `__pycache__` and, per prior P0I-2 lesson, any macOS `com.apple.python` cache paths if present) so no already-running or next-launched process can load stale compiled bytecode instead of the new source.

## 6. Idle-window execution plan

**Current live state (checked at plan time):** `atlas_intraday.py` **is
currently running** — PID `14875`, lock file `/tmp/atlas_intraday.lock`
present (created 22:30). This is a live blocker exactly like the one
encountered in the first P0L-14 attempt.

**Planned execution sequence, to be run only under explicit authorization:**
1. Confirm via `pgrep -fl atlas_intraday.py` that no process is running.
2. Confirm `/tmp/atlas_intraday.lock` is absent, or present but stale (age > ~500s, safely past the observed 398–466s max runtime).
3. If either check fails, **abort** — do not proceed through contention. Retry with a bounded poll (matching the P0L-14 retry pattern: up to 12 minutes, 5-second interval) if the window is requested to wait rather than fail immediately.
4. Once idle is confirmed, immediately execute the backup (§4) and the file copy (§5) back-to-back with minimal elapsed time between the idle check and the write, to minimize the chance of a new cycle starting mid-deployment (same lesson learned from the P0L-12 timing-gap disclosure).
5. Re-check `pgrep -fl atlas_intraday.py` immediately after the copy — if a process appears to have started during the copy window, this is now a **live production code file** mid-write risk (unlike P0L-12's DDL-only risk); if this happens, proceed to rollback immediately (§8) rather than leaving mixed-version files in place, since a partially-applied `cp` could theoretically leave a truncated file if the OS-level write were interrupted (extremely unlikely for a `cp` of a ~40KB/100KB file, but the safest posture is to treat any process-appearance-during-copy as a trigger for an immediate rollback-and-retry rather than "wait and see").

## 7. Post-deploy smoke test plan (no forced trades, no unscoped DB writes)

All smoke tests operate on **read-only imports and attribute checks** of the
newly-deployed production files, or on a **freshly copied DB** — never on
live production DB rows — per the explicit constraint that no DB writes may
occur during this plan/smoke unless truly unavoidable, in which case they
must target a copy.

1. **Import check:** `python3 -c "import atlas_db"` from `/Users/yasser/scripts` — must succeed with no `ImportError`/`SyntaxError`. Confirms the deployed file loads cleanly in the real production environment (not just `py_compile`, which only checks syntax).
2. **`get_connection()` PRAGMA behavior:** call `atlas_db.get_connection()` against a **fresh copy** of production `atlas.db` (e.g. `/tmp/p0l15_smoke/atlas_copy.db`) and query `PRAGMA foreign_keys;` on the returned connection — expect `1` (ON), confirming the P0L-9 `get_connection()` change is live. This never touches the real production DB file.
3. **Dual-write helper symbols exist:** `hasattr(atlas_db, "_bk_safe")`, `hasattr(atlas_db, "_dualwrite_buy_fill")`, `hasattr(atlas_db, "_dualwrite_sell_fill")`, `hasattr(atlas_db, "record_manual_cash_correction")`, `hasattr(atlas_db, "_dualwrite_valuation_mark")` — all must be `True`. Pure attribute checks, no execution, no DB access.
4. **Report-snapshot helper does not send Telegram:** static-inspect (via `inspect.getsource()` or an AST scan) the `_bk_emit_report_snapshot` closure inside `atlas_intraday.py`'s main flow to confirm it contains no call to `send_telegram` or any Telegram-related symbol — purely a source-text/AST check, no live send attempted, no scheduler triggered.
5. **Protected-file untouched re-verification (post-deploy):** re-run the exact §protected-files check against the now-deployed production files — `grep -c "atlas_engine\|atlas_portfolio"` on the deployed `atlas_db.py` (expect 0) and `atlas_intraday.py` (expect 3, byte-identical to the pre-deploy 3 via `diff` against the backup made in §4).
6. None of the above 5 steps write to the real production `atlas.db`, invoke `atlas_manage.run()`, call `confirm_trade_fill()`/`close_trade_broker_confirmed()` against production, or trigger any Telegram send.

## 8. Rollback plan

1. `cp /Users/yasser/scripts/archive/atlas_db.py_${BACKUP_TAG}.bak.py /Users/yasser/scripts/atlas_db.py`
2. `cp /Users/yasser/scripts/archive/atlas_intraday.py_${BACKUP_TAG}.bak.py /Users/yasser/scripts/atlas_intraday.py`
3. `sha256sum` both restored files — confirm each matches the pre-deploy baseline SHA in §2 exactly.
4. `python3 -m py_compile` both restored files — confirm clean pass.
5. Clear `__pycache__` again (same paths as §5 step 5) so no stale post-rollback bytecode lingers.
6. No DB rollback needed for this specific deployment step — code deployment alone does not write any DB row; the DB backfill (P0L-14) is already complete and independent of this code deployment's success or failure.

## 9. DB-write constraint compliance

This entire plan, and the smoke-test plan in §7, perform **zero** writes to
the real production `atlas.db`. The one smoke test that touches a database
connection at all (§7.2) explicitly uses a **fresh copy**
(`/tmp/p0l15_smoke/atlas_copy.db`), never the production file, satisfying
the "if a smoke test needs DB writes, it must use copied DB only" constraint
verbatim (and in fact that specific check doesn't even need to write — a
`PRAGMA` read is sufficient).

## Risks

| Risk | Assessment |
|---|---|
| Lock contention with a live `com.atlas.intraday` write cycle | **Confirmed currently present** — PID 14875 running at plan time. Mitigated by the idle-check-immediately-before-copy + bounded-poll-retry pattern already proven in P0L-14's retry. |
| Stale `__pycache__`/`com.apple.python` cache causing the next scheduled run to execute old code despite the file being updated | LOW — mitigated by explicit cache-clear step in §5.5, matching the exact lesson learned and hardened during P0I-2's deployment. |
| A process starting mid-`cp` leaving a corrupted/partial file | Very LOW for files this size, but explicitly treated as an immediate-rollback trigger rather than "wait and see," per §6.5. |
| Protected-file exposure | NIL — re-verified now (§ protected-files check) at 0/0 for `atlas_engine`/`atlas_portfolio` in `atlas_db.py`, and the 3 pre-existing `atlas_portfolio` references in `atlas_intraday.py` are confirmed byte-identical between production and staged via `diff`. |
| Behavioral regression to legacy trade/cash logic | Very LOW — the P0L-9/P0L-10 staged diffs only *append* code after each existing legacy `commit()`/`close()` call; the legacy `UPDATE`/`INSERT` statements themselves are byte-identical to production in the diff. 14/14 synthetic tests already proved this against a copied DB, including the "forced bookkeeping failure does not block legacy write" case. |

## Conclusion

All preconditions for deployment are confirmed and ready: production
bookkeeping row counts match the P0L-14 backfill exactly, production file
SHAs match the untouched pre-staging baseline, staged files are fresh-
compile-clean, and protected files are confirmed untouched in both the
staged diff and a fresh production comparison. The only live blocker at
plan time is a currently-running `atlas_intraday.py` cycle (PID 14875) —
execution must wait for a confirmed idle window per §6, using the same
bounded-poll pattern already proven in the P0L-14 retry.

**This plan requires Prof's explicit authorization before any execution
step is run.**
