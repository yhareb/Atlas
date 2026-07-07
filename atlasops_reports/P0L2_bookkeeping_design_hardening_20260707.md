# P0L-2 READ-ONLY Bookkeeping Design Hardening

**Scope:** read-only design revision of the P0L-1 proposal. No schema created, no code written, no DB/strategy/TFE/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**P0L2_STATUS: HARDENING_COMPLETE — revised design, still pre-implementation**

## 1. Money-vs-Share Separation

**Gap in P0L-1:** `quantity` (shares) and money amounts (`amount`, `entry_price`, etc.) were both `REAL`, with no explicit unit/currency markers, and no protection against float-rounding drift in cash math (already a live risk — current `cash_ledger.amount` shows float noise like `-1002.0992289546`).

**Revision:**
- All **money** fields become `INTEGER` **cents** (e.g. `amount_cents`, `balance_after_cents`, `price_cents_per_share`) to eliminate float drift entirely. Display/report layers convert to dollars only at render time.
- All **share quantity** fields stay `REAL` (fractional shares are real in this account — e.g. `7.70534157` INTC) but get an explicit `quantity_precision` convention (store as-is, no rounding, since the broker itself uses high-precision fractional shares).
- Every money field carries an explicit `currency TEXT NOT NULL DEFAULT 'USD'` sibling column — even though everything today is USD, this prevents a silent unit-mixing bug if a non-USD instrument is ever added, and makes the schema self-describing rather than relying on a tribal-knowledge assumption.
- `ledger_postings.amount` → `amount_cents INTEGER NOT NULL` + `currency TEXT NOT NULL DEFAULT 'USD'`.

## 2. Cost Basis Tracking

**Gap in P0L-1:** `position_lots.entry_price` alone doesn't capture true cost basis (fees matter, and FIFO lot-splitting can create ambiguity about which fees belong to which sub-lot).

**Revision:** add explicit, always-computed-at-write-time fields to `position_lots`:
```
cost_basis_cents        INTEGER NOT NULL   -- (entry_price_cents * quantity) + entry_fees_cents, frozen at open
cost_basis_per_share_cents INTEGER NOT NULL -- cost_basis_cents / quantity, for FIFO-split fee attribution
```
These are **written once at lot-open time and never recomputed** — if entry data needs correction, that happens via the reversal model (§7), not by silently recalculating cost basis in place. This directly prevents a repeat of the ambiguity seen in the INTC incident, where it wasn't immediately obvious whether `$1,000 invested` already included the `$2.10` entry fee or not (it does, per `cash_ledger` row id 6, but this had to be manually verified rather than being a first-class field).

## 3. Realized vs Unrealized P/L

**Gap in P0L-1:** `position_lots.exit_price`/no realized_pnl field was mentioned only implicitly; unrealized P/L (needed for live reporting) was not addressed at all — this is exactly the gap that let the INTC $129.78/+0% fallback masquerade as a real unrealized figure.

**Revision:**
- `position_lots.realized_pnl_cents` — **NULL while OPEN**, written exactly once at the `BROKER_SELL_FILLED` (not `SELL_DECISION`) event, and never touched again. Realized P/L is only ever true once the broker has confirmed the fill — this is a deliberate design choice: Atlas's own `SELL_DECISION` is a forecast/intent, not yet a fact.
- **Unrealized P/L is never stored in `position_lots` at all.** It is computed transiently, on demand, from a new small table:
```
valuation_marks (
    id              INTEGER PRIMARY KEY,
    lot_id          INTEGER NOT NULL,       -- FK position_lots.id
    price_cents     INTEGER NOT NULL,
    price_source    TEXT NOT NULL,          -- 'live_provider' | 'entry_fallback' | 'broker_screenshot' | 'stale_cache'
    marked_at       DATETIME NOT NULL,
    is_fallback     INTEGER NOT NULL DEFAULT 0  -- explicit flag when price_source is NOT a genuine live quote
)
```
This is the single most important structural fix motivated by the INTC incident: **every price used for display must declare its own provenance and whether it's a fallback.** A report renderer that pulls `price_source='entry_fallback', is_fallback=1` can now explicitly render "price unavailable, showing entry as placeholder" instead of silently presenting a fallback as if it were live — which is exactly what produced the misleading "+0%" report line.

## 4. Fees and FX/Currency Fields

**Gap in P0L-1:** fees existed only as a lump `entry_fees`/`exit_fees` on the old `trades` shape; no currency/FX modeling at all.

**Revision:**
- `ledger_postings` gets a dedicated `posting_kind TEXT NOT NULL` enum: `'PRINCIPAL' | 'FEE' | 'REALIZED_PNL' | 'FX_ADJUSTMENT'` — fees are now their own postings, not folded into the principal amount, so a report can answer "how much have we paid in fees on this ticker, ever" with a simple query instead of parsing free-text notes.
- Every money-bearing table gets `currency TEXT NOT NULL DEFAULT 'USD'` (per §1). An `fx_rate_to_usd REAL DEFAULT 1.0` column is added to `ledger_postings` for future-proofing, defaulting to 1.0 for the all-USD present, with a note that this field is unused/inert until a non-USD instrument is ever introduced (out of scope for the current account).

## 5. Idempotency Keys for Broker Fills and Retries

**Gap in P0L-1:** no protection against the same broker screenshot/notification being ingested twice (e.g. Prof re-sends a screenshot, or a retry after a transient DB error re-runs the same insert), which would double-post cash and corrupt the ledger.

**Revision:** `portfolio_event_journal` gets:
```
idempotency_key   TEXT UNIQUE   -- e.g. sha256(event_type + ticker + broker_ref + occurred_at)
```
with a `UNIQUE` constraint. Any ingestion path (manual broker-ingest, future automation) computes this key deterministically before insert; a duplicate insert attempt fails cleanly (caught and logged as a no-op, not a silent double-post) rather than creating a second `BROKER_SELL_FILLED` event and a second `CASH_CREDIT_POSTED` for the same real-world fill. This is a direct hardening against a realistic near-term failure mode, not a hypothetical one — Prof has already sent broker screenshots multiple times across this engagement for different tickers.

## 6. Event Ordering: occurred_at vs recorded_at vs effective_at

**Gap in P0L-1:** only `occurred_at` and `recorded_at` were defined; no way to represent "this correction should be treated, for accounting purposes, as if it happened at time T even though we're recording it now" — exactly the INTC correction scenario (P0K-3's write landed at 21:04:41, but conceptually it was "un-doing" an error that existed since 13:40:20).

**Revision:** add a third timestamp:
```
effective_at    DATETIME NOT NULL   -- the timestamp this event should be treated as occurring at, for
                                     -- ordering/reporting/reconciliation purposes. Defaults to occurred_at.
                                     -- Only diverges from occurred_at for MANUAL_CORRECTION/REVERSAL events,
                                     -- which may need to be effective as of an earlier point in the timeline.
```
Semantics:
- `occurred_at`: best estimate of when the real-world thing happened (broker fill time, stop-hit detection time).
- `recorded_at`: wall-clock time Atlas actually wrote the row — **immutable, always `CURRENT_TIMESTAMP` at insert, never backdated.** This preserves a truthful record of when AtlasOps/Atlas actually took action, which matters for exactly the kind of "was this correction applied before or after the next scheduled cycle" timing analysis done in P0K-4/P0K-5.
- `effective_at`: the timestamp used when *ordering* events for `position_lots` derivation and reports — lets a correction properly slot into its logical place in history without lying about when it was actually recorded.

All derivation/rebuild logic for `position_lots` sorts by `effective_at`, not `recorded_at` — so a late-arriving correction reconstructs history correctly rather than just appending at the end.

## 7. Correction/Reversal Model

**Gap in P0L-1:** `MANUAL_CORRECTION` was defined as a single event type with a `supersedes_id` pointer, but didn't specify *how* the correction actually undoes prior postings — risking silent double-counting if implemented naively (e.g. if a correction just posts new numbers without first reversing the old ones).

**Revision — proper accounting reversal pattern, no edits, ever:**
1. A correction is **always** modeled as exactly two new journal events, never one:
   - `REVERSAL` — posts the exact negation of every `ledger_postings` row tied to the event being corrected (this is new: `REVERSAL` added to the event-type vocabulary, see §revised_event_types). `REVERSAL.supersedes_id` = the original event's id.
   - The corrected replacement event (e.g. a fresh `POSITION_STATUS_CORRECTED` or the original event type re-posted with right values) — `linked_reversal_id` pointing at the `REVERSAL` row.
2. This guarantees **the sum of all postings for a ticker, across all time, always reflects reality** — nothing is ever silently overwritten; the full CLOSED→REVERSAL→OPEN→[later]→CLOSED chain for INTC would show as four clean, individually-inspectable rows instead of one row mutated three times with only Markdown reports and `.bak.db` files as the human-reconstructed history.
3. `prof_approved` and `evidence_id` are required (`NOT NULL`) specifically on `REVERSAL` and `MANUAL_CORRECTION` rows — enforced via a `CHECK` constraint once out of warning mode (§9), not just convention.

## 8. Exact Report Body Snapshots

**Gap in P0L-1:** `report_snapshots.holdings_json` stored a *parsed* representation, not the literal text — insufficient for "what did the report actually say" forensics (exactly the kind of question asked in P0H-1's stale-IRDM-report investigation, which ended UNDETERMINED partly for lack of this).

**Revision:**
```
report_snapshots (
    id                  INTEGER PRIMARY KEY
    report_type         TEXT NOT NULL
    generated_at         DATETIME NOT NULL
    raw_body_text        TEXT NOT NULL      -- the exact literal message body sent (or would-be-sent in dry-run)
    raw_body_sha256       TEXT NOT NULL      -- hash for fast dedup/diff comparisons across cycles
    inputs_manifest_json  TEXT NOT NULL      -- {lot_id: {price_source, price_cents, is_fallback, event_id_used}, ...}
    telegram_message_id   TEXT
    dry_run              INTEGER NOT NULL DEFAULT 0
)
```
The `inputs_manifest_json` is the critical addition beyond P0L-1: for every ticker shown in the report, it records **exactly which `valuation_marks` row (and thus which `price_source`/`is_fallback` flag) was used to render that line.** This makes the P0K-4 root-cause ("the report displayed an entry-fallback price as if live") mechanically detectable by a simple query (`SELECT * FROM report_snapshots WHERE inputs_manifest_json LIKE '%is_fallback":1%'`) instead of requiring a multi-step manual log-archaeology audit.

## 9. Invariant Checks in Warning Mode Before Enforcement

**Gap in P0L-1:** invariants were listed as rules but with no defined mechanism for how they'd be checked or what happens on violation — risking either silent non-enforcement or, worse, a hard failure that blocks legitimate production activity the first time an edge case is hit.

**Revision:** every invariant from P0L-1/this hardening pass runs in one of two modes, tracked explicitly:
```
invariant_checks (
    id              INTEGER PRIMARY KEY
    invariant_name  TEXT NOT NULL         -- e.g. 'no_closed_without_sell_event'
    mode            TEXT NOT NULL         -- 'WARN' | 'ENFORCE'
    checked_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    subject_type    TEXT NOT NULL         -- 'lot' | 'event' | 'account'
    subject_id      INTEGER NOT NULL
    passed          INTEGER NOT NULL
    detail          TEXT
)
```
**Every invariant starts in `WARN` mode.** A background check (run read-only, on a schedule or after each dual-write) evaluates each invariant and logs a row — pass or fail — without ever blocking a real write. Only after a defined bake-in period with **zero unexplained WARN failures** does Prof decide, per-invariant, whether to promote it to `ENFORCE` (where a violation would raise/reject the writing transaction). This directly avoids two failure modes: (a) invariants that are too strict for a real edge case Prof hasn't foreseen yet, and (b) invariants that silently rot into no-ops because nobody's watching them — the `invariant_checks` table makes every check's history queryable and reviewable before any enforcement decision.

## 10. Compatibility with Existing `trades`/`cash_ledger` During Dual-Write

**Gap in P0L-1:** dual-write was mentioned as the migration strategy but without a concrete cross-reference mechanism to verify the two representations stay in agreement.

**Revision:**
- `portfolio_event_journal` and `position_lots` both get nullable legacy pointers:
```
legacy_trades_id       INTEGER    -- FK to existing trades.id, when this event/lot corresponds to one
legacy_cash_ledger_id  INTEGER    -- FK to existing cash_ledger.id, for CASH_* events
```
- A read-only **consistency-check job** (itself just another `WARN`-mode invariant per §9: `dual_write_consistency`) periodically compares: for every `trades` row, does a `position_lots` row with matching `legacy_trades_id` exist with the same `status`/`exit_price`/`realized_pnl`? For every `cash_ledger` row, does a `ledger_postings` row with matching `legacy_cash_ledger_id` exist with the same signed amount? Any drift is logged to `invariant_checks` as a WARN failure — giving an early, queryable signal if the dual-write shim (built in P0L-1's Phase 2) ever falls out of sync with the legacy tables, well before any cutover is considered.
- Legacy tables (`trades`, `cash_ledger`) remain the **system of record** for all existing report/reconciliation code throughout the dual-write period — the new tables are purely additive telemetry until Phase 5 (a separately-approved future step per P0L-1 §Staging Plan).

## Summary

| Field | Value |
|---|---|
| P0L2_STATUS | HARDENING_COMPLETE |
| schema_changes_required | 10 categories of revision — cents-based money fields + currency columns; explicit cost-basis fields frozen at open; realized P/L only at broker-confirmed close, unrealized moved to a separate `valuation_marks` table with mandatory `price_source`/`is_fallback`; `posting_kind` split for fees; `idempotency_key` unique constraint; added `effective_at`; reversal-pair correction model (no in-place edits); `report_snapshots` gets literal `raw_body_text` + per-line `inputs_manifest_json`; new `invariant_checks` WARN/ENFORCE table; `legacy_trades_id`/`legacy_cash_ledger_id` cross-references + `dual_write_consistency` check |
| revised_tables | `portfolio_event_journal` (+idempotency_key, +effective_at, +legacy_trades_id/legacy_cash_ledger_id, +linked_reversal_id), `ledger_postings` (+posting_kind, +currency/fx_rate_to_usd, cents-based), `position_lots` (+cost_basis_cents/cost_basis_per_share_cents, realized_pnl_cents only at broker-confirm), `valuation_marks` (NEW — price provenance/fallback flag), `broker_reconciliation` (unchanged from P0L-1), `report_snapshots` (+raw_body_text, +raw_body_sha256, +inputs_manifest_json), `evidence_attachments` (unchanged), `invariant_checks` (NEW — WARN/ENFORCE audit table) |
| revised_event_types | Original 9 from P0L-1 retained, plus: `REVERSAL` (negates a prior event's postings, paired with every correction), `VALUATION_MARK_RECORDED` (logs a price provenance event, ties to `valuation_marks`), `IDEMPOTENT_DUPLICATE_REJECTED` (records a rejected duplicate ingestion attempt for audit visibility rather than silent drop) |
| revised_invariants | Original 7 from P0L-1 retained (now explicitly WARN-mode by default per §9), plus: (8) every `ledger_postings` row must carry a `posting_kind` and balance within its `posting_kind` groupings, not just in aggregate; (9) every report-displayed price must have a `valuation_marks` row with `is_fallback` explicitly set — a report may never display a price with unknown/undeclared provenance; (10) every `MANUAL_CORRECTION`/`REVERSAL` pair must net to zero across all affected accounts; (11) `dual_write_consistency` — legacy and new representations must agree for every mirrored row, checked continuously in WARN mode throughout the dual-write period |
| warning_mode_checks | All invariants (original 7 + new 4 = 11 total) start in WARN mode via `invariant_checks`; promotion to ENFORCE is a separate, per-invariant, Prof-approved decision made only after a defined zero-failure bake-in period; `dual_write_consistency` specifically is expected to remain WARN-only for the entire dual-write phase (never enforced, since legacy tables remain system-of-record) |
| staging_schema_ready | NO — hardened design is ready for Prof review and sign-off, but no DDL has been drafted or run; per standing protocol the next step is a staging-only `/tmp` DB implementation (P0L-1 §Staging Plan Phase 1) only after this hardening pass is explicitly approved |
| risks_remaining | (1) Backfilling `effective_at`/`occurred_at` for ~70 pre-existing `trades` rows will require judgment calls where the original event stream is genuinely ambiguous (e.g. rows with only a single timestamp and no distinguishable "decision vs confirmation" moment) — some backfilled rows will carry a documented `occurred_at ≈ recorded_at` approximation flag rather than a true reconstruction. (2) `run_exits()`/`atlas_portfolio.py` is protected and cannot be modified to natively emit `SELL_DECISION`/`STOP_HIT_DETECTED` events without a Prof-authorized alpha-adjacent work order — Phase 2's dual-write shim can only wrap call sites in the non-protected `atlas_db.py`/`atlas_intraday.py`, meaning some event provenance will initially be inferred post-hoc from `trades` row changes rather than captured natively at decision time. (3) Cents-based money migration requires a one-time, carefully-verified conversion of all existing float `cash_ledger.amount`/`trades.entry_price` values to integer cents without introducing new rounding error — needs its own dedicated verification pass (before/after totals must match to the cent) during Phase 1 backfill. (4) `idempotency_key` design assumes broker_ref values are unique per real-world fill; needs confirmation this holds for partial fills / multi-tranche broker orders before the UNIQUE constraint is finalized. |
| production changes | NONE |
