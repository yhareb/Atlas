# P0L-5 READ-ONLY Bookkeeping Backfill Design

**Scope:** read-only design only. No rows written to production or staging DB. No code changes. No DB/strategy/TFE/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**P0L5_STATUS: BACKFILL_DESIGN_COMPLETE — design only, no rows written**

## Real Data Profile (read-only inspection, informs the design below)

| Fact | Value |
|---|---|
| Total `trades` rows | 70 |
| `trades.status` breakdown | `PENDING_FILL`: 52, `CLOSED`: 11, `OPEN`: 4, `VOIDED`: 3 |
| Trades with `broker_ref` set | 11 (of 70) |
| Trades with `parent_id` set (FIFO lot-split) | 0 — no lot-splitting has occurred yet in this account's history |
| Distinct tickers | 36 |
| `CLOSED` trades with `broker_ref` | 7 (of 11 CLOSED) — 4 `CLOSED` rows have **no** `broker_ref` |
| Total `cash_ledger` rows | 21 |
| `cash_ledger` rows matching `'Broker fill%'` | 11 |
| `cash_ledger` rows matching `'Broker sell%'` | 6 |
| Other `cash_ledger` reasons | id 1 `"Initial funding"`; id 2/3 a matched TSM buy+sell pair with slightly different phrasing (`"TSM broker fill..."` / `"TSM sell..."`); id 11 `"Prof verified eToro available cash correction..."` — a manual balance correction, not a trade event at all |

These numbers directly shape the mapping rules below — in particular, the **11 CLOSED-but-4-without-broker_ref gap** is the same class of issue the INTC incident exposed, just discovered here as a pre-existing pattern across the whole table rather than a one-off.

## 1. `trades` → New Schema Mapping

For each of the 70 existing `trades` rows:

**→ `position_lots` (1:1, always):**
```
position_lots.legacy_trades_id      = trades.id
position_lots.ticker                 = trades.ticker
position_lots.status                 = mapped per trades.status (see status-mapping table below)
position_lots.quantity_text          = str(trades.quantity)  -- exact string, no float re-parse
position_lots.quantity_scaled        = Decimal(str(trades.quantity)) * 10^8, as integer
position_lots.quantity_scale         = 100000000
position_lots.quantity_source        = 'broker_fill' if trades.broker_ref else 'atlas_decision_estimate'
position_lots.entry_price_micros     = Decimal(str(trades.entry_price)) * 10^6, as integer
position_lots.entry_price_decimal_text = str(trades.entry_price)
position_lots.exit_price_micros      = same pattern, NULL if trades.exit_price IS NULL
position_lots.exit_price_decimal_text = same pattern
position_lots.stop_loss_micros / _decimal_text     = same pattern (nullable)
position_lots.target_price_micros / _decimal_text  = same pattern (nullable)
position_lots.cost_basis_cents       = see §cost-basis rule below
position_lots.cost_basis_source      = 'broker_amount' if a matching cash_ledger debit row exists, else 'estimated'
position_lots.realized_pnl_cents     = round(Decimal(str(trades.realized_pnl)) * 100) if status CLOSED else NULL
position_lots.broker_quantity_text / broker_price_text / broker_amount_text
                                       = parsed out of trades.notes where a "Broker fill/sell..." pattern is found
                                         (regex-extractable for all 11 broker_ref rows; NULL otherwise — not fabricated)
```

**`trades.status` → `position_lots.status` mapping:**
| Legacy status | New status | Notes |
|---|---|---|
| `OPEN` | `OPEN` | direct |
| `CLOSED` | `CLOSED` | direct |
| `PENDING_FILL` | `PENDING_BROKER_CONFIRMATION` | matches the new schema's third status exactly — this status was clearly anticipated by the P0L-1 design without knowing 52 of 70 rows would actually need it |
| `VOIDED` | **no `position_lots` row created** | see §ambiguity flags — VOIDED trades represent a decision that was reversed before ever being a real position; they map to journal events only (a `BUY_DECISION` followed by a `REVERSAL`), not to a lot, since a `position_lots` row implies a real (even if pending) holding |

**→ `portfolio_event_journal` (1 or more rows per trade):**
- Every `trades` row produces at minimum one `BUY_DECISION`-equivalent event at `entry_at`.
- If `broker_ref` is set, a second `BROKER_BUY_FILLED` event is created, `occurred_at` = `entry_at` (best available estimate — the exact broker confirmation timestamp isn't separately recorded in current data), sourced from the matching `cash_ledger` debit row's `ts` if one is found (see cash_ledger mapping below) — **this is more accurate** than reusing `entry_at`, so the rule is: use the matched `cash_ledger.ts` when available, fall back to `trades.entry_at` otherwise, and flag `timestamp_approximation=1` in the fallback case.
- If `status='CLOSED'`, a `SELL_DECISION` event at `exit_at`, and — only if a matching `cash_ledger` credit row is found — a `BROKER_SELL_FILLED` event at that credit row's `ts`. **If no matching credit row is found (the 4-of-11 gap identified above, including the pre-correction INTC case), NO `BROKER_SELL_FILLED` event is created**, and a `RECONCILIATION_EXCEPTION` event is created instead, flagged `cash_post_missing=1`. This is the design's explicit, honest representation of "we don't actually know the broker confirmed this" — exactly the ambiguity that caused the INTC incident to be discoverable only via a Prof screenshot rather than a system-detected exception.
- If `status='VOIDED'`, a `BUY_DECISION` event followed immediately by a `REVERSAL` event (`supersedes_id` pointing at the `BUY_DECISION`), both timestamped from `updated_at` / the "VOIDED ..." text found in `notes` (all 3 VOIDED rows have explicit void-reason text in `notes`, e.g. "broker did not execute AAL buy") — `inferred_decision=1` on both, since these are reconstructed from free text, not from a structured original event.
- Every backfilled event gets `source='backfill_p0l5'` and `legacy_trades_id` set, distinguishing it permanently from events created by the live dual-write shim going forward (Phase 2).

**→ `ledger_postings`:** created only where a `portfolio_event_journal` row of type `BROKER_BUY_FILLED`/`BROKER_SELL_FILLED`/`CASH_DEBIT_POSTED`/`CASH_CREDIT_POSTED` was actually created per the cash_ledger mapping below — i.e., postings are driven by `cash_ledger`, not manufactured independently from `trades` alone. A `BUY_DECISION`/`SELL_DECISION`/`REVERSAL`-only event (no matching cash row) produces **no** `ledger_postings` rows, by design — decisions without confirmation don't get to claim a cash movement happened.

## 2. `cash_ledger` → New Schema Mapping

For each of the 21 existing `cash_ledger` rows:

| Pattern | Journal event | Postings |
|---|---|---|
| `reason LIKE 'Broker fill%'` (11 rows) | `BROKER_BUY_FILLED`, `occurred_at=ts` | `PRINCIPAL` posting to `POSITION:<ticker>` (positive) + `CASH` (negative, = `amount_cents`); `FEE` posting split out if fee text is parseable from `reason` |
| `reason LIKE 'Broker sell%'` (6 rows) | `BROKER_SELL_FILLED`, `occurred_at=ts` | `PRINCIPAL` reversal on `POSITION:<ticker>` + `CASH` credit + `REALIZED_PNL` posting (computed as the delta) |
| `reason = 'Initial funding'` (id 1) | **No journal event** — this is an `account`-level opening balance, not a position/trade event | A single `ledger_postings` row with `account='CASH'`, `posting_kind='PRINCIPAL'`, `amount_cents = amount`, `event_id` pointing at a synthetic one-time `ACCOUNT_OPENED`-equivalent marker row (out of the 9 defined event types — flagged as a **schema gap**, see risks below: the current event-type vocabulary has no explicit "opening balance" type, and forcing it into `BROKER_BUY_FILLED`/`CASH_CREDIT_POSTED` would misrepresent it) |
| `reason LIKE 'Prof verified...correction%'` (id 11) | `MANUAL_CORRECTION`, `prof_approved=1` (explicit "Prof verified" text is itself informal evidence — `evidence_id` would point at a new `evidence_attachments` row of kind `'prof_message'` with `description` quoting the reason text, since no separate screenshot file exists for this one) | A `ledger_postings` row for the balance adjustment delta, `posting_kind='FX_ADJUSTMENT'` is the wrong kind for this (it's not FX) — **flagged as a second schema gap**: `posting_kind` enum needs a `'MANUAL_ADJUSTMENT'` value added before backfill, or this row has no correct kind to use |
| TSM buy/sell pair (id 2, 3) — matched to a `trades` row already covered above | Linked via `legacy_cash_ledger_id` on the corresponding `portfolio_event_journal`/`ledger_postings` rows created from the `trades`-side mapping — **not double-created** | n/a (already counted above) |

**Matching cash_ledger rows to trades rows:** primary match key is `broker_ref` appearing as a substring in `cash_ledger.reason` (works for all 11 `Broker fill` + observed `Broker sell` rows, since the ref/order-id string is embedded in the free text). Where no `broker_ref` substring match is found for a `CLOSED` trade, that trade is flagged `cash_post_missing=1` (see §1) rather than matched by ticker+approximate-timestamp heuristics, which would risk a false-positive match — **exact substring match or no match**, no fuzzy matching, to keep the backfill provably conservative.

## 3. Ambiguity Flags (applied per backfilled row)

| Flag | Set when |
|---|---|
| `inferred_decision` | The `BUY_DECISION`/`SELL_DECISION` event's existence/timing is reconstructed from `trades.entry_at`/`exit_at`/`notes` text rather than from an original structured decision record (true for **100% of backfilled decision events**, since no such structured record exists pre-P0L) |
| `broker_confirmed` | Set `1` only when a `BROKER_BUY_FILLED`/`BROKER_SELL_FILLED` event was actually created (i.e., a matching `broker_ref`-linked `cash_ledger` row was found); `0` otherwise — this becomes the queryable answer to "was this actually broker-confirmed" that the INTC incident lacked |
| `cash_post_missing` | Set on any `CLOSED` `trades` row (or `SELL_DECISION` event) where no matching `cash_ledger` credit row was found — **known to apply to 4 of the 11 CLOSED rows** based on the broker_ref/cash-row count mismatch found in inspection |
| `timestamp_approximation` | Set whenever `occurred_at` had to fall back to `trades.entry_at`/`exit_at`/`updated_at` instead of a matched `cash_ledger.ts` (applies to the 59 trades with no `broker_ref` entirely, plus any `CLOSED` row lacking a matched sell-side cash row) |
| `cost_basis_estimated` | Set whenever `cost_basis_cents` had to be computed from `entry_price_micros × quantity_scaled` because no broker-amount cash row was matched, rather than being taken from the broker's own stated total (applies to any of the 59 no-`broker_ref` rows) |

## 4. Decimal Conversion Rules

1. **Legacy `REAL` → `Decimal`:** always via `Decimal(str(x))`, **never** `Decimal(x)` directly on a float — the latter would re-inherit the float's own binary imprecision (e.g. `Decimal(7.70534157)` produces a long imprecise expansion; `Decimal(str(7.70534157))` produces the exact intended value). This rule applies uniformly to every float field being converted: `quantity`, `entry_price`, `exit_price`, `stop_loss`, `target_price`, `realized_pnl`, `realized_pnl_pct`, `cash_ledger.amount`, `cash_ledger.balance_after`.
2. **Money → cents:** `cents = int((Decimal(str(x)) * 100).to_integral_value(rounding=ROUND_HALF_UP))` — single rounding step, applied once, at the final cents conversion only (never rounded at an intermediate step).
3. **Quantity → `quantity_text` + `quantity_scaled` + `quantity_scale`:** `quantity_text = str(trades.quantity)` (verbatim); `quantity_scaled = int((Decimal(str(trades.quantity)) * 100000000).to_integral_value(rounding=ROUND_HALF_UP))`; `quantity_scale = 100000000` fixed, per the P0L-3 design. **Verification step required:** every converted `quantity_scaled / quantity_scale` must reconstruct to a `Decimal` exactly equal to the original `Decimal(str(trades.quantity))` — any row failing this exact round-trip check is held out of the backfill and flagged for manual review rather than silently accepted with rounding error (not expected to trigger for the observed 8-decimal-max precision, but must be checked, not assumed).
4. **Price → `price_micros` + `price_decimal_text`:** `price_decimal_text = str(trades.entry_price)` (verbatim); `price_micros = int((Decimal(str(trades.entry_price)) * 1000000).to_integral_value(rounding=ROUND_HALF_UP))`. Same exact round-trip verification requirement as quantity.
5. **`cost_basis_cents` rule (per P0L-3 §4.3):** where a broker-amount-bearing `cash_ledger` row is matched, parse the dollar amount out of its `amount` column (itself a float needing the `Decimal(str(x))` rule) and use `abs(amount) + entry_fees_cents` as cost basis — **not** `entry_price_micros × quantity_scaled / 10^6`. Where no such row is matched (`cost_basis_estimated=1`), fall back to the computed product, single final cents rounding.

## 5. Idempotency Key Construction

```
idempotency_key = sha256(
    event_type + '|' + ticker + '|' + (broker_ref or '') + '|' + occurred_at.isoformat()
).hexdigest()
```
Rules:
- Only computed/set for `BROKER_BUY_FILLED` and `BROKER_SELL_FILLED` event types (the ones representing a real-world broker fill that could plausibly be re-ingested twice); all other event types leave `idempotency_key` NULL (permitted by the `UNIQUE` constraint's NULL-multiplicity semantics per the P0L-4 schema).
- For backfill specifically, since every row is being inserted exactly once from a fixed historical snapshot, **duplicate-key collisions are not expected during backfill itself** — the check exists primarily to (a) prove the key-construction function is deterministic and collision-free against real historical data before Phase 2 relies on it live, and (b) catch any case where two different `trades` rows for the same ticker happen to share an identical `broker_ref` (would indicate a genuine data problem worth investigating, not a backfill bug) — a **pre-backfill dry-run key-collision check across all 11 broker_ref rows** is included in the validation plan (§6) specifically to test this before any row is written.

## 6. Invariant WARN Checks to Run After Backfill

All checks run in `WARN` mode (per P0L-2 §9 — no invariant is enforced yet), writing rows to `invariant_checks`:

1. `no_closed_without_sell_event` — every `position_lots.status='CLOSED'` row must have a linked `SELL_DECISION` or `BROKER_SELL_FILLED` event. **Expected result: 100% pass**, since backfill only sets `status='CLOSED'` when a `SELL_DECISION` event was created.
2. `broker_fill_has_cash_posting` — every `BROKER_BUY_FILLED`/`BROKER_SELL_FILLED` event must have ≥1 `ledger_postings` row. **Expected result: 100% pass** by construction (postings are only created alongside these events).
3. `postings_balance_per_event` — for each `event_id`, `SUM(ledger_postings.amount_cents)` grouped appropriately must net to zero within the event's own accounting (cash vs position vs pnl). **Expected to require the most careful implementation** — this is the check most likely to surface a real historical data quirk (e.g. a fee that wasn't cleanly separable from principal in old free-text notes).
4. `cash_post_missing_flagged` — cross-check: every `position_lots` row with `cost_basis_source='estimated'` OR every CLOSED lot lacking a `BROKER_SELL_FILLED` event must have a corresponding `RECONCILIATION_EXCEPTION` journal row. **Expected result: exactly 4 flagged exceptions**, matching the pre-identified CLOSED-without-broker_ref gap.
5. `quantity_precision_roundtrip` — every `quantity_scaled/quantity_scale` must reconstruct exactly to the source `Decimal(str(quantity))` (per §4.3). **Expected result: 100% pass**; any failure blocks backfill completion for that row pending manual review.
6. `dual_write_consistency` (from P0L-2) — every backfilled `position_lots`/`portfolio_event_journal` row's `legacy_trades_id`/`legacy_cash_ledger_id` must point at a legacy row with matching status/amount. **Expected result: 100% pass** immediately after backfill (by definition, since backfill derives from those exact legacy rows) — this check becomes more meaningful once live dual-write (Phase 2) begins diverging over time.

## 7. Validation Report Plan

A single Markdown report (post-backfill, staging-only, not yet produced) will include:

1. **Legacy row counts vs new row counts:** `trades: 70` vs `position_lots: <N, expected 67>` (70 minus 3 VOIDED, which map to journal-only per §1) `+ 3 VOIDED-only journal pairs`; `cash_ledger: 21` vs `ledger_postings: <N>` (expected >21, since fee/principal/pnl splits multiply rows per event) plus 1 non-position `Initial funding`/1 `MANUAL_CORRECTION` handled per §2.
2. **Open positions match:** the `position_lots WHERE status='OPEN'` set must exactly equal current `trades WHERE status='OPEN'` (4 tickers, per the P0K-3-corrected present state) — ticker-for-ticker, quantity-for-quantity (via exact `quantity_scaled` comparison, not float `==`).
3. **Cash balance match to cents:** `SUM(ledger_postings.amount_cents WHERE account='CASH') / 100` must equal the latest `cash_ledger.balance_after` to the cent, accounting for the `Initial funding` and `MANUAL_CORRECTION` rows being included in the postings sum.
4. **Closed trades with missing broker/cash confirmation:** explicit list of the 4 (or however many are confirmed at execution time) CLOSED trades lacking a `BROKER_SELL_FILLED` event — cross-referenced by ticker/id so Prof can independently verify against real broker records if desired.
5. **INTC timeline reconstructable:** see dedicated section below — this is the design's acid test.

## 8. Special INTC Handling (acid test for this design)

The INTC lot (legacy `trades.id=16`) is the single most information-dense row in the dataset — it alone should backfill into a **five-event chain**, not a single row, proving the design actually captures the incident's full history:

1. `BROKER_BUY_FILLED` — `occurred_at` = matched `cash_ledger` id 6 `ts` (2026-06-25 14:26:24), `broker_confirmed=1`, linked to the initial `PRINCIPAL`+`CASH` postings for the $1,002.10 debit.
2. `SELL_DECISION` — `occurred_at` = 2026-07-07 13:40:20 (the original stop-hit close per current `trades.updated_at` history — reconstructable only from the fact that this timestamp is known from prior P0K-1 audit evidence, not from the DB alone post-correction, since the DB no longer shows this intermediate state directly). **This is the one place the backfill design has a real limitation**: the DB's current state only shows the *final* CLOSED (post-correction, post-second-close) row — the original erroneous close and the correction are **not independently recoverable from `atlas.db` alone**; they exist only in this session's transcript and the `archive/atlas_db_*_p0k3_predeploy.bak.db` file. **Special handling: the INTC backfill will use the `p0k3_predeploy.bak.db` backup file as a secondary source** to reconstruct the true event chain (original SELL_DECISION+exception, MANUAL_CORRECTION+REVERSAL, second SELL_DECISION+BROKER_SELL_FILLED), rather than relying on the live DB alone — this is the one ticker where the backfill script needs a non-standard, manually-supplied historical source, and it should be flagged explicitly in the backfill run's output as `special_case='INTC_p0k_incident'`.
3. `RECONCILIATION_EXCEPTION` — dated 2026-07-07 (P0K-1 audit time), `cash_post_missing=1`, referencing the original close having no matching credit.
4. `MANUAL_CORRECTION` + `REVERSAL` pair — dated 2026-07-07 21:04:41 (P0K-3 write time), `prof_approved=1`, `evidence_id` pointing at a new `evidence_attachments` row summarizing the broker screenshot Prof provided plus a reference to the P0K-2/P0K-3 Markdown reports as `kind='system_log_excerpt'`.
5. `BROKER_SELL_FILLED` — `occurred_at` = 2026-07-07 17:10:22 UTC (the second, genuine stop-hit close, live-quote-confirmed per P0K-5), `broker_confirmed=0` still (since, per this session's own P0K-5 finding, **no matching cash_ledger credit exists yet even for this second close** — the backfill must NOT fabricate a confirmation that hasn't happened) — instead this becomes a `SELL_DECISION` only, with a fresh `RECONCILIATION_EXCEPTION` still open, exactly matching live reality as of P0K-5.

**This is the acid test because it's the one lot where naive backfill (read `trades` as-is) would silently produce a wrong, incomplete history — the design must explicitly special-case it using the backup file, or the backfill would misrepresent exactly the incident that motivated this whole project.**

## Summary

| Field | Value |
|---|---|
| P0L5_STATUS | BACKFILL_DESIGN_COMPLETE |
| backfill_mapping_plan | `trades`→`position_lots` (1:1, except VOIDED which map journal-only) + `portfolio_event_journal` (1-3 events per trade depending on broker confirmation); `cash_ledger`→`portfolio_event_journal`+`ledger_postings` (matched to trades via `broker_ref` substring, exact match only, no fuzzy matching); 2 rows (`Initial funding`, Prof manual correction) need special non-trade handling |
| ambiguity_flags | `inferred_decision` (100% of backfilled decisions), `broker_confirmed` (0/1, true source-of-truth flag), `cash_post_missing` (expected on 4 of 11 CLOSED rows), `timestamp_approximation` (59 no-broker_ref rows + any unmatched CLOSED), `cost_basis_estimated` (same 59-row set) |
| decimal_conversion_rules | `Decimal(str(x))` never `Decimal(x)`; cents = single final `ROUND_HALF_UP`; quantity/price via text+scaled-integer pairs with mandatory exact round-trip verification before acceptance |
| idempotency_key_rules | `sha256(event_type\|ticker\|broker_ref\|occurred_at)`, only for `BROKER_*_FILLED` events, NULL otherwise; pre-backfill collision dry-run required across the 11 broker_ref rows |
| invariant_checks_after_backfill | 6 WARN-mode checks: no_closed_without_sell_event, broker_fill_has_cash_posting, postings_balance_per_event, cash_post_missing_flagged (expect exactly 4), quantity_precision_roundtrip, dual_write_consistency |
| validation_report_plan | legacy vs new row counts; open-position ticker/quantity match; cash balance match to the cent; explicit list of CLOSED trades missing broker/cash confirmation; INTC 5-event timeline reconstruction proof |
| special_INTC_handling | Live `atlas.db` alone cannot reconstruct the pre-correction CLOSED state — backfill must additionally read `archive/atlas_db_20260707_2107_p0k3_predeploy.bak.db` to recover the true 5-event chain (BROKER_BUY_FILLED → SELL_DECISION → RECONCILIATION_EXCEPTION → MANUAL_CORRECTION/REVERSAL → SELL_DECISION), and must NOT fabricate a `BROKER_SELL_FILLED` for the second close since no matching cash credit exists yet per P0K-5 — that gap must be preserved as an open `RECONCILIATION_EXCEPTION`, matching current live reality |
| staging_backfill_ready | NO — 2 schema gaps found during this design pass (missing `ACCOUNT_OPENED`-equivalent event type for the "Initial funding" row; missing `MANUAL_ADJUSTMENT` posting_kind for the Prof balance-correction row) must be resolved — either by extending the P0L-4 schema's `CHECK` constraints in a follow-up staging-only DDL patch, or by an explicit decision to route these 2 rows differently — before backfill code can be written |
| risks_remaining | (1) The 2 schema gaps above block a clean backfill of all 21 cash_ledger rows as-is. (2) INTC's true pre-correction history depends on a backup file outside `atlas.db` — any future incident without an equivalent manually-created backup would not be as fully reconstructable; this is a process gap, not just a schema gap. (3) `postings_balance_per_event` (invariant #3) is flagged as the check most likely to surface real historical fee-attribution ambiguity in old free-text `notes` — some rows may need manual judgment calls, which should be logged as their own `MANUAL_CORRECTION`-with-evidence rows rather than silently adjusted. (4) 59 of 70 trades have no `broker_ref` at all (mostly `PENDING_FILL`) — these will backfill with `broker_confirmed=0` and `cost_basis_estimated=1` across the board, which is honest but means the backfilled journal will show the *majority* of historical activity as unconfirmed by design, not a defect but worth setting Prof's expectations on volume. |
| production changes | NONE |
