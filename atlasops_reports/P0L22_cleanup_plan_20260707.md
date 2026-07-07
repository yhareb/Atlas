# P0L-22 — READ-ONLY Bad valuation_marks Cleanup Plan

**Date:** 2026-07-07
**Scope:** READ-ONLY planning only. Nothing executed — no DELETEs run, no backups taken, no DB writes.

## Context
P0L-21 confirmed the P0L-20 fix is working correctly across the live cycle at 19:17:01. Since then, 3 additional live cycles have run (19:27:31, 19:36:42, 19:47:03) — all producing correct marks. `valuation_marks` now totals 25 rows: 9 bad (pre-fix) + 16 correct (post-fix, 4 tickers × 4 cycles).

## 1. Bad valuation_marks rows identified
Criteria: attached to CLOSED AAPL/PBXT/IBXT lots (53/54/55) AND `marked_at` < 2026-07-07 19:17:01 (the first fixed-code cycle).

| id | lot_id | ticker | lot_status | marked_at |
|---|---|---|---|---|
| 1 | 53 | AAPL | CLOSED | 2026-07-07 18:46:30 |
| 2 | 54 | PBXT | CLOSED | 2026-07-07 18:46:30 |
| 3 | 55 | IBXT | CLOSED | 2026-07-07 18:46:30 |
| 4 | 53 | AAPL | CLOSED | 2026-07-07 18:56:30 |
| 5 | 54 | PBXT | CLOSED | 2026-07-07 18:56:30 |
| 6 | 55 | IBXT | CLOSED | 2026-07-07 18:56:30 |
| 7 | 53 | AAPL | CLOSED | 2026-07-07 19:06:37 |
| 8 | 54 | PBXT | CLOSED | 2026-07-07 19:06:37 |
| 9 | 55 | IBXT | CLOSED | 2026-07-07 19:06:37 |

**bad_valuation_mark_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]** — exactly 9 rows, 100% of the pre-fix bad set, zero overlap with post-fix rows.

Sanity check run: confirmed **zero** rows exist with `lot_id IN (53,54,55)` at or after 19:17:01 — the fix has fully stopped the bad-attribution pattern on every subsequent cycle (19:17:01, 19:27:31, 19:36:42, 19:47:03 all clean).

## 2. Matching stale fallback_price_used invariant rows

| id | invariant_name | checked_at | subject_id (lot) |
|---|---|---|---|
| 14 | fallback_price_used | 2026-07-07 18:46:30 | 53 |
| 15 | fallback_price_used | 2026-07-07 18:46:30 | 54 |
| 16 | fallback_price_used | 2026-07-07 18:46:30 | 55 |
| 17 | fallback_price_used | 2026-07-07 18:56:30 | 53 |
| 18 | fallback_price_used | 2026-07-07 18:56:30 | 54 |
| 19 | fallback_price_used | 2026-07-07 18:56:30 | 55 |
| 20 | fallback_price_used | 2026-07-07 19:06:37 | 53 |
| 21 | fallback_price_used | 2026-07-07 19:06:37 | 54 |
| 22 | fallback_price_used | 2026-07-07 19:06:37 | 55 |

**stale_invariant_check_ids = [14, 15, 16, 17, 18, 19, 20, 21, 22]** — exactly 9 rows, 1:1 with the 9 bad marks.

⚠️ Interesting corroborating detail (informational only, no action needed): these invariant rows' `detail` text carries mislabeled tickers inherited from the original bug (e.g. lot 53 is AAPL but detail says "ticker=SYNA", lot 54 is PBXT but says "ticker=RL", lot 55 is IBXT but says "ticker=BAC") — this is the old loop-index bug's ticker mislabeling bleeding into the WARN detail string itself. It's additional confirmation these rows are the bad pre-fix set and should be removed alongside their marks.

## 3. Confirm no correct post-fix rows included
Confirmed. All 16 post-fix rows (ids 10–25, lots 63/64/65/66 = SYNA/RL/BAC/ABNB, all OPEN, timestamps 19:17:01 / 19:27:31 / 19:36:42 / 19:47:03) are excluded from both delete lists. **correct_marks_excluded: YES**

## 4. Confirm no other tables would be touched
Delete scope is limited to exactly 2 tables, 9 rows each. Verified NOT touched: `position_lots` (67 rows), `portfolio_event_journal` (85), `ledger_postings` (49), `report_snapshots` (7), `trades` (70), `cash_ledger` (21). No FK relationship requires cascading changes to any of these — `valuation_marks.lot_id` and `invariant_checks.subject_id` are the only references, and deleting the marks/invariant rows does not affect the referenced `position_lots` rows themselves.

## 5. Backup plan
1. `cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/archive/atlas_db_<TIMESTAMP>_p0l22_precleanup.bak.db`
2. SHA256 the backup immediately after copy, record alongside pre-cleanup live DB SHA.
3. Backup taken only inside a confirmed idle window (bounded idle poll, 12 min cap / 5s interval, same pattern as P0L-14/16/20) — no backup or delete during an active `atlas_intraday.py` run.

## 6. Exact cleanup SQL (NOT executed — for future approval only)
```sql
BEGIN TRANSACTION;

DELETE FROM valuation_marks
WHERE id IN (1,2,3,4,5,6,7,8,9);

DELETE FROM invariant_checks
WHERE id IN (14,15,16,17,18,19,20,21,22);

COMMIT;
```
Both statements are ID-list scoped (not date/ticker/pattern-scoped) specifically to prevent any possibility of accidentally catching a future row that happens to share a ticker or timestamp pattern.

## 7. Rollback plan
1. If integrity/FK/count checks fail post-delete: `ROLLBACK;` before COMMIT if still in-transaction, or restore from the `p0l22_precleanup` backup file if already committed.
2. Restore: `cp archive/atlas_db_<TIMESTAMP>_p0l22_precleanup.bak.db /Users/yasser/scripts/atlas.db`, SHA-verify restored file matches backup SHA exactly.
3. No code changes involved in this cleanup — rollback is DB-file-only, no file/process restart needed.

## 8. Post-cleanup verification plan
1. `SELECT COUNT(*) FROM valuation_marks WHERE id IN (1,2,3,4,5,6,7,8,9);` → expect 0.
2. `SELECT COUNT(*) FROM valuation_marks;` → expect 25 − 9 = 16 (all post-fix rows ids 10–25 remain, plus any new cycles that ran in the interim).
3. `SELECT COUNT(*) FROM invariant_checks WHERE id IN (14,15,16,17,18,19,20,21,22);` → expect 0.
4. Spot-check remaining `valuation_marks` rows all map to `position_lots.status='OPEN'` and ticker matches `legacy_trades_id` (18/42/47/48 → SYNA/RL/BAC/ABNB) — zero CLOSED-lot rows remain.
5. `PRAGMA integrity_check;` → expect `ok`.
6. `PRAGMA foreign_key_check;` → expect 0 rows.
7. Confirm legacy tables unchanged: `trades`=70, `cash_ledger`=21, `account`=1.
8. Confirm untouched-table counts unchanged: `position_lots`=67, `portfolio_event_journal`=85, `ledger_postings`=49, `report_snapshots`= (current live count at execution time).

---

## Return Fields

- **P0L22_STATUS:** PLAN_READY
- **bad_valuation_mark_ids:** [1, 2, 3, 4, 5, 6, 7, 8, 9]
- **stale_invariant_check_ids:** [14, 15, 16, 17, 18, 19, 20, 21, 22]
- **correct_marks_excluded:** YES
- **delete_scope:** 2 tables (`valuation_marks`, `invariant_checks`), 9 rows each, ID-list scoped only — no date/ticker/pattern matching used
- **backup_plan:** timestamped copy of `atlas.db` tagged `p0l22_precleanup` in `archive/`, SHA256-verified, taken only inside a confirmed idle window (bounded idle poll, same pattern as P0L-14/16/20)
- **exact_cleanup_sql:** `DELETE FROM valuation_marks WHERE id IN (1,2,3,4,5,6,7,8,9); DELETE FROM invariant_checks WHERE id IN (14,15,16,17,18,19,20,21,22);` (wrapped in a transaction; full text in file above)
- **rollback_plan:** restore `atlas.db` from `p0l22_precleanup` backup, SHA-verify match, no code/process changes needed (DB-only rollback)
- **verification_plan:** bad-row counts→0, remaining valuation_marks=16 (+any interim cycles), all remaining rows map to OPEN lots only, integrity_check=ok, foreign_key_check=0, legacy tables unchanged (trades=70, cash_ledger=21, account=1), untouched-table counts unchanged
- **approval_required:** YES
- **production changes:** NONE
