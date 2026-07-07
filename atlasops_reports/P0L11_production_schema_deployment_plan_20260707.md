# P0L-11 — Production Additive Schema Deployment PLAN (Evidence)

**Date:** 2026-07-07 22:16 +04
**Scope:** PLANNING ONLY. No execution. No production DB write. No code
patch. No deploy. This document is the plan to be reviewed and explicitly
authorized by Prof before any production action is taken.

## 1. Production schema — current state (confirmed live)

```
sqlite3 /Users/yasser/scripts/atlas.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
```
Returns exactly 8 tables: `account`, `cash_ledger`, `ema_retry_candidates`,
`handoff`, `pending_pullbacks`, `signals`, `sqlite_sequence`, `trades`.

**Confirmed: none of the 8 bookkeeping tables exist in production.**
Checked individually — `portfolio_event_journal`, `position_lots`,
`ledger_postings`, `valuation_marks`, `broker_reconciliation`,
`report_snapshots`, `evidence_attachments`, `invariant_checks` all return
`exists=0`.

Current production row counts: `trades`=70, `cash_ledger`=21, `account`=1,
`signals`=26504, `handoff`=13, `pending_pullbacks`=50,
`ema_retry_candidates`=0.

Production `atlas.db` SHA256 at plan time: `b5c5408243a7fe21dea009d9739f90e44522f34409d9d6e8cb75ccfcddc6791d`
(will differ at execution time due to normal live `signals` growth — this is
expected and does not indicate any bookkeeping-relevant change).

## 2. Approved DDL

**File:** `/tmp/p0l6/p0l6_revised_ddl.sql`
**SHA256:** `7719cadc0cb5560ff5b45826c2d62fd0df73aca57174ac36b2a006f009b4e0a4`
**Lines:** 238

This is the P0L-6 revision (event_type `ACCOUNT_OPENED` +
posting_kind `MANUAL_ADJUSTMENT`/`OPENING_BALANCE` added to the P0L-4
baseline), which was:
- Applied and integrity-verified against `/tmp/p0l6/atlas_copy_p0l6.db` (P0L-6)
- Re-applied and used successfully for the full P0L-7 backfill against
  `/tmp/p0l7/atlas_copy_p0l7.db` (85 events, 67 lots, 49 postings, all
  balanced, 0 FK violations)
- Re-applied again for P0L-9/P0L-10 dual-write staging and passed all 14
  synthetic tests against `/tmp/p0l9/atlas_copy_p0l9.db`

This is the single DDL file that has been exercised across 4 separate
staging passes without a single integrity or FK failure. It contains **only**
`CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements — a
`grep` confirms **zero** `ALTER`, `DROP`, `UPDATE`, `DELETE`, or `INSERT`
statements anywhere in the file (verified below in §5).

## 3. Backup + SHA plan

1. `BACKUP_TAG=$(date -u +%Y%m%d_%H%M%S)_p0l11_predeploy`
2. `cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/archive/atlas_db_${BACKUP_TAG}.bak.db`
3. Immediately: `sha256sum /Users/yasser/scripts/atlas.db /Users/yasser/scripts/archive/atlas_db_${BACKUP_TAG}.bak.db` — the two hashes **must match exactly** before proceeding. If they don't match, abort (means the DB changed between copy start and finish, e.g. a live write landed mid-copy — extremely unlikely for a `cp` of a file this size but checked anyway).
4. Record this pre-deploy SHA as the rollback-verification anchor.

## 4. SQLite lock-safe execution plan

**Current live state (checked at plan time):** `atlas_intraday.py` **was
running** at 22:16 — PID `12939`, `com.atlas.intraday` launchd label active,
lock file `/tmp/atlas_intraday.lock` present (created 22:10). **As of this
writing the process has since completed** (`pgrep -fl atlas_intraday.py`
now returns no match) — confirming the ~398–466s runtime estimate and
giving a real, currently-open idle window. This window will be re-verified
live immediately before execution regardless, since idle state can change
at any moment up to the next 10-minute tick.

Execution must NOT run concurrently with a live intraday write cycle,
because:
- SQLite uses file-level locking; a `CREATE TABLE` DDL statement takes a
  write lock on the whole database file. If `atlas_intraday.py` is mid-write
  (e.g. `_append_cash_ledger`, `_cache_open_trade_prices`), the DDL apply
  will either block (risking a timeout on both sides) or, if it acquires the
  lock first, could stall the live trading cycle's own writes.
- The DDL itself is purely additive and structurally safe (no risk *to
  existing data*), but a lock collision risks an operational stall or error
  in the live pipeline — an availability risk, not a data-safety risk.

**Execution steps (planned, not run):**
1. Confirm via `pgrep -fl atlas_intraday.py` and `launchctl list | grep com.atlas.intraday` that no intraday process is currently running.
2. Confirm `/tmp/atlas_intraday.lock` is absent or stale (mtime older than one full cycle interval).
3. Immediately execute the backup (§3).
4. Immediately execute `sqlite3 /Users/yasser/scripts/atlas.db < /tmp/p0l6/p0l6_revised_ddl.sql` — a single, fast (sub-second for pure `CREATE TABLE`/`CREATE INDEX` DDL) transaction.
5. Immediately re-check `pgrep -fl atlas_intraday.py` to confirm no intraday cycle started *during* the DDL apply (the whole window should be well under 10 seconds, minimizing the chance of a race against the next 10-minute tick).
6. If a live process is detected running at any point in steps 1–5, abort and reschedule — do not force through a lock contention.

## 5. DDL-only guarantee (verified now, ahead of authorization)

```
grep -Ei "ALTER |DROP |UPDATE |DELETE |INSERT " /tmp/p0l6/p0l6_revised_ddl.sql
```
Result: 2 matches, both **comments only** (not executable SQL):
- Line 3: `-- Additive only. Does NOT alter or drop any existing table...`
- Line 213: `-- ...A future ENFORCE-mode option is an AFTER INSERT trigger on...`

**Zero actual `ALTER`/`DROP`/`UPDATE`/`DELETE`/`INSERT` statements** — confirmed
the file contains only additive `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX
IF NOT EXISTS` statements, no row inserts, no existing-table mutation, and
(obviously) no code files are touched by this plan at all.

## 6. Deployment window recommendation

**Best window:** the **next confirmed idle gap between two `com.atlas.intraday`
10-minute ticks**, verified live immediately before execution (not
pre-scheduled), using the same bounded-watch-loop pattern already proven
successful for P0I-2 (2-second poll interval, abort-and-retry if a process
starts mid-window). Given the DDL apply itself takes well under a second,
a single confirmed idle poll immediately before running is sufficient — no
need for the full 30-minute watch loop used for the larger P0I-2 code
deploy, since this operation is much shorter than one intraday cycle.

**Avoid:** the ~7-minute pre-tick window before the next scheduled intraday
run (established standing caution from prior P0-series work), and avoid
initiating during an active `atlas_perme.py` run if one is concurrently
scheduled (currently confirmed not running).

## 7. Rollback plan

- If the DDL apply itself fails partway (unlikely — SQLite DDL statements
  are individually atomic, and none of these 8 `CREATE TABLE` statements
  depend on each other completing first except via `FOREIGN KEY` references,
  which SQLite defers until `PRAGMA foreign_keys=ON` is actually set on a
  connection, not at DDL-apply time) — restore from the archive backup made
  in §3: `cp /Users/yasser/scripts/archive/atlas_db_${BACKUP_TAG}.bak.db /Users/yasser/scripts/atlas.db`, then re-verify SHA matches the pre-deploy anchor.
- If the DDL apply succeeds but post-deploy verification (§8) finds any
  unexpected discrepancy in the 7 pre-existing tables (this should be
  structurally impossible given the file contains zero ALTER/DROP/UPDATE/
  DELETE/INSERT statements, but verified anyway) — same restore procedure.
- Because the new tables are additive and currently unused by any running
  code (no dual-write patch has been deployed to production — P0L-9/P0L-10
  remain staging-only), a rollback of *just the schema* by dropping the 8
  new tables (`DROP TABLE IF EXISTS ...` for each) is also a safe,
  lower-impact alternative to a full DB file restore, since it cannot affect
  the 7 pre-existing tables either. Full-file restore remains the primary
  plan; table-drop is the documented fallback if a full restore is
  operationally inconvenient (e.g., mid-cycle).

## 8. Verification plan (to run immediately after DDL apply)

1. `sqlite3 atlas.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"` — expect the original 8 tables **plus** the 8 new bookkeeping tables (16 total, plus `sqlite_sequence` already counted).
2. For each of the 8 new tables: `SELECT COUNT(*) FROM <table>;` — expect **0** for every one (no backfill has been authorized or run against production).
3. For each of the 7 pre-existing tables (`account`, `cash_ledger`, `ema_retry_candidates`, `handoff`, `pending_pullbacks`, `signals`, `trades`): re-run the exact row-count query from §1 and diff against the pre-deploy baseline. Expect all counts **unchanged**, except `signals` which may show normal growth if a live intraday cycle ran between backup and verification (this is expected and not a defect — same documented pattern from every prior P0L pass).
4. `PRAGMA integrity_check;` — expect `ok`.
5. `PRAGMA foreign_key_check;` — expect zero rows (no violations). Note this
   requires a fresh connection with `PRAGMA foreign_keys=ON` set, matching
   how the P0L-9 staged `get_connection()` change will eventually set it —
   but is checkable manually via the CLI regardless of application code.
6. Compare `sha256sum` of the post-deploy `atlas.db` against the backup made
   in §3 — they will **legitimately differ** (schema changed), so this SHA
   is recorded as the new "post-P0L-11" baseline anchor for future tasks,
   not compared for equality.
7. Report table list before/after, all 8 new-table row counts, all 7
   existing-table row-count deltas, integrity_check result, foreign_key_check
   result, and backup path/SHA to Prof.

## Risks

| Risk | Assessment |
|---|---|
| Lock contention with a live `com.atlas.intraday` write | LOW-MEDIUM if executed without checking; **mitigated to near-zero** by the idle-poll-immediately-before-execution step in §4/§6 |
| Partial DDL application (some tables created, then a failure) | LOW — each `CREATE TABLE IF NOT EXISTS` is independently idempotent; a rerun of the same DDL file after a partial failure is safe and will simply skip already-created tables |
| Unexpected FK reference failure at apply time | LOW — the DDL has already been applied cleanly across 4 separate staging copies of this exact production DB with zero FK violations each time |
| Accidental impact to existing tables | Effectively NIL — the DDL file has been grepped and contains zero `ALTER`/`DROP`/`UPDATE`/`DELETE`/`INSERT` statements; verified in §5 |
| Someone runs the P0L-9/10 staged code changes against production before this schema exists | N/A to this plan — those code changes remain staging-only and out of scope for this deployment; flagged here only as an ordering dependency: schema deployment (P0L-11) is a prerequisite for any future dual-write code deployment, not the reverse |

## Conclusion

Production currently lacks all 8 bookkeeping tables. The P0L-6 DDL is fully
staging-proven across 4 independent passes (P0L-6, P0L-7, P0L-9, P0L-10),
contains zero destructive statements, and the execution plan is a single
sub-second additive transaction guarded by a live idle-check immediately
before running. Rollback is a straightforward backup restore (or, as a
lighter-weight fallback, dropping just the 8 new tables). No backfill, no
code change, and no existing-table mutation are part of this deployment.

**This plan requires Prof's explicit authorization before any execution
step is run.**
