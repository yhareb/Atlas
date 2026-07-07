# P0L-8 — Read-Only Dual-Write Design for the Bookkeeping Schema (Evidence)

**Date:** 2026-07-07
**Scope:** READ-ONLY DESIGN ONLY. No production or staging DB write. No code
change. No patch. No deploy. Builds directly on the P0L-7 backfill results
(85 journal events / 67 lots / 49 postings / 8 WARN exceptions produced
cleanly against a copy).

## 1. System-of-record boundary (unchanged, explicit)

`trades`, `cash_ledger`, `account` remain the **sole system of record**. Every
report, exit decision, P/L calculation, and broker reconciliation continues
to read from these three tables exactly as today. The 8 bookkeeping tables
(`portfolio_event_journal`, `position_lots`, `ledger_postings`,
`valuation_marks`, `broker_reconciliation`, `report_snapshots`,
`evidence_attachments`, `invariant_checks`) are **additive telemetry only** —
a parallel, derived, non-authoritative shadow ledger. If the two ever
disagree, legacy wins, and the disagreement itself becomes a
`RECONCILIATION_EXCEPTION` row, never a legacy overwrite.

## 2. Safe, non-protected write boundaries identified

All 4 requested boundaries exist in code already inspected read-only (no
protected files touched):

| Boundary | Location | What it does today |
|---|---|---|
| Cash writes | `atlas_db.py::_append_cash_ledger(cursor, amount, reason)` (line 334) | Single-sided INSERT into `cash_ledger`, called from `confirm_trade_fill()` (broker buy) and `close_trade_broker_confirmed()` (broker sell) |
| Broker ingest confirmations | `atlas_db.py::confirm_trade_fill()` (line 374, buy leg) and `close_trade_broker_confirmed()` (line 548, sell leg) | UPDATE `trades` row to OPEN/CLOSED + calls `_append_cash_ledger()` |
| Report render snapshot persistence | `atlas_intraday.py::_build_report()` (report assembly, before Telegram send) | Currently builds the message text in memory only; no persistence today — this is a **net-new** hook point, not a modification of existing logic |
| Manual correction path | Currently ad hoc: Prof-directed manual `cash_ledger` INSERT (e.g. the P0K-2/P0K-3 pattern: staged review → production write under a DB transaction with busy-timeout) | No dedicated function today; corrections are one-off scripted writes reviewed and applied per-incident |

None of these touch `atlas_engine.py` or `atlas_portfolio.py`. `atlas_intraday.py`
already imports `atlas_db` and calls report-render functions; adding a
snapshot-persistence call after `_build_report()` completes (before/alongside
the existing Telegram send, dry-run-safe) requires no engine/portfolio
change.

## 3. Protected-files-untouched plan

- `atlas_engine.py`, `atlas_portfolio.py`: **zero changes, zero new imports,
  zero call sites added.** All dual-write hooks live in `atlas_db.py` (data
  layer) and `atlas_intraday.py` (report layer), both already non-protected
  and already the natural owners of cash/trade writes and report rendering
  respectively.
- Verification plan for any future staging patch: `grep -c` "atlas_engine\|atlas_portfolio" import lines in the diff of `atlas_db.py`/`atlas_intraday.py` before/after — must be identical count. AST-level check that no new call sites reference engine/portfolio internals.
- The manual-correction path is proposed as a **new small helper** in
  `atlas_db.py` (not a protected file) — see §5.

## 4. Dual-write event emission plan

Each dual-write hook wraps the **existing** legacy write in a try/except and
appends a bookkeeping write **after** the legacy write commits successfully
(never before — legacy is always the leading writer):

| Legacy event | Hook point | Bookkeeping emission |
|---|---|---|
| Broker buy fill | `confirm_trade_fill()`, immediately after `_append_cash_ledger()` returns and `conn.commit()` | `portfolio_event_journal` (`BROKER_BUY_FILLED`) + 2-leg `ledger_postings` (`CASH` / `POSITION:<TICKER>`), using the broker's stated cash amount (not `qty*price`) — same rule proven in P0L-7 |
| Broker sell fill | `close_trade_broker_confirmed()`, immediately after its `_append_cash_ledger()` commit | `portfolio_event_journal` (`BROKER_SELL_FILLED`) + 3-leg `ledger_postings` (`CASH` / `POSITION:<TICKER>` / `REALIZED_PNL`) |
| Manual correction | New `atlas_db.py::record_manual_cash_correction(amount, reason)` helper (wraps today's ad hoc pattern) | `portfolio_event_journal` (`MANUAL_CORRECTION`, `prof_approved=1` — only settable by the Prof-invoked path, never automated) + 2-leg `ledger_postings` (`CASH` / `SUSPENSE:MANUAL_ADJUSTMENT`) |
| Cash adjustment (non-trade, e.g. future fee/interest) | Same `_append_cash_ledger()` call site, tagged by `reason` pattern-matching (mirrors the P0L-7 backfill matcher logic) | `portfolio_event_journal` (`CASH_DEBIT_POSTED` / `CASH_CREDIT_POSTED`) + matching 2-leg posting |
| Report snapshot | `atlas_intraday.py::_build_report()`, after message text is finalized, before/alongside Telegram send | `report_snapshots` row: literal `raw_body_text`, `raw_body_sha256`, `inputs_manifest_json` (per-line price provenance), `dry_run` flag mirrored from the run's own dry-run state |
| Valuation mark | `atlas_intraday.py::_cache_open_trade_prices()` (existing display-cache call, live-only per the P0C/P0D dry-run guard already established) | `valuation_marks` row: `price_micros`, `price_source`, `is_fallback` — this is the **direct fix target** for the P0K-4 entry-price-fallback bug: the emission point must read whatever `price_source` the price actually came from (`live_provider` vs `entry_fallback`) and never default silently |

## 5. Idempotency behavior for retries

- Every emission carries a deterministic `idempotency_key`, built the same
  way P0L-7's backfill built its keys: `live_<table>_<legacy_id>_<leg>` (e.g.
  `live_trade_91_buy`), so a retried call (crash after legacy commit, before
  bookkeeping commit, then re-invoked) produces the **same** key.
- `ledger_postings` inherits idempotency via its `event_id` FK — a duplicate
  event insert is rejected by the `idempotency_key UNIQUE` constraint before
  any posting is attempted, so postings can never be double-counted.
- On `UNIQUE` constraint violation, the dual-write wrapper catches it, logs
  `IDEMPOTENT_DUPLICATE_REJECTED` (already in the P0L-6 event_type vocabulary)
  and returns success — the retry is treated as a no-op, not an error.
- Report snapshots key off `raw_body_sha256` + `report_type` + rendering
  timestamp truncated to the report cycle — a re-render producing identical
  text in the same cycle is deduped; a genuinely different render (e.g.
  price changed) gets a new row, which is correct (it's a new fact, not a
  duplicate).

## 6. Failure-mode and recovery plan

| Failure mode | Behavior |
|---|---|
| Legacy write succeeds, bookkeeping write fails | **Never blocks or rolls back the legacy write.** Bookkeeping write is wrapped in its own try/except *outside* the legacy transaction; a failure is caught, logged (non-fatal), and the run continues. This is the single most important invariant: bookkeeping is telemetry, and telemetry must never be able to break trading. A missing bookkeeping row for a known legacy event is auto-detected later by a reconciliation sweep (compare `trades`/`cash_ledger` id coverage against `legacy_trades_id`/`legacy_cash_ledger_id` FKs in the journal) and backfilled retroactively using the same idempotent keying — no data is lost, just delayed. |
| Bookkeeping write succeeds, legacy write fails | Cannot happen by construction: the bookkeeping call only fires *after* the legacy `conn.commit()` returns successfully. If the legacy write itself fails (exception before commit), the dual-write hook is never reached. |
| Invariant WARN failure | WARN mode never blocks, never raises, never alters behavior — it only inserts a row into `invariant_checks` with `passed=0` and a human-readable `detail`. WARN failures accumulate for periodic review (e.g. a daily cron summarizing `invariant_checks WHERE passed=0 AND checked_at > cutoff`); promotion of any single invariant to `ENFORCE` mode (which *would* reject writes) is a separate, explicit, per-invariant Prof-approved step — never automatic, never bundled with dual-write rollout. |

## 7. Rollback and replay strategy

- **Rollback:** the dual-write layer is purely additive — rolling back means
  reverting the `atlas_db.py`/`atlas_intraday.py` diff (restoring the
  pre-dual-write backup) and optionally truncating the 8 bookkeeping tables
  (safe, since legacy tables never depended on them). No legacy data is ever
  at risk because legacy writes are never made conditional on bookkeeping
  success.
- **Replay:** the exact P0L-7 backfill script becomes the replay tool. If
  dual-write was down for a period (bookkeeping write failures, or the
  feature was rolled back and later re-enabled), rerunning the backfill
  against the current legacy state re-derives every bookkeeping row using
  the same idempotent keys — already-present rows are skipped via the
  `UNIQUE` constraint, missing rows are filled in. This makes the backfill
  script dual-purpose: initial migration tool *and* gap-healing replay tool.

## 8. Staging-only test plan (required before any production approval)

1. Copy `atlas.db` → fresh `/tmp` copy, apply P0L-6 DDL (established pattern).
2. Stage the dual-write diff to `atlas_db.py`/`atlas_intraday.py` copies under
   `/tmp/p0l9_staging/` (next task number) — never edit the production files
   directly.
3. Compile-check both staged files.
4. Run staged `confirm_trade_fill()` / `close_trade_broker_confirmed()`
   against the copied DB with synthetic fill data — assert: (a) legacy
   `trades`/`cash_ledger` rows land exactly as today (byte-identical to a
   run of the *unmodified* function), (b) matching `portfolio_event_journal`
   + `ledger_postings` rows appear, balanced to 0 cents.
5. Force a bookkeeping-write exception (e.g. temporarily drop a bookkeeping
   table in the copy) and confirm the legacy write still lands and no
   exception propagates to the caller.
6. Call the same fill function twice with identical arguments (retry
   simulation) — confirm exactly one set of bookkeeping rows exists
   (idempotency proof) while the legacy write behavior matches today's
   (i.e., don't change legacy duplicate-call semantics, only bookkeeping's).
7. Run the P0L-7 backfill script against the same copy afterward — confirm
   it recognizes the dual-written rows (same idempotency keys) and inserts
   nothing new for them, only for any still-missing legacy history.
8. Full `PRAGMA integrity_check` + `foreign_key_check` after all of the above.
9. Report staged diff, compile results, and all assertions to Prof for
   explicit review before any production file is touched — per the standing
   Staging-First Protocol.

## Migration risk

**LOW.** Unlike a big-bang schema cutover, this design keeps legacy as sole
system of record indefinitely; bookkeeping writes are non-blocking,
idempotent, and replay-healable. The only meaningful risk is the **new**
report-snapshot hook point in `atlas_intraday.py`, since it's the one place
touching an already-live, frequently-executed script — mitigated by gating
it behind the existing dry-run/live distinction (mirroring the P0C/P0D
price-cache guard already established) so staging validation never risks
writing snapshot rows during a live production cycle before Prof approval.

## Conclusion

Dual-write design is complete and staging-ready. All four requested boundary
points are the *existing*, already-inspected, non-protected write sites in
`atlas_db.py` and `atlas_intraday.py`. No protected file is touched by this
design. No code has been written yet — this is the design/audit only, per
the READ-ONLY scope of P0L-8.
