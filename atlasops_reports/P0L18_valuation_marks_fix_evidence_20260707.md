# P0L-18 — Staging-Only valuation_marks Lot-ID Fix (Evidence)

**Date:** 2026-07-07 22:50 +04
**Scope:** STAGING-ONLY. All code patches applied only to `/tmp/p0l18/src/`
copies. Zero production file edits, zero production DB writes. No
production `valuation_marks` cleanup executed — audit and plan only.

## Problem (from P0L-17)

`_open_trades()` in `atlas_intraday.py` fell back to the `enumerate()` loop
index as `trade_id` whenever `get_open_positions()` didn't return a real
`id`/`trade_id` column (which it never does — that function only returns
display fields). The P0L-9/P0L-10 dual-write hook then used that fake
"trade_id" as `legacy_trades_id` when looking up `position_lots`, causing
`valuation_marks` to attach to unrelated, already-closed backfilled lots
(AAPL/PBXT/IBXT) instead of the real open positions (SYNA/RL/BAC/ABNB).

## 1. Staging setup

- Copied `/Users/yasser/scripts/atlas.db` → `/tmp/p0l18/atlas_copy_p0l18.db` (SHA match confirmed at copy time).
- Copied `/Users/yasser/scripts/atlas_db.py` and `atlas_intraday.py` → `/tmp/p0l18/src/` (SHA match confirmed at copy time — both were the P0L-16-deployed dual-write versions).

## 2. Fix 1 — real trade-id resolution (`atlas_intraday.py::_open_trades()`)

- Builds a `ticker -> real trades.id` map by calling
  `atlas_db.get_trades(status='OPEN')` (which **does** return a genuine `id`
  column, unlike `get_open_positions()`).
- Each `AtlasTrade.trade_id` now resolves in this priority order: the row's
  own `id`/`trade_id` if genuinely present → the resolved real-id map →
  sentinel `-1` (never the loop index).
- `-1` is intentionally an invalid `trades.id` (all real ids are positive
  `AUTOINCREMENT` values), so even in the extremely unlikely case resolution
  fails entirely, the downstream guard (Fix 2) cannot accidentally match a
  real lot with it.
- Removed `enumerate(rows or [], 1)` entirely — the loop no longer produces
  or uses a positional index anywhere in trade-id assignment.

## 3. Fix 2 — defensive lot-attribution guard (`atlas_db.py::_dualwrite_valuation_mark()`)

Lot lookup changed from:
```sql
SELECT id FROM position_lots WHERE legacy_trades_id=? ORDER BY id DESC LIMIT 1
```
to:
```sql
SELECT id FROM position_lots
WHERE legacy_trades_id=? AND UPPER(ticker)=? AND status='OPEN'
ORDER BY id DESC LIMIT 1
```
A mark may now **only** attach to a lot that matches `legacy_trades_id`
**AND** the given ticker (case-insensitive) **AND** has `status='OPEN'`. If
no lot satisfies all three, the insert is skipped and a new
`valuation_mark_lot_mismatch` WARN invariant is logged — never a
best-effort/partial match, and never silently dropped without a trace. This
guard is the actual safety net: even if Fix 1's id resolution were somehow
wrong in the future, Fix 2 independently prevents any cross-ticker or
closed-lot mismatch.

## 4. Test results

### P0L-18-specific new tests (all against `/tmp/p0l18/atlas_copy_p0l18.db`, real production-mirrored data)

| Test | Result |
|---|---|
| **Real trade-id resolution fixed** | **YES** — `_open_trades()` resolved SYNA→18, RL→42, BAC→47, ABNB→48 exactly matching `trades.id`, confirmed against the copy's real open positions |
| **Loop-index fallback removed** | **YES** — no resolved id matches what a positional loop index would have produced; all ids traced to genuine `trades.id` values |
| **Correct lot mapping test** | **PASS** — ran the full `_cache_open_trade_prices()` dual-write path end-to-end; every new mark attached to the correct `legacy_trades_id` + `status='OPEN'` lot for its ticker (SYNA→lot 63, RL→lot 64, BAC→lot 65, ABNB→lot 66) |
| **ABNB mark test** | **PASS** — ABNB (the ticker that got ZERO marks in the P0L-17 bug because legacy id 4 had no lot) now correctly resolves to its real id 48 and receives a properly-attributed mark |
| **Closed-lot mismatch test** | **PASS** — zero *new* marks landed on the AAPL/PBXT/IBXT backfilled closed lots (ids 53/54/55) during this test run; delta = 0 (pre-existing production-inherited bad marks in the copy are unrelated to this fix and are accounted for separately, see §6) |
| **Direct guard rejection test** | **PASS** — explicitly forced a mismatch (ticker `SYNA` with `legacy_trades_id=1`, which is AAPL's id) → correctly rejected: 0 new marks, 1 new `valuation_mark_lot_mismatch` WARN logged |

### Regression: all 14 P0L-10 tests re-run and passing

| # | Test | Result |
|---|---|---|
| 1 | Broker buy fill | PASS — legacy unchanged, bookkeeping balanced |
| 2 | Broker sell fill | PASS — legacy CLOSED, 3 postings, balanced |
| 3 | Manual correction | PASS — `prof_approved=1`, balanced |
| 4 | Report snapshot | PASS — SHA match |
| 5/6 | Valuation marks on a CLOSED lot (ZTST) | **PASS with updated expectation** — the P0L-18 guard now correctly rejects both calls (delta=0) since ZTST was already closed by test 2; this is the fix working as intended, not a regression |
| 7 | Forced bookkeeping failure | PASS — no exception to caller, legacy unaffected |
| 8 | Idempotency retry | PASS — 0 new postings |
| A | Missing provenance ≠ live_provider | PASS |
| B | Missing provenance → is_fallback=1 | PASS |
| C | Explicit live_provider → is_fallback=0 | PASS |
| D | Explicit entry_fallback → is_fallback=1 | PASS |
| D2 | Fallback WARN invariant fires | PASS |
| E | Report snapshot captures fallback provenance | PASS |

**All 14/14 pass**, with test 5/6's expected outcome updated to reflect the
new (correct) rejection behavior — documented inline in the test script,
not silently changed.

### Full-suite integrity

- `PRAGMA integrity_check` → `ok`
- `PRAGMA foreign_key_check` → **0 violations**
- All `ledger_postings` events still balance to exactly 0 cents

## 5. Compile results

```
python3 -m py_compile atlas_db.py         -> OK
python3 -m py_compile atlas_intraday.py   -> OK
```

## 6. Production audit (read-only — no cleanup executed)

**All 6 existing production `valuation_marks` rows are bad** (100% of the
table), confirming the bug fired on **two** separate live cycles (18:46:30
and 18:56:30) before this fix:

| mark_id | lot_id | lot_ticker | lot_status | legacy_trades_id | price | marked_at |
|---|---|---|---|---|---|---|
| 1 | 53 | AAPL | CLOSED | 1 | 120.64 | 2026-07-07 18:46:30 |
| 2 | 54 | PBXT | CLOSED | 2 | 396.06 | 2026-07-07 18:46:30 |
| 3 | 55 | IBXT | CLOSED | 3 | 60.05 | 2026-07-07 18:46:30 |
| 4 | 53 | AAPL | CLOSED | 1 | 119.84 | 2026-07-07 18:56:30 |
| 5 | 54 | PBXT | CLOSED | 2 | 395.86 | 2026-07-07 18:56:30 |
| 6 | 55 | IBXT | CLOSED | 3 | 60.02 | 2026-07-07 18:56:30 |

All 6 are attached to the 3 backfilled, already-CLOSED lots (AAPL id 53,
PBXT id 54, IBXT id 55) — none belong to the real open positions
(SYNA/RL/BAC/ABNB) they were actually meant to price. 6 matching
`fallback_price_used` invariant rows (ids 14–19) reference these same bad
marks and are equally stale/misleading (their `detail` text names the
*correct* ticker but the *wrong* `lot_id`, e.g. `"...lot_id=53
ticker=SYNA..."`).

### Proposed cleanup plan (NOT executed — for future authorization)

1. **Backup first** (standard pattern): timestamped copy of `atlas.db` to `archive/`, SHA-verified.
2. **Delete the 6 bad `valuation_marks` rows** (`DELETE FROM valuation_marks WHERE id IN (1,2,3,4,5,6)`) — these are pure telemetry, never read by any strategy/report path that trusts them as ground truth (confirmed in P0L-17: the `report_snapshots` manifest path already used a different, correct id source and safely reported `unknown_no_mark` instead of trusting these bad marks).
3. **Delete the 6 matching stale `fallback_price_used` invariant rows** (ids 14–19) — same reasoning, purely diagnostic telemetry with no downstream consumer that would be broken by their removal.
4. **Do NOT touch** `position_lots` (53/54/55 remain correctly `CLOSED`, correctly attributed to AAPL/PBXT/IBXT — the lots themselves were never wrong, only the marks pointing at them) or any legacy table.
5. **Verify after cleanup**: `valuation_marks` count = 0, `invariant_checks` count reduced by exactly 6, `PRAGMA integrity_check` = ok, `PRAGMA foreign_key_check` = 0 violations, all legacy tables byte-identical row counts.
6. This cleanup is **low-risk and reversible** (backup-restorable) but is explicitly **not performed in this task** per the instruction to audit only.

## 7. Protected files / production verification

- `grep -c "atlas_engine\|atlas_portfolio"` on `atlas_db.py`: **0** in both production and staged copy.
- `atlas_intraday.py`: **3** pre-existing references in both — confirmed byte-identical via `diff` (untouched by this fix).
- Production `atlas_db.py` SHA: `93cdb28d98d6879d1fd6d13e043af8b4609c1427a4d586620981edc301345a85` — unchanged (still the P0L-16-deployed version, this fix has NOT been deployed).
- Production `atlas_intraday.py` SHA: `49e30aff620140df218dc515cc77b0e4b97fa99a5c517dad7f27946b5fc768d8` — unchanged.
- Production `atlas.db`: unchanged, `trades`=70, `cash_ledger`=21, `valuation_marks`=6 (the 6 bad rows, untouched).

## Conclusion

Both fixes are staged, compiled, and fully tested — 14/14 regression + 6/6
new tests pass, integrity/FK checks clean. The staged code is ready for a
future production deployment review. Production currently still runs the
unfixed P0L-16 code and contains 6 confirmed-bad `valuation_marks` rows (100%
of the table); a safe, reversible cleanup plan is proposed but intentionally
**not executed** in this task, per the read-only-audit-only instruction.
