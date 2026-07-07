# P0L-4 Staging-Only Bookkeeping Schema DDL — Evidence Report

**Scope:** staging-only DDL application to a copied `/tmp` database. No production DB write. No code changes. No backfill rows inserted.

**P0L4_STATUS: PASS**

## 1. Copied DB Path

```
/tmp/p0l4/atlas_copy_p0l4.db
```
Created via `cp /Users/yasser/scripts/atlas.db /tmp/p0l4/atlas_copy_p0l4.db` at 20260707_213454+0400.

## 2. DDL File Path

```
/tmp/p0l4/p0l4_bookkeeping_schema.sql
```
Full additive DDL implementing the approved P0L-1 (design) / P0L-2 (hardening) / P0L-3 (precision) proposal — 8 new tables, 21 indexes, `CHECK` constraints for enums, and foreign keys to both new tables and existing `trades`/`cash_ledger` (dual-write bridge columns).

## 3. Tables Created (in copied DB only)

1. `evidence_attachments`
2. `portfolio_event_journal`
3. `position_lots`
4. `ledger_postings`
5. `valuation_marks`
6. `broker_reconciliation`
7. `report_snapshots`
8. `invariant_checks`

Full table list in copied DB after DDL: `account, broker_reconciliation, cash_ledger, ema_retry_candidates, evidence_attachments, handoff, invariant_checks, ledger_postings, pending_pullbacks, portfolio_event_journal, position_lots, report_snapshots, signals, sqlite_sequence, trades, valuation_marks` — 16 total (7 original + 8 new + `sqlite_sequence`).

## 4. Existing Tables Unchanged

**existing_tables_unchanged: YES.**

No `ALTER`/`DROP` statement exists anywhere in the DDL file for `trades`, `cash_ledger`, `account`, `signals`, `handoff`, `pending_pullbacks`, or `ema_retry_candidates`. Verified by re-reading the applied schema (all 8 `CREATE TABLE` statements target only new table names) and by row-count comparison (below).

## 5. Row Counts Before/After (copied DB)

**Existing tables — unchanged:**

| Table | Before | After |
|---|---|---|
| cash_ledger | 21 | 21 |
| handoff | 13 | 13 |
| pending_pullbacks | 50 | 50 |
| signals | 26121 | 26121 |
| trades | 70 | 70 |
| account | 1 | 1 |
| ema_retry_candidates | 0 | 0 |

**New tables — all zero, no backfill performed (as instructed):**

| Table | Row Count |
|---|---|
| portfolio_event_journal | 0 |
| ledger_postings | 0 |
| position_lots | 0 |
| valuation_marks | 0 |
| broker_reconciliation | 0 |
| report_snapshots | 0 |
| evidence_attachments | 0 |
| invariant_checks | 0 |

## 6. Indexes Created

21 non-autoindex indexes across the 8 new tables:

- `broker_reconciliation`: `idx_reconciliation_lot`, `idx_reconciliation_match`
- `invariant_checks`: `idx_invariant_name_mode`, `idx_invariant_passed`, `idx_invariant_subject`
- `ledger_postings`: `idx_postings_account`, `idx_postings_event`, `idx_postings_legacy_cash`
- `portfolio_event_journal`: `idx_journal_event_type`, `idx_journal_legacy_cash`, `idx_journal_legacy_trades`, `idx_journal_lot`, `idx_journal_ticker_effective`
- `position_lots`: `idx_lots_legacy_trades`, `idx_lots_ticker_status`
- `report_snapshots`: `idx_snapshots_sha`, `idx_snapshots_type_time`
- `valuation_marks`: `idx_valuation_fallback`, `idx_valuation_lot_time`

Pre-existing indexes (`idx_ema_retry_status`, `idx_pending_pullbacks_status`, `idx_trades_ticker_status`) confirmed still present, unmodified.

## 7. Foreign Keys

**foreign_keys_enabled_or_reason_not:** Foreign key **constraints are declared** in the DDL (`portfolio_event_journal.lot_id → position_lots.id`, `position_lots.entry_event_id/exit_event_id → portfolio_event_journal.id`, `ledger_postings.event_id → portfolio_event_journal.id`, `valuation_marks.lot_id → position_lots.id`, `broker_reconciliation.lot_id → position_lots.id`, plus dual-write bridge FKs to existing `trades.id`/`cash_ledger.id`), and `PRAGMA foreign_key_check` returned **zero violations**.

However, `PRAGMA foreign_keys` reports **0 (disabled)** when queried on a fresh connection — this is expected SQLite behavior: the pragma is a **per-connection session setting**, not a persistent database property, and must be explicitly re-enabled (`PRAGMA foreign_keys = ON;`) by every future connection/application session that wants FK enforcement. The DDL application itself ran with `PRAGMA foreign_keys = ON` active, and `foreign_key_check` (a static structural check, not a live pragma) confirms no existing rows violate any declared constraint — but this is trivially true right now since all new tables are empty. **Action item for Phase 2 (dual-write shim):** any application code path that inserts into these tables must explicitly set `PRAGMA foreign_keys = ON` on its own connection, or FK constraints will be silently unenforced.

## 8. Integrity Check

```
PRAGMA integrity_check;
> ok
```

## 9. Production DB Verification

- Production `atlas.db` SHA256 **before** this work: `74af9997d9095d9d7b03af72f7f1dab1477f0207f3eee5c85ca53bd66d2c2e3a`
- Production `atlas.db` SHA256 **after** this work: `8dec37b1766695ee74a0c597b9ce2b8af8bd8cfccf8f80cf5115dd6fdd57eaab`
- **SHA differs** — but this is confirmed to be from **legitimate, unrelated, concurrent production activity**: `signals` row count grew from 26121 → 26188 during this session, consistent with the live `com.atlas.intraday` scheduled process (PID 8990, confirmed still running) writing normal scan signals. No table structure change occurred: production table list re-checked and is still exactly the original 8 tables (`account, cash_ledger, ema_retry_candidates, handoff, pending_pullbacks, signals, sqlite_sequence, trades`) — **none of the 8 new bookkeeping tables exist in production.** All other row counts (`cash_ledger`, `handoff`, `pending_pullbacks`, `trades`, `account`, `ema_retry_candidates`) are unchanged.

**production_db_unchanged (schema/tables): YES.** **production_db_byte-identical: NO** (expected — normal concurrent signal-writing activity, not caused by this work; no bookkeeping DDL touched production).

## 10. Staging Schema Issues

1. `PRAGMA foreign_keys` must be explicitly enabled per-connection by any future write path (§7) — not a schema defect, but a required implementation note carried forward to Phase 2.
2. No other issues found. All `CHECK` constraints for enum-like columns (`event_type`, `status`, `posting_kind`, `price_source`, `mode`, `subject_type`, `quantity_source`, `cost_basis_source`, `broker_status`) applied cleanly with no conflicts.
3. `idempotency_key UNIQUE` constraint on `portfolio_event_journal` applied without issue (column is nullable, so multiple NULLs are permitted by SQLite's `UNIQUE` semantics — appropriate here since not every event type requires an idempotency key, only broker-fill-originated ones per the P0L-2 design).

## Summary

| Field | Value |
|---|---|
| P0L4_STATUS | PASS |
| copied_db_path | `/tmp/p0l4/atlas_copy_p0l4.db` |
| ddl_file_path | `/tmp/p0l4/p0l4_bookkeeping_schema.sql` |
| tables_created | 8 (`evidence_attachments`, `portfolio_event_journal`, `position_lots`, `ledger_postings`, `valuation_marks`, `broker_reconciliation`, `report_snapshots`, `invariant_checks`) |
| existing_tables_unchanged | YES |
| indexes_created | 21 |
| foreign_keys_enabled_or_reason_not | Declared + zero violations (`foreign_key_check` clean); pragma is per-connection and must be explicitly set by future write paths |
| integrity_check | ok |
| production_db_unchanged | YES (schema/tables identical — no new tables leaked to production); byte-level SHA differs only due to unrelated concurrent `signals` writes from the live scheduled process |
| staging_schema_issues | None blocking; 1 implementation note carried forward (explicit per-connection FK enablement) |
| ready_for_backfill_design | YES |
| production changes | NONE |
