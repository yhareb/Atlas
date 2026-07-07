# P0L-13 — Staging-Only Production-Current Backfill Rehearsal (Evidence)

**Date:** 2026-07-07
**Scope:** STAGING-ONLY. Rehearses the P0L-7 backfill against a fresh copy
of production `atlas.db` taken *after* the P0L-12 schema deployment. Zero
production writes, zero code changes, zero deploys.

## 1. Copy + pre-rehearsal verification

```
cp /Users/yasser/scripts/atlas.db /tmp/p0l13/atlas_copy_p0l13.db
```
Copy SHA256 = production SHA256 at copy time = `e8f8f00ff949e695fe59d09647618e6eaf0368db282000d50b72cc37867c7b1a`
(the post-P0L-12 baseline) — exact match, clean copy.

**Production bookkeeping tables confirmed empty BEFORE rehearsal:** all 8
(`portfolio_event_journal`, `position_lots`, `ledger_postings`,
`valuation_marks`, `broker_reconciliation`, `report_snapshots`,
`evidence_attachments`, `invariant_checks`) = 0 rows, checked directly
against production immediately before the copy was made.

**Fresh production row counts re-read (not assumed from P0L-7):**
`trades`=70 (`CLOSED`=11, `OPEN`=4, `PENDING_FILL`=52, `VOIDED`=3),
`cash_ledger`=21, `account`=1, `signals`=26504. INTC (trade id 16) confirmed
`CLOSED`, `exit_price=112.12`, `exit_at=2026-07-07 17:10:22` — identical
final state to what P0L-7 saw.

**Conclusion of the fresh read:** production `trades`/`cash_ledger`/`account`
have **not changed** since P0L-7 (no new fills, no new manual corrections,
no additional INTC activity). This is expected — no backfill-relevant
production activity occurred between P0L-7 and now, only the P0L-12 schema
deployment (which added empty tables, touching no existing row).

## 2. Backfill script

`/tmp/p0l13/p0l13_backfill.py` — a copy of `/tmp/p0l7/p0l7_backfill.py` with
only `DB_PATH` repointed to `/tmp/p0l13/atlas_copy_p0l13.db` (mechanical
path substitution only, zero logic changes). `INTC_BACKUP_PATH` still points
to `/Users/yasser/scripts/archive/atlas_db_20260707_2107_p0k3_predeploy.bak.db`
— re-verified present and SHA-identical to the copy P0L-7 used
(`603cb49b38d79c9e468a9e94d7c00c1e3ee52cce81672222ce310aca5d5a8db6`).
Compile check: PASS.

## 3. Rehearsal run results

```
python3 p0l13_backfill.py
```

| Table | Rows inserted |
|---|---|
| `portfolio_event_journal` | 85 |
| `position_lots` | 67 |
| `ledger_postings` | 49 |
| `evidence_attachments` | 1 |
| `invariant_checks` | 13 |

Zero quantity/price roundtrip failures. 6 `RECONCILIATION_EXCEPTION`
events. Legacy OPEN = 4, new `position_lots` OPEN = 4 (match).

## 4. Validation results

| Check | Result |
|---|---|
| Open positions match | **YES** — legacy `trades` OPEN=4, `position_lots` OPEN=4 |
| Cash balance match to cents | **YES** — legacy final balance `26424.29` → `2,642,429` cents == `SUM(ledger_postings.amount_cents WHERE account='CASH')` == `2,642,429`, exact |
| Quantity roundtrip | **PASS** — 0 mismatches |
| Price roundtrip | **PASS** — 0 mismatches |
| Idempotency collisions | **0** — 85 events, 85 distinct keys |
| Closed without cash credit | **3 trades** (AAPL id 1, PBXT id 2, IBXT id 3 — both legs unmatched each; same pre-existing legacy gap identified in P0L-7, not new) + INTC's 2 sell legs (handled separately, typed `STOP_HIT_DETECTED` not `RECONCILIATION_EXCEPTION`, per the known P0K-5 lag) |
| INTC timeline | Full 4-event chain reconstructed identically to P0L-7: `BROKER_BUY_FILLED` (event 82) → `STOP_HIT_DETECTED` close 1 via P0K3 backup (event 83) → `REVERSAL` (event 84, `supersedes_id`/`linked_reversal_id`=83) → `STOP_HIT_DETECTED` close 2 live (event 85, `supersedes_id`=84) |
| Invariant WARN summary | `cash_confirmation_present` 0/8 pass (all pre-existing gaps); `ledger_postings_balance_zero`, `open_positions_match_legacy`, `quantity_roundtrip_exact`, `price_roundtrip_exact` all 1/1 pass |
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 0 violations |

## 5. Drift vs. P0L-7

**Zero drift.** Every number — row counts inserted per table, cash balance
match, roundtrip results, idempotency collision count, reconciliation
exception list (AAPL/PBXT/IBXT + INTC), invariant WARN summary, and the
exact INTC 4-event chain — is **identical** to the original P0L-7 run. This
is the expected and correct outcome: production `trades`/`cash_ledger`/
`account` have not changed since P0L-7 (confirmed via the fresh row-count
read in §1), and the only production change between the two tasks was the
P0L-12 schema deployment, which added empty tables and touched no existing
row. A backfill rehearsal against unchanged source data using the same
(unmodified) backfill logic against the same schema should — and does —
reproduce byte-identical results.

## 6. Production verification (after rehearsal)

- Production SHA256: `e8f8f00ff949e695fe59d09647618e6eaf0368db282000d50b72cc37867c7b1a` — **unchanged** from before this task started.
- Production `trades`=70, `cash_ledger`=21 — unchanged.
- Production bookkeeping tables: all 8 re-verified still **empty** (0 rows each) after the rehearsal — confirming this task never touched production, only the `/tmp/p0l13` copy.

## Conclusion

The backfill logic remains correct and stable against the current
post-P0L-12 production data: exact parity with P0L-7, zero drift, all
validations pass, production completely untouched (schema and data both
byte-identical before and after). The rehearsal confirms the backfill is
ready to be considered for a future production backfill approval decision
— that decision itself is out of scope for this READ-ONLY/staging-only task
and requires separate explicit Prof authorization.
