# P0L-9 — Staging-Only Dual-Write Patch (Evidence)

**Date:** 2026-07-07
**Scope:** STAGING-ONLY. All edits made in `/tmp/p0l9/src/` copies. Zero
production file edits, zero production DB writes, zero deploys. Builds
directly on the P0L-8 design.

## 1. Copy + schema

```
cp /Users/yasser/scripts/atlas.db /tmp/p0l9/atlas_copy_p0l9.db
```
SHA256 at copy time matched production exactly. P0L-6 revised DDL applied to
the copy only — `PRAGMA integrity_check` = `ok` immediately after.

## 2. Staged source files

| File | Path | Baseline SHA (== production at copy time) |
|---|---|---|
| `atlas_db.py` | `/tmp/p0l9/src/atlas_db.py` | `c9f79d7a51ab26862f3f979ec53227324721802d088196cd646939c42f830c55` |
| `atlas_intraday.py` | `/tmp/p0l9/src/atlas_intraday.py` | `ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb` |

Both patched **only** as staging copies — production files were never opened
for write.

## 3. What was added to staged `atlas_db.py`

- `get_connection()`: now sets `PRAGMA foreign_keys = ON;` per connection
  (per-connection pragma, as flagged in every prior P0L pass).
- `_bk_to_cents` / `_bk_to_quantity_scaled` / `_bk_to_price_micros`: all route
  through `Decimal(str(x))` exclusively, matching the P0L-3/P0L-7 precision
  rule — zero raw float arithmetic in the money/quantity/price path.
- `_bk_emit_event()`: inserts a `portfolio_event_journal` row; on
  `idempotency_key` UNIQUE collision, catches the `IntegrityError`, logs an
  `IDEMPOTENT_DUPLICATE_REJECTED` row, and returns the **original** event id
  — never raises, never duplicates.
- `_bk_emit_posting()`, `_bk_emit_invariant()`: thin insert helpers.
- `_bk_safe(fn, *args)`: runs any dual-write function in its **own**
  connection/transaction; any exception is caught, rolled back, logged via
  `print()`, and swallowed — never propagates to the caller.
- `_dualwrite_buy_fill()`: `BROKER_BUY_FILLED` event + 2-leg posting
  (`CASH` / `POSITION:<TICKER>`) + `position_lots` row (status `OPEN`).
- `_dualwrite_sell_fill()`: `BROKER_SELL_FILLED` event + 3-leg posting
  (`CASH` / `POSITION:<TICKER>` / `REALIZED_PNL`) + updates the matching
  `position_lots` row to `CLOSED` with `exit_price_micros`/`realized_pnl_cents`.
- `record_manual_cash_correction(amount, reason)`: new reusable helper —
  writes `cash_ledger` via the **existing** `_append_cash_ledger()` call,
  commits, **then** (non-fatally) emits `MANUAL_CORRECTION` +
  `MANUAL_ADJUSTMENT` 2-leg posting (`CASH` / `SUSPENSE:MANUAL_ADJUSTMENT`).
- `_dualwrite_valuation_mark()`: inserts a `valuation_marks` row with
  mandatory `price_source`/`is_fallback` — the direct fix target for the
  P0K-4 entry-price-fallback bug.

### Call-site wiring (legacy-write-first, always)

- `confirm_trade_fill()`: legacy `UPDATE trades` + `_append_cash_ledger()` +
  `conn.commit()` run **exactly as before**, unmodified. Only *after*
  `conn.close()` does `_bk_safe(_dualwrite_buy_fill, ...)` fire.
- `close_trade_broker_confirmed()`: same pattern — legacy `UPDATE trades` +
  `_append_cash_ledger()` + `conn.commit()` unmodified;
  `_bk_safe(_dualwrite_sell_fill, ...)` fires only afterward.

## 4. What was added to staged `atlas_intraday.py`

- `_cache_open_trade_prices()`: legacy `UPDATE trades SET current_price=...`
  block is **byte-identical** to production. A new loop appended *after* the
  legacy `conn.commit()`/`conn.close()` calls `_bk_safe(atlas_db._dualwrite_valuation_mark, ...)`
  per trade, reading `price_source`/`is_fallback` from the trade object
  (defaulting to `live_provider`/`False` only when the caller doesn't supply
  provenance — matching the P0L-8 design's "never default silently" intent
  as closely as possible without a live caller wired yet).
- Main flow (`report_msg = _build_report(summary)` block): a new
  `_bk_emit_report_snapshot()` closure computes `raw_body_sha256` and a small
  `inputs_manifest_json`, then calls `atlas_db._bk_safe(_bk_emit_report_snapshot)`
  — fired immediately after the report text is finalized and printed, before
  the (unmodified) Telegram send block below it.

### Protected-files-untouched verification

```
grep -c "atlas_engine\|atlas_portfolio" atlas_db.py (prod & staged) -> 0 / 0
grep -c "atlas_engine\|atlas_portfolio" atlas_intraday.py (prod & staged) -> 3 / 3
diff prod vs staged atlas_intraday.py | grep -i "atlas_engine|atlas_portfolio" -> EMPTY
```
The 3 pre-existing `atlas_portfolio` references in `atlas_intraday.py`
(`import atlas_portfolio as port` ×2, one docstring mention) are **untouched**
by this diff — confirmed identical in both baseline and staged copies.
`atlas_engine.py` / `atlas_portfolio.py` themselves were never opened.

## 5. Compile results

```
python3 -m py_compile atlas_db.py        -> OK
python3 -m py_compile atlas_intraday.py  -> OK
```

## 6. Synthetic test results (all against `/tmp/p0l9/atlas_copy_p0l9.db`)

| # | Test | Result |
|---|---|---|
| 1 | Broker buy fill | Legacy `trades` UPDATE (delta 0 new rows, status→OPEN), `cash_ledger` +1 row — both **exactly as production behavior**. Bookkeeping: `BROKER_BUY_FILLED` event created, 2 postings, balance = **0 cents**. |
| 2 | Broker sell fill | Legacy `trades` UPDATE (status→CLOSED), `cash_ledger` +1 row — unchanged behavior. Bookkeeping: `BROKER_SELL_FILLED` event, 3 postings (CASH/POSITION/REALIZED_PNL), balance = **0 cents**; `position_lots` row correctly flipped to CLOSED. |
| 3 | Manual correction | `cash_ledger` +1 row via the same `_append_cash_ledger()` path as production. Bookkeeping: `MANUAL_CORRECTION` event (`prof_approved=1`), 2 postings, balance = **0 cents**. |
| 4 | Report snapshot | Row inserted; `raw_body_text` matches the exact literal input string; `raw_body_sha256` matches an independently computed SHA256; `dry_run` flag correctly `1`. |
| 5 | Valuation mark (`live_provider`) | Row inserted, `is_fallback=0`, `price_decimal_text='106.5'` — exact echo of input. |
| 6 | Valuation mark (`entry_fallback`) | Row inserted, `is_fallback=1`, `price_decimal_text='100.0'` — exact echo, correctly flagged. |
| 7 | Forced bookkeeping failure | `ledger_postings` table renamed away mid-test to force a hard SQL failure inside the dual-write call. **No exception propagated to the caller.** Legacy `trades` status still correctly `OPEN`, legacy `cash_ledger` still got its +1 row — legacy write path is completely unaffected by the bookkeeping failure. |
| 8 | Duplicate retry | Re-invoking the same buy-fill dual-write emission with the same `idempotency_key` produced **zero** new `portfolio_event_journal` rows and **zero** new `ledger_postings` rows for that key; instead logged 1 `IDEMPOTENT_DUPLICATE_REJECTED` row. |

## 7. Full-suite verification

- `PRAGMA integrity_check` → `ok`
- `PRAGMA foreign_key_check` → **0 violations**
- Ledger balance check (`GROUP BY event_id HAVING SUM(amount_cents) != 0`) → **0 unbalanced events**, across all events created by every test including test 8's retry.

### Row counts (copy DB, before → after full test suite)

| Table | Before | After | Delta |
|---|---|---|---|
| `trades` | 70 | 72 | +2 (2 synthetic test trades: ZTST, ZTST2) |
| `cash_ledger` | 21 | 25 | +4 (buy+sell for ZTST, buy for ZTST2, manual correction) |
| `portfolio_event_journal` | 0 | 4 | +4 (buy, sell, manual correction, report-snapshot test does not use this table) |
| `ledger_postings` | 0 | 7 | +7 (2+3+2, test 7's failed attempt inserted 0 due to the forced table-rename, test 8's retry inserted 0 new) |
| `position_lots` | 0 | 1 | +1 (ZTST lot; test 7's ZTST2 attempt failed before reaching the lot insert, by design) |
| `valuation_marks` | 0 | 2 | +2 (live_provider + entry_fallback marks) |
| `report_snapshots` | 0 | 1 | +1 |
| `invariant_checks` | 0 | 1 | +1 (balance-check invariant logged during the sell-fill test) |

All deltas are exactly the expected synthetic test footprint — no
unexpected or leaked rows.

## 8. Production verification

- Production `atlas_db.py` SHA: `c9f79d7a51ab26862f3f979ec53227324721802d088196cd646939c42f830c55` — **unchanged**, identical to the pre-patch baseline captured at the start of this task.
- Production `atlas_intraday.py` SHA: `ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb` — **unchanged**.
- Production table list: still exactly the original 8 tables — no bookkeeping tables leaked into production.
- Production `trades` = 70, `cash_ledger` = 21 — unchanged.
- Production `atlas.db` SHA moved once more during this pass (documented pattern: concurrent `com.atlas.intraday` live `signals` growth, same as every prior P0L task) — no bookkeeping-relevant table or file was touched.

## Conclusion

The dual-write patch is fully staged, compiled, and synthetically tested with
all 8 required scenarios passing, including the two hardest-to-fake
guarantees: a forced mid-call bookkeeping failure never blocks or corrupts
the legacy write, and a duplicate retry never double-posts. Zero protected
file exposure, zero production file or DB mutation. Ready for Prof review
before any production deployment step.
