# P0L-3 READ-ONLY Precision Hardening Before Staging DDL

**Scope:** read-only design revision. No schema created, no code written, no DB/strategy/TFE/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**P0L3_STATUS: PRECISION_HARDENING_COMPLETE — design only, still pre-implementation**

## Problem Confirmed

**precision_issue_confirmed: YES.**

P0L-2 moved all money fields to integer cents, correctly eliminating float drift for cash accounting — but left `quantity` as `REAL` for share counts. This is a real defect for this account specifically: broker fractional shares like `7.70534157` (INTC), `20.97462` (ABNB), `8.75657` (BAC) are exact decimal values as reported by the broker, and storing them in IEEE-754 double-precision float risks silent representation drift (e.g. `7.70534157` may not round-trip exactly through float arithmetic, and repeated read-modify-write cycles — exactly what today's mutable `trades.quantity` undergoes across FIFO lot-splits — compound that drift). The existing production DB already exhibits float-noise symptoms in the money domain (`cash_ledger.amount = -1002.0992289546`), and there is no reason to assume share quantities are immune to the same class of bug once arithmetic (partial sells, FIFO splits) is applied to them. This must be fixed before any staging DDL is drafted, not after.

## 1. Revised Quantity Fields

Replace every `REAL` quantity column across `position_lots`, and any journal/posting payload that carries share counts, with a four-column exact-representation group:

```
quantity_text     TEXT NOT NULL      -- raw decimal string exactly as received from the broker/source,
                                       -- e.g. '7.70534157' — never parsed to float, stored verbatim
quantity_scaled   INTEGER NOT NULL   -- quantity_text converted to a fixed-point integer, e.g. 770534157
quantity_scale    INTEGER NOT NULL   -- the scale denominator, e.g. 100000000 (10^8)
                                       -- quantity_scaled / quantity_scale == the exact decimal value
quantity_source   TEXT NOT NULL      -- 'broker_fill' | 'atlas_decision_estimate' | 'manual_correction'
```

Rules:
- **`quantity_scale` is fixed at `100000000` (10^8) account-wide**, chosen because it comfortably covers the observed broker precision (8 decimal places, e.g. `7.70534157`) with headroom, and matches common fractional-share broker precision conventions. This is stored per-row (not just as a global constant) so that if a future broker/instrument ever needs a different scale, historical rows remain self-describing and correctly interpretable without a silent global-assumption break.
- **`quantity_scaled` is computed via exact string/integer arithmetic only** (e.g. Python's `Decimal`, never `float()`), directly from `quantity_text`, at write time. `quantity_scaled` is the field all arithmetic (FIFO splits, sums, comparisons) operates on — as integers, exactly, with no float ever entering the calculation path.
- **`quantity_text` is the audit/display source of truth** — whenever a report or reconciliation needs to show "quantity" to a human, it renders from `quantity_text` (or from `quantity_scaled`/`quantity_scale` reconstructed as a `Decimal`, never as a `float`).
- FIFO lot-splitting (splitting `quantity_scaled` when a partial sell occurs) is pure integer subtraction — `remaining_scaled = original_scaled - sold_scaled`, with both operands and the result always expressible exactly at the fixed scale, so no rounding ever occurs in the split itself.

## 2. Broker Raw Fields for Audit

Add unconditionally to every event/lot row that originates from or is confirmed by a broker source (`BROKER_BUY_FILLED`, `BROKER_SELL_FILLED`, `broker_reconciliation`):

```
broker_quantity_text   TEXT   -- exact string as it appeared in the broker screenshot/notification/API payload
broker_price_text      TEXT   -- exact string, e.g. '129.78' or a higher-precision value if the broker ever
                                -- reports one, preserved verbatim
broker_amount_text     TEXT   -- exact total-amount string as stated by the broker (e.g. "invested $1,000.00"),
                                -- kept separately from any Atlas-computed amount so the two can be diffed
```

These are **never parsed into computed fields automatically** — they exist purely as an immutable, verbatim record of what the broker actually said, independent of whatever `quantity_scaled`/`price_micros`/`cost_basis_cents` values Atlas derives from them. This directly serves the P0K-1/P0K-4 pattern: when a broker screenshot and Atlas's DB disagree, having the *exact original broker text* preserved (not just Atlas's parsed interpretation of it) makes reconciliation audits strictly more reliable — nothing is lost in translation at ingest time.

## 3. Price Precision

**Do not force per-share prices into cents.** Cents-only pricing loses precision for any provider/broker that reports sub-cent prices (uncommon for US equities today, but real for some ETFs, most crypto/FX-adjacent instruments, and some broker mid-price/average-cost displays) — and forcing a lossy round at ingest time destroys the ability to later detect that loss.

**Revision — dual representation, same pattern as quantity:**
```
price_micros       INTEGER NOT NULL   -- price in millionths of a dollar (10^-6), e.g. $129.78 -> 129780000
price_decimal_text TEXT NOT NULL      -- raw decimal string exactly as received, e.g. '129.78'
```
Rules:
- `price_micros` is the **calculation-safe integer representation** used for all arithmetic (multiplying by `quantity_scaled` to derive cost basis, comparing against `stop_loss`/`target_price`, etc.) — chosen at micro-dollar (10^-6) granularity rather than cents specifically *because* it must support sub-cent precision if a provider ever supplies it, while still being an exact integer for all currently-observed 2-decimal-place US equity prices (e.g. `129.78` → exactly `129780000`, no rounding).
- `price_decimal_text` is the **verbatim audit/display source**, exactly as ingested, never reconstructed lossily from `price_micros` for display purposes (though reconstructing `price_micros / 1_000_000` as a `Decimal` for display is safe and exact for the common case — the point is `price_decimal_text` is authoritative and doesn't depend on that reconstruction being bug-free).
- `stop_loss`, `target_price`, and every other per-share price column across `position_lots` follows the same `*_micros` + `*_decimal_text` pair pattern for consistency — no column is left as a bare float or a bare cents-only integer.

## 4. Settlement/Provenance Rule (formalized)

**calculation_rules — three explicit, non-overlapping rules:**

1. **Cash/accounting settles in cents.** Every `ledger_postings.amount_cents` and every account-level balance (`cash_ledger`-equivalent) is integer cents — this remains unchanged from P0L-2 and is correct, because real-world cash settlement (what actually moves between bank/broker/Atlas's tracked balance) is genuinely cents-precision; there is no legitimate sub-cent cash movement to preserve.
2. **Broker quantities and per-share prices preserve exact raw decimal provenance**, via the `*_text` + scaled-integer pairs in §1/§3 — because these are *inputs* to accounting math, not the settled cash result itself, and the broker's own precision (up to 8 decimals for shares, arbitrary decimals for price) must not be pre-emptively truncated before Atlas has a chance to compute against it exactly.
3. **`cost_basis_cents` is derived from broker amount/fee totals, never recomputed from `price_micros × quantity_scaled` float-adjacent math.** Specifically:
   ```
   cost_basis_cents = round_to_cents(broker_amount_text_as_decimal) + entry_fees_cents
   ```
   using `Decimal` string-based parsing of `broker_amount_text` (never `float(broker_amount_text)`), with **explicit, single, final rounding to cents only at this last step** — not before, and not in intermediate calculations. This directly matches how the real INTC entry was recorded: broker stated "invested $1,000.00" (a cents-exact figure) even though `quantity × price` computed from the individual share/price fields (`7.70534157 × 129.78`) would need to round to reach that same $1,000.00 — the broker's own stated total is authoritative for `cost_basis_cents`, not Atlas's recomputation from the finer-grained fields. If the two disagree by more than a defined tolerance (e.g. $0.01), that discrepancy itself becomes a `RECONCILIATION_EXCEPTION` event rather than being silently absorbed by picking whichever number Atlas prefers.

## 5. Updated Schema Safety Confirmation

**staging_schema_ready: YES** — with the quantity and price precision model above incorporated, the design is now internally consistent for a staging-only DDL draft:
- No `REAL`/float columns remain anywhere in the money or share-quantity domain of the proposed schema (`portfolio_event_journal` payload fields, `ledger_postings`, `position_lots`, `valuation_marks`, `broker_reconciliation`) — every quantity/price/money field is either an exact integer (cents, micros, or scaled-quantity) or a verbatim `*_text` string, with `Decimal`-based (never `float`-based) conversion between them enforced as an implementation rule for Phase 1.
- The three-rule settlement/provenance split in §4 gives implementers of the Phase 1 backfill script (P0L-1 staging plan) an unambiguous, testable procedure for converting the ~70 existing `trades` rows and ~21 `cash_ledger` rows without introducing new rounding error — each legacy float value gets parsed via `Decimal(str(value))` (not `Decimal(value)`, which would inherit the float's own imprecision) as an interim step, then converted to the appropriate scaled-integer/cents/micros representation, with a mandatory before/after total-value cross-check (§remaining_risks #1).
- This does not yet constitute schema creation — no DDL has been drafted or executed. "Ready" here means the design is suffiently precise and internally consistent to *begin* drafting staging DDL in `/tmp`, pending your explicit go-ahead, per the standing staging-first protocol.

## Summary

| Field | Value |
|---|---|
| P0L3_STATUS | PRECISION_HARDENING_COMPLETE |
| precision_issue_confirmed | YES — float `REAL` for fractional broker share quantities is unsafe for bookkeeping, same class of defect already visible in existing `cash_ledger.amount` float noise |
| revised_quantity_fields | `quantity_text` (verbatim broker decimal string), `quantity_scaled` (exact fixed-point integer), `quantity_scale` (per-row scale denominator, default 10^8), `quantity_source` (provenance tag) — replaces all `REAL` quantity columns; all arithmetic (FIFO splits, sums) operates only on `quantity_scaled` as integers |
| revised_price_fields | `price_micros` (integer, 10^-6 precision, calculation-safe) + `price_decimal_text` (verbatim broker/provider string) pair, applied uniformly to every per-share price column (entry, exit, stop_loss, target_price, valuation_marks price) |
| revised_money_fields | Unchanged from P0L-2: all cash/ledger amounts remain integer cents (`amount_cents`, `balance_after_cents`, `cost_basis_cents`) — confirmed correct, since real cash settlement is genuinely cents-precision; `cost_basis_cents` derivation rule tightened per §4 rule 3 |
| calculation_rules | (1) cash settles in cents; (2) broker quantities/prices preserve exact raw decimal provenance via text+scaled-integer pairs, never pre-truncated; (3) `cost_basis_cents` derives from broker-stated amount totals (Decimal-parsed, single final cents rounding) plus fee cents — never recomputed from `price × quantity` float-adjacent math; disagreement beyond tolerance becomes a `RECONCILIATION_EXCEPTION`, not a silently-picked value |
| staging_schema_ready | YES — precision model is now internally consistent and safe to begin staging-only DDL drafting in `/tmp`, pending explicit approval to proceed to P0L-1's Phase 1 |
| remaining_risks | (1) Backfill of ~70 existing float `trades.quantity`/`entry_price` and ~21 `cash_ledger.amount` rows must use `Decimal(str(x))` conversion with a mandatory before/after total cross-check to cent-level precision — a naive `Decimal(x)` on the raw float would re-inherit the existing imprecision instead of fixing it. (2) `quantity_scale = 10^8` is an assumption based on observed broker precision (8 decimals) in this account's existing data — if a future broker/instrument reports finer precision, the fixed 10^8 scale (though stored per-row and technically adjustable) would need a deliberate decision to raise the default, not an automatic one. (3) The `cost_basis_cents`-from-broker-amount rule (§4.3) depends on `broker_amount_text` reliably being present and correctly transcribed at ingest time (from screenshots or manual entry) — if it's ever missing, cost basis would need to fall back to `price_micros × quantity_scaled` with a `cost_basis_source='estimated'` flag, and that fallback path itself needs the same is-this-a-fallback transparency treatment already designed for `valuation_marks.is_fallback` in P0L-2. (4) `atlas_portfolio.py`/`atlas_engine.py` remain protected and cannot be modified to natively emit scaled-integer quantities at decision time — Phase 2's dual-write shim will need to convert `float` values coming out of the protected files' existing return values via `Decimal(str(x))` at the boundary, which is safe but means the *protected* engine's internal math still runs in float; the new precision model only guarantees exactness from that boundary onward, not inside protected files, which is out of scope per the access boundary. |
| production changes | NONE |
