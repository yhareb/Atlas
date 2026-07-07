# P0L-10 — Staging-Only Price-Provenance Hardening (Evidence)

**Date:** 2026-07-07
**Scope:** STAGING-ONLY. Patches applied only to the P0L-9 `/tmp/p0l9/src/`
copies. Zero production file edits, zero production DB writes, zero
deploys.

## Problem addressed

P0L-9's `_dualwrite_valuation_mark()` and its `atlas_intraday.py` call site
defaulted a missing `price_source` to `"live_provider"` with
`is_fallback=False`. That is unsafe: silence about provenance must never be
interpreted as "this was a confirmed live quote" — this is exactly the class
of bug that caused the P0K-4 INTC incident (an entry-price fallback silently
cached as if live).

## 1. Fix in `atlas_db.py::_dualwrite_valuation_mark()`

Signature changed to `price_source=None, is_fallback=None` (both now
optional, defaulting to `None`, never to `"live_provider"`/`False`).

Logic:

| Caller input | Result |
|---|---|
| `price_source=None` (not supplied) | `price_source` forced to `'stale_cache'`, `is_fallback` forced to `1`. Never `live_provider`. |
| `price_source='live_provider'`, `is_fallback=None` | Preserved verbatim; `is_fallback` derived as `0` only because the source is explicitly `live_provider`. |
| `price_source='<anything else>'`, `is_fallback=None` | Preserved verbatim; `is_fallback` derived as `1` (conservative — any non-`live_provider` source defaults to fallback unless the caller explicitly overrides). |
| Any explicit `price_source` + explicit `is_fallback` | Both preserved exactly as supplied — caller intent always wins over defaults. |

Whenever the inserted row ends up `is_fallback=1`, a `fallback_price_used`
WARN invariant row is emitted in the same transaction, with a detail string
that explicitly calls out when provenance was *missing* versus merely
non-live, e.g.:
> `"...used non-live price_source='stale_cache' (provenance was MISSING from caller -- defaulted conservatively, never live_provider)"`

## 2. Fix in `atlas_intraday.py::_cache_open_trade_prices()` call site

Previously: `price_source = getattr(trade, "price_source", None) or "live_provider"`
— this silently converted "attribute missing" into `"live_provider"`.

Now: `price_source = getattr(trade, "price_source", None)` — `None` is
passed straight through to `_dualwrite_valuation_mark()`, which applies its
own conservative default (`stale_cache` + `is_fallback=1`) rather than the
call site guessing `live_provider`. Same treatment for `is_fallback`.

## 3. Report snapshot manifest hardening

`_bk_emit_report_snapshot()` in `atlas_intraday.py` now builds a
`priced_tickers` dict inside `inputs_manifest_json`, one entry per currently
OPEN legacy trade, each containing `price_source`, `is_fallback`, and
`price_decimal_text` sourced from that ticker's most recent
`valuation_marks` row. If **no** `valuation_marks` row exists at all for a
ticker in a given cycle, the manifest explicitly records
`price_source='unknown_no_mark'`, `is_fallback=True` — it never silently
omits the ticker or implies a live price was used by absence.

## 4. Test results (14/14 pass — 8 regression + 6 new)

Run against a fresh `/tmp/p0l9/atlas_copy_p0l9.db` (P0L-6 DDL re-applied,
`PRAGMA integrity_check`=`ok` before any test).

### Regression (all 8 original P0L-9 tests, unchanged behavior confirmed)

| # | Test | Result |
|---|---|---|
| 1 | Broker buy fill | Legacy behavior unchanged, bookkeeping event created, postings balance 0 cents |
| 2 | Broker sell fill | Legacy status→CLOSED, 3 postings, balance 0 cents, lot→CLOSED |
| 3 | Manual correction | `MANUAL_CORRECTION` event, `prof_approved=1`, postings balance 0 cents |
| 4 | Report snapshot | SHA256 match confirmed |
| 5/6 | Valuation marks (explicit) | Both inserts succeed |
| 7 | Forced bookkeeping failure | No exception to caller; legacy trade/cash writes unaffected |
| 8 | Idempotency retry | Zero new postings for the duplicate key |

### New P0L-10 provenance tests

| # | Test | Result |
|---|---|---|
| A | Missing provenance does NOT become `live_provider` | `price_source='stale_cache'` — **confirmed never `live_provider`** |
| B | Missing provenance sets `is_fallback=1` | `is_fallback=1` — confirmed |
| C | Explicit `live_provider` remains `is_fallback=0` | `price_source='live_provider'`, `is_fallback=0` — confirmed |
| D | Explicit `entry_fallback` remains `is_fallback=1` | `price_source='entry_fallback'`, `is_fallback=1` — confirmed |
| D2 | WARN invariant fires on fallback use | 3 `fallback_price_used` WARN rows logged, all `passed=0` (flagged, non-blocking) |
| E | Report snapshot captures fallback provenance | `priced_tickers.ZTST3 = {price_source: 'entry_fallback', is_fallback: true, price_decimal_text: '72.0'}` — confirmed present and accurate in `inputs_manifest_json` |

## 5. Full-suite verification

- `PRAGMA integrity_check` → `ok`
- `PRAGMA foreign_key_check` → **0 violations**
- Ledger balance check → **0 unbalanced events** across all 14 tests

### Row counts (before → after full 14-test run)

| Table | Before | After | Delta |
|---|---|---|---|
| `trades` | 70 | 73 | +3 (ZTST, ZTST2, ZTST3 synthetic entries) |
| `cash_ledger` | 21 | 26 | +5 |
| `portfolio_event_journal` | 0 | 5 | +5 |
| `ledger_postings` | 0 | 9 | +9 |
| `position_lots` | 0 | 2 | +2 (ZTST closed lot, ZTST3 open lot; ZTST2's lot insert never happened by design — test 7 forces the failure before that point) |
| `valuation_marks` | 0 | 6 | +6 |
| `report_snapshots` | 0 | 2 | +2 |
| `invariant_checks` | 0 | 5 | +5 (1 balance-check + 3 fallback_price_used from tests A/D/E + implicit ones) |

All deltas match the expected synthetic footprint exactly.

## 6. Protected files / production verification

- `grep -c "atlas_engine\|atlas_portfolio"` on `atlas_db.py`: **0** in both production and staged copy.
- `atlas_intraday.py`: **3** pre-existing references in both production and staged copy — `diff` confirms these 3 lines are byte-identical between versions (untouched by this or the P0L-9 diff).
- Production `atlas_db.py` SHA: `c9f79d7a51ab26862f3f979ec53227324721802d088196cd646939c42f830c55` — unchanged.
- Production `atlas_intraday.py` SHA: `ab1b52bc2d8cc2c00a4755fc3ff31c77ea7565de3429360eb824728fce152acb` — unchanged.
- Production table list: still exactly the original 8 tables.
- Production `trades`=70, `cash_ledger`=21 — unchanged.
- Compile check: both staged files `python3 -m py_compile` clean.

## Conclusion

The unsafe default is eliminated: missing price provenance can no longer be
mistaken for a live quote anywhere in the staged dual-write path — not in
`_dualwrite_valuation_mark()`, not in its `atlas_intraday.py` call site, and
not in the report-snapshot manifest (which now explicitly flags
`unknown_no_mark` rather than omitting a ticker). All 14 tests (8 regression
+ 6 new) pass. Zero protected-file exposure. Zero production mutation. Ready
for Prof review before any production deployment step.
