# P0L-21 — Post-Fix Live-Cycle valuation_marks Verification

**Date:** 2026-07-07
**Scope:** READ-ONLY verification only. No patches, no deploys, no DB writes, no cleanup, no forced trades, no Telegram test sends.

## Context
P0L-20 deployed the valuation_marks lot-id fix to production at ~19:07 UTC. The first live `com.atlas.intraday` cycle to run entirely on the fixed code was the one observed live during this task (PID 19011, started ~23:16 local / completed 19:17:11 UTC-log-timestamp). Two earlier cycles (18:46:30, 18:56:30) and one (19:06:37) predate the P0L-20 deploy or straddled it — those still show old buggy marks. This report focuses on the cycle that is unambiguously post-fix: report_snapshot id=4, generated_at 2026-07-07 19:17:11.

## 1. Did atlas_intraday.py complete successfully?
YES. Process (PID 19011) started and exited cleanly within the poll window (~50s observed exit after last check). `atlas_intraday.log` shows a full report body generated and delivered. No traceback in the most recent 500 lines of `atlas_intraday.err.log` (the window covering this cycle).

## 2. Did valuation_marks increase after the fixed code ran?
YES. Count went from 9 → 13 (+4), ids 10–13, all timestamped 2026-07-07 19:17:01 — matching the fixed-code cycle.

## 3. Are new marks attached only to OPEN position_lots for the correct real legacy trade ids?

| valuation_marks.id | lot_id | legacy_trades_id | ticker | lot_status | price | price_source |
|---|---|---|---|---|---|---|
| 10 | 63 | 18 | SYNA | OPEN | 119.15 | stale_cache |
| 11 | 64 | 42 | RL | OPEN | 393.52 | stale_cache |
| 12 | 65 | 47 | BAC | OPEN | 60.02 | stale_cache |
| 13 | 66 | 48 | ABNB | OPEN | 148.45 | stale_cache |

All 4 correct: SYNA→18, RL→42, BAC→47, ABNB→48, all lot_status=OPEN. **This confirms the fix is working exactly as designed.**

## 4. Did any new mark attach to CLOSED AAPL/PBXT/IBXT lots 53/54/55?
NO. Zero of the 4 new marks (ids 10–13) reference lot_id 53, 54, or 55. Those lots remain CLOSED and received no new marks from the fixed-code cycle.

## 5. Did valuation_mark_lot_mismatch WARNs appear?
NO. `SELECT COUNT(*) FROM invariant_checks WHERE invariant_name='valuation_mark_lot_mismatch'` = 0. The defensive guard did not need to fire — real-id resolution worked correctly on the first fixed-code cycle, so no mismatch was ever detected/skipped.

Note: 4 new `fallback_price_used` WARN rows (ids 23–26) *did* fire — this is expected/correct behavior (price_source='stale_cache', not live_provider) and unrelated to the lot-id bug.

## 6. Did report_snapshots still increase by 1?
YES. report_snapshots count 3→4 (id=4, generated_at 2026-07-07 19:17:11, dry_run=0).

## 7. Did legacy trades/cash_ledger remain unchanged unless a real broker event occurred?
YES — unchanged. `trades` count = 70 (unchanged), `cash_ledger` count = 21 (unchanged). No broker event occurred this cycle (report shows "BUY Small blocked" reasons only, no new fills).

## 8. Did Telegram delivery remain normal?
YES, with one transient/routine retry (not a failure): first chunk attempt hit a 5s read-timeout, auto-retried after 2s, succeeded on attempt 2 (fell back to plain-text after a Markdown parse failure), delivered successfully: `message_id=1488`. `[intraday] telegram report success=True`. This retry pattern is a known pre-existing network-transient behavior, unrelated to the P0L-20 code change.

## 9. Did any dual-write exception appear in logs?
NO. Grep for `_dualwrite`, `dual_write`, `valuation_mark` across the full `atlas_intraday.err.log` returns zero matches. The only Tracebacks present in the error log (5 total, lines 1094/2453/2483/2513/2543) are all pre-existing/historical `NameError: name 'target_price' is not defined` failures in `atlas_engine.py`'s `log_signal` call path — confirmed to sit in the first ~48% of the log file, well before this cycle, and outside scope of this task (unrelated to bookkeeping/valuation_marks; not investigated further per read-only/no-strategy-changes scope).

---

## Return Fields

- **P0L21_STATUS:** PASS
- **intraday_cycle_completed:** YES
- **new_valuation_marks_count:** 4 (ids 10–13; total table count 9→13)
- **correct_marks_by_ticker:** SYNA→trades.id 18 (lot 63) ✅, RL→trades.id 42 (lot 64) ✅, BAC→trades.id 47 (lot 65) ✅, ABNB→trades.id 48 (lot 66) ✅ — all 4/4 correct, all OPEN
- **wrong_closed_lot_marks_added:** NO
- **valuation_mark_lot_mismatch_WARNs:** 0
- **report_snapshots_delta:** +1 (3→4)
- **legacy_trades_delta:** 0 (70→70)
- **legacy_cash_ledger_delta:** 0 (21→21)
- **telegram_delivery_status:** SUCCESS (message_id=1488, one transient timeout auto-retried, normal pattern)
- **dual_write_errors_found:** NO
- **ready_for_bad_marks_cleanup:** YES (fix confirmed working live; the 9 pre-fix bad rows are now clearly isolated/dated before 19:17:01 and safe to target in a future cleanup pass)
- **production changes:** scheduled dual-write telemetry only
