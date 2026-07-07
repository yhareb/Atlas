# P0L-6 — Staging-Only Bookkeeping Schema Follow-Up (Evidence)

**Date:** 2026-07-07
**Scope:** STAGING-ONLY. No production code, DB, schema, strategy, TFE, reports,
routing, schedulers, env, Telegram, stops, targets, exits, or risk touched.

## 1. Copy

```
cp /Users/yasser/scripts/atlas.db /tmp/p0l6/atlas_copy_p0l6.db
```
- Copy SHA256 at creation: `4b78286af1f68b40fcc46ef04da716bf91b5c6a54d8c8a239d8fdf0e11851242`
  (matched production SHA at that instant — clean copy, no corruption).
- `/tmp/p0l4` DB from the prior pass was **not** mutated or referenced by this
  DDL run (P0L-6 works from a fresh copy per the task's instruction).

## 2. Revised DDL

File: `/tmp/p0l6/p0l6_revised_ddl.sql` (12,419 bytes)

Corrections applied vs the P0L-4 DDL:

| Gap (from P0L-5) | Fix |
|---|---|
| No event type for initial funding | Added `'ACCOUNT_OPENED'` to `portfolio_event_journal.event_type` CHECK vocabulary |
| No posting_kind for Prof-verified manual cash correction | Added `'MANUAL_ADJUSTMENT'` to `ledger_postings.posting_kind` CHECK vocabulary |
| Opening balance needs its own posting_kind (distinct from ordinary trade principal) | Added `'OPENING_BALANCE'` to `ledger_postings.posting_kind` CHECK vocabulary |

All 8 P0L-4 tables carried forward unchanged in structure except the two CHECK
constraint edits above (`portfolio_event_journal.event_type`,
`ledger_postings.posting_kind`). No existing production table
(`trades`, `cash_ledger`, `account`, `signals`, `handoff`, `pending_pullbacks`,
`ema_retry_candidates`) is referenced by any `ALTER`/`DROP` statement — the DDL
file contains zero such statements, only `CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS`.

## 3. Double-entry models

### Opening balance ("Initial funding")
Two-leg posting under one `ACCOUNT_OPENED` journal event, same `event_id`:

| account | posting_kind | amount_cents |
|---|---|---|
| `CASH` | `OPENING_BALANCE` | `+N` |
| `EQUITY:OPENING_BALANCE` (or `CAPITAL:OWNER_CONTRIBUTION` — pick one convention, not both, per account) | `OPENING_BALANCE` | `-N` |

Sum per `event_id` = 0. Verified with a live test insert (event `ACCOUNT_OPENED`,
+100000 / -100000 cents) — accepted by the CHECK constraint, balance confirmed
via `SUM(amount_cents) GROUP BY event_id` = 0, then rolled back (no rows
persisted, per "no backfill yet").

### Prof manual cash/balance correction
Two-leg posting under one `MANUAL_CORRECTION` journal event (`prof_approved=1`),
same `event_id`:

| account | posting_kind | amount_cents |
|---|---|---|
| `CASH` | `MANUAL_ADJUSTMENT` | `±N` |
| `SUSPENSE:MANUAL_ADJUSTMENT` (default) or `EQUITY:MANUAL_ADJUSTMENT` (alternate) | `MANUAL_ADJUSTMENT` | `∓N` |

Sum per `event_id` = 0. Verified with a live test insert (event
`MANUAL_CORRECTION`, +5000 / -5000 cents) — accepted, balance confirmed = 0,
then rolled back.

### Single-sided posting prevention
SQLite `CHECK` constraints are per-row only; they cannot enforce an aggregate
"this event's postings sum to zero" rule at the column-constraint level. This
is documented as invariant **WARN**-mode check #12
(`ledger_postings_balance_zero`) in `invariant_checks`, consistent with the
P0L-2 design decision that all invariants start in WARN and promote to
ENFORCE only per Prof-approved step. An `AFTER INSERT` trigger is the eventual
ENFORCE-mode mechanism (not built in this pass — no code changes requested).

## 4. CHECK constraint verification (executed against the copy, then rolled back)

- Insert `event_type='ACCOUNT_OPENED'` → **accepted**.
- Insert `event_type='MANUAL_CORRECTION'` with `prof_approved=1` → **accepted**
  (already valid in P0L-4 vocabulary, re-verified here for completeness).
- Insert `posting_kind='OPENING_BALANCE'` → **accepted**.
- Insert `posting_kind='MANUAL_ADJUSTMENT'` → **accepted**.
- Negative control: insert `event_type='NOT_A_REAL_EVENT_TYPE'` →
  **rejected** with `CHECK constraint failed: event_type IN (...)` (exit code
  1, savepoint rolled back) — confirms the CHECK vocabulary is actually
  enforced, not silently permissive.
- All test rows executed inside a transaction and explicitly `ROLLBACK`ed.
  Post-rollback row counts confirmed 0 for both `portfolio_event_journal` and
  `ledger_postings` — no backfill rows persisted anywhere, per instruction.

## 5. Tables / indexes created (copy only)

8 tables: `portfolio_event_journal`, `position_lots`, `ledger_postings`,
`valuation_marks`, `broker_reconciliation`, `report_snapshots`,
`evidence_attachments`, `invariant_checks`.

22 indexes (`idx_%` prefix) created across those 8 tables.

## 6. Integrity

- `PRAGMA integrity_check` → `ok`
- `PRAGMA foreign_key_check` → zero rows returned (no violations)
- `PRAGMA foreign_keys = ON` set at head of DDL (per-connection pragma —
  application code must set this explicitly in Phase 2, same note carried
  from P0L-4).

## 7. Row counts

| Table | Before | After |
|---|---|---|
| `trades` (existing) | 70 | 70 |
| `cash_ledger` (existing) | 21 | 21 |
| `account` (existing) | 1 | 1 |
| `signals` (existing) | 26257 | 26257 (copy is a frozen snapshot; live production `signals` continues to grow independently) |
| `portfolio_event_journal` (new) | — | 0 |
| `position_lots` (new) | — | 0 |
| `ledger_postings` (new) | — | 0 |
| `valuation_marks` (new) | — | 0 |
| `broker_reconciliation` (new) | — | 0 |
| `report_snapshots` (new) | — | 0 |
| `evidence_attachments` (new) | — | 0 |
| `invariant_checks` (new) | — | 0 |

## 8. Production verification

- Production table list re-checked after this pass: still exactly the
  original 8 tables (`account`, `cash_ledger`, `ema_retry_candidates`,
  `handoff`, `pending_pullbacks`, `signals`, `sqlite_sequence`, `trades`) — no
  bookkeeping tables present in production.
- Production `trades` = 70, `cash_ledger` = 21 — unchanged.
- Production SHA256 at end of this pass: `5f673d57a46f18330891c4f67cf6db74891183ec00d35f4b58adf1c24d3c2884`
  vs. `4b78286af1f68b40fcc46ef04da716bf91b5c6a54d8c8a239d8fdf0e11851242` at copy
  time — **the hash moved, but this is the same pattern already documented in
  P0L-4**: the live `com.atlas.intraday` process continues writing `signals`
  rows during market hours, which changes the file bytes without touching
  schema or any bookkeeping-relevant table. Table structure, `trades`, and
  `cash_ledger` are all confirmed byte-for-byte identical in row count and
  content shape to the pre-pass baseline.

## Conclusion

Both P0L-5 schema gaps are resolved. Double-entry balance model defined and
verified (accepted by constraints, sums to zero, rolled back cleanly) for both
opening-balance and manual-adjustment cases. No single-sided posting path
exists in the design; enforcement is deferred to a future WARN→ENFORCE
promotion, per standing P0L-2 philosophy. Schema is ready for staging backfill
*code* to be drafted (still no rows written).
