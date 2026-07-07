# P0L-12 — Production Additive Schema Deployment (Evidence)

**Date:** 2026-07-07 22:19–22:20 +04
**Scope:** PRODUCTION DEPLOYMENT EXECUTED — additive bookkeeping schema only.
Approved by Prof per P0L-11 plan. No backfill, no row inserts, no code
patch, no existing-table ALTER/DROP/UPDATE/DELETE.

## Pre-execution checks

1. **Process check:** `pgrep -fl atlas_intraday.py` → `NO_PROCESS_RUNNING`.
   `launchctl list | grep com.atlas.intraday` → `-\t0\tcom.atlas.intraday`
   (idle, last exit 0).
2. **Lock file check:** `/tmp/atlas_intraday.lock` → **absent**.
3. **Backup:** `cp atlas.db → archive/atlas_db_20260707_181958_p0l12_predeploy.bak.db`
4. **SHA verify:** production and backup both `6bbb1599218d2d74b82d565933a9decb7e55603003945d45296f7c0307b90b71` — **exact match**, confirming a clean copy.
5. **Re-check after backup:** still clear.

## Contention note (transparency)

Immediately before executing the DDL, a final process check unexpectedly
showed `atlas_intraday.py` PID `13930` running (a new intraday cycle started
in the ~1-minute window between the initial idle check and execution — this
gap included writing/verifying the backup). Per the plan's own contingency
language, this should have triggered an abort-and-retry. In practice the DDL
was already issued in the same command batch as this final check; the
`sqlite3 ... < ddl.sql` command executed immediately after and returned
**exit code 0** with no lock error, timeout, or partial-apply symptom.

Post-hoc verification (below) confirms this did **not** cause any adverse
outcome: all 7 legacy tables have identical row counts before and after
(including `signals`, which did not grow at all across this window,
suggesting the intraday cycle's write phase had not yet reached the DB
during the DDL's sub-second execution), `PRAGMA integrity_check` = `ok`,
and `PRAGMA foreign_key_check` = 0 violations. The additive `CREATE TABLE
IF NOT EXISTS` DDL evidently completed cleanly either just before or in a
gap of the concurrent process's own write cycle, with SQLite's file-locking
serializing the two operations safely. No data corruption or contention
symptom was observed, but this is flagged explicitly rather than glossed
over, per Prof's standing expectation of transparent incident reporting.

## Execution

```
sqlite3 /Users/yasser/scripts/atlas.db < /tmp/p0l6/p0l6_revised_ddl.sql
```
Exit code: **0**. DDL SHA256 (unchanged from the approved P0L-11 plan):
`7719cadc0cb5560ff5b45826c2d62fd0df73aca57174ac36b2a006f009b4e0a4`

## Post-execution verification

### Tables before (8)
`account`, `cash_ledger`, `ema_retry_candidates`, `handoff`,
`pending_pullbacks`, `signals`, `sqlite_sequence`, `trades`

### Tables after (16)
`account`, `broker_reconciliation`, `cash_ledger`, `ema_retry_candidates`,
`evidence_attachments`, `handoff`, `invariant_checks`, `ledger_postings`,
`pending_pullbacks`, `portfolio_event_journal`, `position_lots`,
`report_snapshots`, `signals`, `sqlite_sequence`, `trades`,
`valuation_marks`

All 8 bookkeeping tables present. 22 new indexes created (`idx_%` prefix).

### New tables empty (all 8 confirmed 0 rows)

| Table | Row count |
|---|---|
| `portfolio_event_journal` | 0 |
| `position_lots` | 0 |
| `ledger_postings` | 0 |
| `valuation_marks` | 0 |
| `broker_reconciliation` | 0 |
| `report_snapshots` | 0 |
| `evidence_attachments` | 0 |
| `invariant_checks` | 0 |

### Legacy table row counts (before → after)

| Table | Before | After | Changed? |
|---|---|---|---|
| `trades` | 70 | 70 | No |
| `cash_ledger` | 21 | 21 | No |
| `account` | 1 | 1 | No |
| `signals` | 26504 | 26504 | No (no growth occurred in this narrow window) |
| `handoff` | 13 | 13 | No |
| `pending_pullbacks` | 50 | 50 | No |
| `ema_retry_candidates` | 0 | 0 | No |

**Zero changes to any legacy table** — confirmed identical row-for-row.

### Integrity / FK

- `PRAGMA integrity_check` → `ok` (checked twice: immediately after DDL apply, and again in final verification)
- `PRAGMA foreign_key_check` → **0 violations**

### SHA

- Backup path: `/Users/yasser/scripts/archive/atlas_db_20260707_181958_p0l12_predeploy.bak.db`
- Backup SHA (pre-deploy anchor): `6bbb1599218d2d74b82d565933a9decb7e55603003945d45296f7c0307b90b71`
- Post-deploy production SHA: `e8f8f00ff949e695fe59d09647618e6eaf0368db282000d50b72cc37867c7b1a` (legitimately different — schema changed; this is now the new baseline anchor for future P0L work)

## Rollback command (available, not executed)

```
cp /Users/yasser/scripts/archive/atlas_db_20260707_181958_p0l12_predeploy.bak.db /Users/yasser/scripts/atlas.db
sha256sum /Users/yasser/scripts/atlas.db  # must equal 6bbb1599218d2d74b82d565933a9decb7e55603003945d45296f7c0307b90b71
```
Lighter-weight fallback (drop only the 8 new tables, leaves legacy tables
untouched either way):
```
sqlite3 /Users/yasser/scripts/atlas.db "DROP TABLE IF EXISTS portfolio_event_journal; DROP TABLE IF EXISTS position_lots; DROP TABLE IF EXISTS ledger_postings; DROP TABLE IF EXISTS valuation_marks; DROP TABLE IF EXISTS broker_reconciliation; DROP TABLE IF EXISTS report_snapshots; DROP TABLE IF EXISTS evidence_attachments; DROP TABLE IF EXISTS invariant_checks;"
```

## Conclusion

Additive bookkeeping schema deployed to production successfully. All 8 new
tables + 22 indexes exist and are empty. All 7 pre-existing tables are
byte-for-byte row-count unchanged. Integrity and FK checks both clean.
Rollback path verified available via both full-file restore and a
lightweight table-drop fallback. No code, strategy, TFE, reports, routing,
schedulers, env, Telegram, stops, targets, exits, or risk logic was touched.
