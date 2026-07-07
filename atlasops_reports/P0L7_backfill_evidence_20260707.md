# P0L-7 — Staging-Only Bookkeeping Backfill Implementation (Evidence)

**Date:** 2026-07-07
**Scope:** STAGING-ONLY. No production code, DB, schema, strategy, TFE, reports,
routing, schedulers, env, Telegram, stops, targets, exits, or risk touched.

## 1. Copy + schema

```
cp /Users/yasser/scripts/atlas.db /tmp/p0l7/atlas_copy_p0l7.db
```
- Copy SHA256 at creation matched production SHA at that instant (clean copy).
- P0L-6 revised DDL (`/tmp/p0l6/p0l6_revised_ddl.sql`, copied to
  `/tmp/p0l7/p0l6_revised_ddl.sql`) applied to the copy only. All 8
  bookkeeping tables + 22 indexes created. `PRAGMA integrity_check` = `ok`
  immediately after DDL apply, before any backfill row was written.

## 2. Backfill script

File: `/tmp/p0l7/p0l7_backfill.py` (staging-only, never touches production
path; hardcoded `DB_PATH = "/tmp/p0l7/atlas_copy_p0l7.db"`).

- Every legacy float → exact-numeric conversion uses `Decimal(str(x))`
  exclusively — verified in source, zero `Decimal(x)` or raw float arithmetic
  anywhere in the money/quantity/price path.
- `to_cents()`, `to_quantity_scaled()`, `to_price_micros()` all route through
  `Decimal(str(x))` before scaling, with `ROUND_HALF_UP` only at the final
  integer cast.

## 3. Mapping rules applied

| Legacy source | New destination | Rule |
|---|---|---|
| `account` row + `cash_ledger` "Initial funding" row | `portfolio_event_journal` (`ACCOUNT_OPENED`) + `ledger_postings` (`CASH` +N / `EQUITY:OPENING_BALANCE` −N, `OPENING_BALANCE` kind) | Double-entry, `prof_approved=1` |
| `cash_ledger` "Prof verified ... correction" row | `portfolio_event_journal` (`MANUAL_CORRECTION`) + `ledger_postings` (`CASH` ±N / `SUSPENSE:MANUAL_ADJUSTMENT` ∓N, `MANUAL_ADJUSTMENT` kind) | Double-entry, `prof_approved=1` |
| `trades` VOIDED (3 rows) | `portfolio_event_journal` (`REVERSAL`) only | No lot, no postings |
| `trades` PENDING_FILL (52 rows) | `portfolio_event_journal` (`BUY_DECISION`) + `position_lots` (`PENDING_BROKER_CONFIRMATION`, `quantity_source='atlas_decision_estimate'`, `cost_basis_source='estimated'`) | No postings (no cash moved) |
| `trades` CLOSED with matched buy+sell `cash_ledger` rows | Full `BROKER_BUY_FILLED` / `BROKER_SELL_FILLED` double-entry using the broker's stated cash amounts | `cost_basis_source='broker_amount'`, never `price×quantity` recomputed |
| `trades` CLOSED/OPEN with an unmatched leg | `RECONCILIATION_EXCEPTION` event for that leg + `cash_confirmation_present` WARN invariant | **No posting inserted for the unmatched leg — never single-sided** |
| `trades` OPEN (4 rows) | `BROKER_BUY_FILLED` (or `RECONCILIATION_EXCEPTION` if unmatched) + `position_lots` (`OPEN`) | No exit fields |
| INTC (trade id 16) | Full 4-event chain: `BROKER_BUY_FILLED` → `STOP_HIT_DETECTED` (close 1, sourced from P0K3 backup DB) → `REVERSAL` (P0K3 correction) → `STOP_HIT_DETECTED` (close 2, live) | See §6 |

Cash-leg matching: `cash_ledger.reason` matched against `trades.broker_ref`
(exact substring) first, falling back to ticker-substring match when
`broker_ref` is empty; buy legs require `amount<0` + `"fill"` in reason, sell
legs require `amount>0` + `"sell"` in reason.

## 4. Idempotency key construction

Pattern: `legacy_<source>_<id>_<leg-or-purpose>`, e.g.
`legacy_trade_16_buy`, `legacy_trade_16_close1_reverted`,
`legacy_cash_11_manual_adjustment`, `legacy_account_opened_1`. All keys are
deterministic functions of the legacy row id + leg, so a rerun of the
backfill against the same legacy data reproduces identical keys (idempotent
by construction, not by chance).

## 5. INTC special-case handling

- Source for the first close: `/Users/yasser/scripts/archive/atlas_db_20260707_2107_p0k3_predeploy.bak.db`
  (the P0K3 pre-deploy backup), attached as an `evidence_attachments` row
  (`kind='system_log_excerpt'`) since the live copy alone cannot reconstruct
  the reverted history.
- 4-event chain reconstructed: `BROKER_BUY_FILLED` (2026-06-25 14:08:30) →
  `STOP_HIT_DETECTED` close 1 (exit $112.97, 2026-07-07 13:40:20, from
  backup) → `REVERSAL` (2026-07-07 21:04:41, `prof_approved=1`, `supersedes_id`
  points at close 1) → `STOP_HIT_DETECTED` close 2 (exit $112.12,
  2026-07-07 17:10:22, from live copy).
- **Neither sell leg was fabricated as `BROKER_SELL_FILLED`** — both remain
  cash-unconfirmed per the known P0K-5 lag pattern; each got a
  `cash_confirmation_present` WARN invariant instead of an invented posting.
- Final `position_lots` row for INTC: `status='CLOSED'`, `exit_event_id`
  points at close 2 (the current live truth), `realized_pnl_cents` taken from
  the live `trades.realized_pnl` (−$125.72).

## 6. Validation results

### Row counts

| Table | Before backfill | After backfill |
|---|---|---|
| `trades` (legacy, untouched) | 70 | 70 |
| `cash_ledger` (legacy, untouched) | 21 | 21 |
| `account` (legacy, untouched) | 1 | 1 |
| `signals` (legacy, untouched by this script; grew from concurrent live intraday) | 26257 | 26267 |
| `portfolio_event_journal` | 0 | 85 |
| `position_lots` | 0 | 67 |
| `ledger_postings` | 0 | 49 |
| `evidence_attachments` | 0 | 1 |
| `invariant_checks` | 0 | 13 |
| `valuation_marks` / `broker_reconciliation` / `report_snapshots` | 0 | 0 (out of scope for this backfill pass) |

67 `position_lots` = 70 legacy trades − 3 VOIDED (journal-only, no lot) = 67. Confirmed.

### Open positions match

`trades WHERE status='OPEN'` = 4. `position_lots WHERE status='OPEN'` = 4.
**MATCH.**

### Cash balance match to cents

Legacy `cash_ledger` final `balance_after` = `26424.29` → `2,642,429` cents
(via `Decimal(str(x))`). Sum of all `ledger_postings.amount_cents` where
`account='CASH'` = `2,642,429`. **EXACT MATCH to the cent.**

### Quantity / price roundtrip

Every `quantity_scaled` / `price_micros` value was round-tripped
(`Decimal(scaled)/SCALE == Decimal(str(original))`) immediately after
conversion for all 67 lots (all quantity + entry/exit/stop/target price
fields present). **Zero roundtrip failures** — `quantity_roundtrip_exact` and
`price_roundtrip_exact` invariants both `passed=1`.

### Idempotency collision check

85 `portfolio_event_journal` rows inserted, 85 distinct `idempotency_key`
values. **Zero collisions.**

### Ledger balance invariant (no single-sided postings)

Every `event_id` present in `ledger_postings` sums to exactly 0 cents —
verified via `GROUP BY event_id HAVING SUM(amount_cents) != 0`, which
returned zero rows. `ledger_postings_balance_zero` invariant `passed=1`.

### Closed-without-cash-confirmation

4 trades have at least one leg without a matching `cash_ledger` row:
- **AAPL (id 1), PBXT (id 2), IBXT (id 3)** — both buy AND sell legs
  unmatched. These are same-day, zero-fee, zero-P/L, entry==exit-price rows
  (opened and closed within ~2–12 seconds on 2026-06-22) — consistent with
  early Atlas v2 test/simulation entries that never reached the broker, not
  real missing bookkeeping. Flagged as `RECONCILIATION_EXCEPTION` on both
  legs, no postings inserted for either.
- **INTC (id 16)** — sell leg unmatched on **both** the reverted first close
  and the current live close (known P0K-5 lag, not a new anomaly).

6 total `RECONCILIATION_EXCEPTION` events logged (3 trades × 2 legs for
AAPL/PBXT/IBXT); INTC's 2 unmatched sell legs are typed `STOP_HIT_DETECTED`
with a separate WARN invariant rather than `RECONCILIATION_EXCEPTION`, since
that gap is already explained/expected per P0K-5 rather than a genuine
reconciliation break.

### Invariant WARN summary

| invariant_name | passed=1 | passed=0 |
|---|---|---|
| `cash_confirmation_present` | 0 | 8 |
| `ledger_postings_balance_zero` | 1 | 0 |
| `open_positions_match_legacy` | 1 | 0 |
| `price_roundtrip_exact` | 1 | 0 |
| `quantity_roundtrip_exact` | 1 | 0 |
| `reconciliation_exception_logged` | 1 (informational) | 0 |

The 8 `cash_confirmation_present` failures are all pre-existing legacy data
gaps (AAPL/PBXT/IBXT ×2 legs, INTC ×2 sell legs) surfaced by the backfill —
they are historically accurate reconciliation exceptions, not backfill bugs.

### Integrity

- `PRAGMA integrity_check` → `ok`
- `PRAGMA foreign_key_check` → zero rows (no violations)

## 7. Production verification

- Production table list: still exactly the original 8 tables — no
  bookkeeping tables present.
- Production `trades` = 70, `cash_ledger` = 21 — unchanged.
- Production SHA256 moved again during this pass (`1fb8d9fc...`), consistent
  with the same documented pattern from P0L-4/P0L-6: the live
  `com.atlas.intraday` process continues writing `signals` rows during
  market hours. No bookkeeping-relevant table or schema element changed in
  production.

## Conclusion

Backfill implementation is complete and validated entirely against
`/tmp/p0l7/atlas_copy_p0l7.db`. All required checks pass: cash balance exact
to the cent, quantity/price roundtrip exact, zero idempotency collisions,
zero single-sided postings, zero FK violations, integrity ok, open positions
match legacy. Three pre-existing "no cash record" trades (AAPL/PBXT/IBXT) and
the known INTC sell-side lag are the only reconciliation exceptions, both
consistent with prior findings (not new bugs introduced by this backfill).
No rows were ever written to production.
