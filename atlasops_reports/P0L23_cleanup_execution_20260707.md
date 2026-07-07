# P0L-23 — PRODUCTION Bad valuation_marks Cleanup — Execution Report

**Date:** 2026-07-07
**Status: PASS**

## Idle Window
- Live `atlas_intraday.py` (PID 22227) was running at task start — per idle rule, no backup/write occurred until it exited.
- Bounded idle poll: process exited after ~293s (well within 12-min/720s cap). Re-confirmed idle + no lock file immediately before backup, and again immediately before the transaction.
- No process/lock reappeared during backup, transaction, or verification.

## Backup
- **backup_path:** `/Users/yasser/scripts/archive/atlas_db_20260707_235731_p0l23_precleanup.bak.db`
- SHA256 verified identical to production at backup time: `92c5f9827737fdc5b615ec88ed418cbc86263d8f5274a314369ff13e891f06d6` (both files match).

## Pre-Delete Re-Verification
- Re-confirmed `valuation_marks` ids 1–9: all attached to CLOSED lots 53/54/55, all timestamped ≤19:06:37 (before the 19:17:01 fix cutoff). ✅
- Re-confirmed `invariant_checks` ids 14–22: all `fallback_price_used`, `subject_id` 53/54/55, timestamps matching the 9 bad marks exactly. ✅
- Re-confirmed correct post-fix marks excluded: lots 63/64/65/66 (SYNA/RL/BAC/ABNB) all OPEN — 20 rows present at delete time (ids 10–29, including a 5th live cycle that ran during the idle wait, also correctly attributed). None in delete scope. ✅

## Transaction Executed
```sql
BEGIN TRANSACTION;
DELETE FROM valuation_marks WHERE id IN (1,2,3,4,5,6,7,8,9);
DELETE FROM invariant_checks WHERE id IN (14,15,16,17,18,19,20,21,22);
COMMIT;
```
Exit code 0 — committed cleanly.

## Post-Delete Verification

| Check | Result |
|---|---|
| Bad `valuation_marks` (ids 1–9) count | **0** ✅ |
| `valuation_marks` total remaining | **20** (all post-fix, ids 10–29) ✅ |
| Stale `invariant_checks` (ids 14–22) count | **0** ✅ |
| `invariant_checks` total remaining | 33 |
| Rows in `valuation_marks` still on a CLOSED lot | **0** (query returned empty) ✅ |
| `trades` | 70 (unchanged) |
| `cash_ledger` | 21 (unchanged) |
| `position_lots` | 67 (unchanged) |
| `portfolio_event_journal` | 85 (unchanged) |
| `ledger_postings` | 49 (unchanged) |
| `broker_reconciliation` | 0 (unchanged) |
| `evidence_attachments` | 1 (unchanged) |
| `report_snapshots` | 8 (was 7 — **expected increase**: one additional live cycle completed during the idle-wait/verification window, unrelated to this cleanup; not in delete scope, not caused by this transaction) |
| `PRAGMA integrity_check` | **ok** |
| `PRAGMA foreign_key_check` | **0 violations** (empty result) |

## Rollback (available, not needed)
```bash
cp /Users/yasser/scripts/archive/atlas_db_20260707_235731_p0l23_precleanup.bak.db /Users/yasser/scripts/atlas.db
```
Then SHA-verify restored file = `92c5f9827737fdc5b615ec88ed418cbc86263d8f5274a314369ff13e891f06d6`. No code/process restart needed (DB-file-only rollback).

---

## Return Fields

- **P0L23_STATUS:** PASS
- **backup_path:** `/Users/yasser/scripts/archive/atlas_db_20260707_235731_p0l23_precleanup.bak.db`
- **deleted_valuation_mark_ids:** [1, 2, 3, 4, 5, 6, 7, 8, 9]
- **deleted_invariant_check_ids:** [14, 15, 16, 17, 18, 19, 20, 21, 22]
- **correct_marks_preserved:** YES (20 remaining, all post-fix, all on OPEN lots)
- **non_scope_tables_unchanged:** YES (trades/cash_ledger/position_lots/portfolio_event_journal/ledger_postings/broker_reconciliation/evidence_attachments all unchanged; report_snapshots +1 from an unrelated concurrent live cycle, not from this transaction)
- **integrity_check:** ok
- **foreign_key_check:** 0 violations
- **rollback_available:** YES
- **production changes:** bad telemetry cleanup only
