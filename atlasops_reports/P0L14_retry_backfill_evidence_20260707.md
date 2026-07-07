# P0L-14 (Retry) — Production Bookkeeping Backfill (Evidence)

**Date:** 2026-07-07 22:29 +04
**Scope:** PRODUCTION BACKFILL EXECUTED into the 8 new bookkeeping tables
only, using the exact P0L-13 rehearsed logic. No legacy table writes
(other than read-only verification queries). No code patch, no deploy.

## Bounded idle poll

Poll started immediately; `atlas_intraday.py` was **not running** and no
lock file was present on the very first check (`poll_ticks: 1`,
`poll_duration_seconds: 0.0`) — a clean idle window was already open when
this retry began (unlike the first P0L-14 attempt, which was blocked by an
active cycle).

## Pre-execution gate (re-verified immediately, no delay)

| Check | Result |
|---|---|
| No `atlas_intraday.py` process | PASS — `proc_running: false` |
| Lock file absent/stale | PASS — `exists: false` |
| All 8 bookkeeping tables empty | PASS — all 0 |
| `trades`=70, `cash_ledger`=21 (match P0L-13) | PASS — exact match |

## Backup + SHA verification

- Backup path: `/Users/yasser/scripts/archive/atlas_db_20260707_182924_p0l14_predeploy.bak.db`
- Production SHA at backup time: `e127791571458afde890877de2610a6707098e3729e8506767535448ba26d907`
- Backup SHA: `e127791571458afde890877de2610a6707098e3729e8506767535448ba26d907` — **exact match**
- Final recheck immediately before write (no process must have started during the backup copy): `proc_running: false`, lock absent — clean.

## Execution

Ran the exact P0L-13 rehearsed backfill logic (identical algorithm:
`Decimal(str(x))`-only conversions, cash-ledger matching by `broker_ref`/
ticker substring, VOIDED→journal-only, PENDING_FILL→decision-only,
CLOSED/OPEN→full double-entry postings when cash-matched or
`RECONCILIATION_EXCEPTION` when not, INTC's 4-event chain reconstructed via
the P0K3 backup DB) against production `atlas.db` directly.

## Post-execution verification (matches P0L-13 exactly, zero drift)

### Rows inserted

| Table | Expected (P0L-13) | Actual (production) | Match |
|---|---|---|---|
| `portfolio_event_journal` | 85 | 85 | ✅ |
| `position_lots` | 67 | 67 | ✅ |
| `ledger_postings` | 49 | 49 | ✅ |
| `evidence_attachments` | 1 | 1 | ✅ |
| `invariant_checks` | 13 | 13 | ✅ |
| `valuation_marks` | 0 | 0 | ✅ (unchanged, out of scope) |
| `broker_reconciliation` | 0 | 0 | ✅ (unchanged, out of scope) |
| `report_snapshots` | 0 | 0 | ✅ (unchanged, out of scope) |

### Legacy tables

`trades`: 70 → 70 (**unchanged**). `cash_ledger`: 21 → 21 (**unchanged**).
Zero legacy writes occurred — confirmed independently via a direct
production query after execution.

### Validation results

| Check | Result |
|---|---|
| Open positions match | **YES** — legacy OPEN=4, `position_lots` OPEN=4 |
| Cash balance match to cents | **YES** — `2,642,429` cents both sides (legacy final balance vs. `SUM(ledger_postings.amount_cents WHERE account='CASH')`) |
| Quantity roundtrip | **PASS** — 0 failures |
| Price roundtrip | **PASS** — 0 failures |
| Idempotency collisions | **0** — 85 events, 85 distinct keys |
| INTC 4-event chain | Confirmed: event 82 `BROKER_BUY_FILLED` (2026-06-25) → event 83 `STOP_HIT_DETECTED` close 1 via P0K3 backup (2026-07-07 13:40:20) → event 84 `REVERSAL` (2026-07-07 21:04:41, `supersedes_id`/`linked_reversal_id`=83) → event 85 `STOP_HIT_DETECTED` close 2 live (2026-07-07 17:10:22, `supersedes_id`=84) |
| Invariant WARN summary | `cash_confirmation_present` 0/8 pass (AAPL/PBXT/IBXT both legs + INTC both sell legs — all pre-existing/known gaps, not new); `ledger_postings_balance_zero`, `open_positions_match_legacy`, `quantity_roundtrip_exact`, `price_roundtrip_exact`, `reconciliation_exception_logged` all 1/1 pass |
| `PRAGMA integrity_check` | `ok` (checked both inside the execution script and independently afterward) |
| `PRAGMA foreign_key_check` | 0 violations (checked both inside the execution script and independently afterward) |

Independent post-hoc re-verification (run separately from the execution
script, directly against production) confirms every row count, integrity
check, and FK check identically.

### SHA

- Post-deploy production SHA: `9e745a866d3df216d4e907e1510ec8a10742ea74ecd9db2d31051ec50bd200aa` (new baseline anchor)

## Rollback command (available, not executed)

```
cp /Users/yasser/scripts/archive/atlas_db_20260707_182924_p0l14_predeploy.bak.db /Users/yasser/scripts/atlas.db
sha256sum /Users/yasser/scripts/atlas.db  # must equal e127791571458afde890877de2610a6707098e3729e8506767535448ba26d907
```
This restores the DB to the exact pre-backfill state (schema present, all 8
bookkeeping tables empty, legacy tables unchanged from before this task).

## Conclusion

Production bookkeeping backfill completed successfully on the retry, with
a clean idle window available immediately. All results are byte-identical
to the P0L-13 rehearsal — zero drift. Legacy tables (`trades`, `cash_ledger`,
`account`) were never written to, confirmed both by the execution script's
own before/after counts and an independent post-hoc query. Integrity and FK
checks both clean. Rollback path verified available.
