# P0L-17 — First Live Cycle Dual-Write Verification (Evidence)

**Date:** 2026-07-07 22:40–22:47 +04
**Scope:** READ-ONLY monitoring of the first `com.atlas.intraday` cycle to
run after the P0L-16 dual-write code deployment. No patch, no manual DB
write, no forced trades, no Telegram test sends performed by this task.

## Cycle observed

- Cycle started immediately when monitoring began (process already
  transitioning into a new tick) and ran for **386.6 seconds** (~6.4 min,
  within the established 398–466s historical range).
- Telegram: `[intraday] telegram report success=True`, `message_id=1485`
  (distinct from the pre-deployment cycle's `message_id=1484`) — **normal
  delivery confirmed.**
- No `err.log` tracebacks. No `[dual_write]` failure-log lines (the
  `_bk_safe()` non-fatal error print never fired) — no dual-write exception
  was swallowed or surfaced.

## Row-count deltas (before → after)

| Table | Before | After | Delta |
|---|---|---|---|
| `trades` | 70 | 70 | **0** |
| `cash_ledger` | 21 | 21 | **0** |
| `portfolio_event_journal` | 85 | 85 | 0 |
| `position_lots` | 67 | 67 | 0 |
| `ledger_postings` | 49 | 49 | 0 |
| `valuation_marks` | 0 | 3 | **+3** |
| `report_snapshots` | 0 | 1 | **+1** |
| `invariant_checks` | 13 | 16 | **+3** |

Legacy tables (`trades`, `cash_ledger`) are byte-for-byte unchanged — no
broker fill/close occurred this cycle, correctly reflected by zero
`portfolio_event_journal`/`ledger_postings` growth. `report_snapshots`
increased by exactly 1, as expected for one cycle.

## ⚠️ Defect found: valuation_marks attributed to the WRONG lot

`valuation_marks` grew by 3 (not 4, for 4 open positions), and closer
inspection reveals a **real attribution bug**, not merely "missing
provenance behaving conservatively":

| mark id | lot_id | price_source | is_fallback | price | ticker in invariant detail |
|---|---|---|---|---|---|
| 1 | **53** | stale_cache | 1 | 120.64 | SYNA |
| 2 | **54** | stale_cache | 1 | 396.06 | RL |
| 3 | **55** | stale_cache | 1 | 60.05 | BAC |

**Lots 53/54/55 are not SYNA/RL/BAC at all** — they are the P0L-14
backfilled, already-**CLOSED** lots for **AAPL** (id 53), **PBXT** (id 54),
and **IBXT** (id 55), from trades ids 1/2/3 respectively. The live SYNA,
RL, BAC, ABNB open positions are lots 63/64/65/66 (`legacy_trades_id`
18/42/47/48). No valuation mark was written to the correct lots at all.

### Root cause

- `atlas_db.get_open_positions()` returns rows **without** a trade `id`
  column (only `ticker, quantity, entry_price, entry_at, stop_loss,
  risk_pct, target_price, manual_stop_lock`).
- `atlas_intraday.py::_open_trades()` builds each `AtlasTrade` with
  `trade_id=int(row.get("id") or row.get("trade_id") or idx)` — since
  `id`/`trade_id` are absent from the row, this **silently falls back to
  the loop's 1-based enumerate index** (`idx` = 1, 2, 3, 4 for the 4 open
  positions, in DB `id` order: SYNA, RL, BAC, ABNB).
- The P0L-9/P0L-10 dual-write hook in `_cache_open_trade_prices()` reads
  `getattr(trade, "trade_id", None)` and passes it as `legacy_trades_id` to
  `_dualwrite_valuation_mark()`, which looks up
  `position_lots WHERE legacy_trades_id = <that value>`.
- Because `trade_id` is really the enumerate index (1,2,3,4) rather than
  the true `trades.id` (18,42,47,48), the lookup matched **completely
  unrelated, already-closed backfilled lots** that happen to have those
  same small ids (from the original `trades` table's very first rows).
- For idx=4 (ABNB), `legacy_trades_id=4` matches **no** `position_lots` row
  (trade id 4 was VOIDED during backfill, journal-only, no lot exists) —
  so `_dualwrite_valuation_mark()` correctly returned `None` and skipped
  silently, which is why ABNB got 0 marks rather than a wrong one.
- This is a **pre-existing gap in `_open_trades()`/`get_open_positions()`
  that the P0L-9/P0L-10 staging tests never exercised**, because those
  tests called `_dualwrite_valuation_mark()` directly with an explicit
  `legacy_trades_id` argument, never through the live `_open_trades()` →
  `_cache_open_trade_prices()` call path with real production open
  positions.

### Consistency check: report_snapshots manifest (independently, safely, correct)

The `report_snapshots` manifest builder queries `position_lots` using the
**real** trade ids read directly from `trades WHERE status='OPEN'` (18, 42,
47, 48) — not through `_open_trades()`'s buggy `trade_id`. Because the
valuation marks were (wrongly) attached to lots 53/54/55, the manifest's
lookup for the real lots 63/64/65/66 correctly found **no** matching mark
and reported all 4 tickers as `price_source='unknown_no_mark',
is_fallback=true` — the P0L-10 conservative-default logic worked exactly as
designed *for the manifest path*, and never claimed a live price. So the
**report_snapshot itself is safe and conservative**, even though the
`valuation_marks` rows it should have been able to reference are
mis-attributed.

### Invariant checks

3 `fallback_price_used` WARN rows were logged (ids 14–16, all `passed=0`),
correctly flagging every mark as fallback — but their `detail` text
(e.g. `"...lot_id=53 ticker=SYNA..."`) exposes the mismatch directly: the
lot id and the ticker name in the same message don't belong to the same
position, which is itself hard evidence of the bug from inside the
telemetry the hardening was designed to produce.

## Everything else: correct and safe

| Check | Result |
|---|---|
| `atlas_intraday.py` completed successfully | **YES** — clean exit, no traceback |
| `report_snapshots` increased by exactly 1 | **YES** |
| `valuation_marks` increased for open holdings | **Partially — YES in count (3), but WRONGLY ATTRIBUTED (see above)** |
| Marks conservatively `stale_cache`/`is_fallback=1` absent explicit provenance | **YES** — none defaulted to `live_provider`; the P0L-10 hardening itself functioned correctly on the data it was given |
| `invariant_checks` recorded `fallback_price_used` WARNs | **YES** — exactly 3, matching the 3 marks written |
| `trades` unchanged | **YES** — 0 delta, no fill/close occurred this cycle |
| `cash_ledger` unchanged | **YES** — 0 delta |
| Telegram sent normally | **YES** — `message_id=1485`, `success=True` |
| Dual-write exceptions in logs | **NO** — zero `[dual_write]` failure lines, zero new tracebacks |
| Strategy/TFE/stops/targets/exits unchanged | **YES** — no `trades` row modified, all stop/target/quantity/entry values for the 4 open positions identical to pre-cycle state; report diagnostics/BUY-blocked lines reflect normal scan behavior unrelated to bookkeeping |
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 0 violations |

## Conclusion

The dual-write layer is **non-fatal and safe** exactly as designed: zero
impact on legacy tables, zero impact on strategy/TFE/Telegram, zero
uncaught exceptions. However, this first live cycle surfaced a **real,
previously-undetected bug**: `_open_trades()`'s `trade_id` fallback to loop
index (masking the fact that `get_open_positions()` doesn't return the real
`id` column) causes `_dualwrite_valuation_mark()` to attach valuation marks
to the wrong (and in one case nonexistent) `position_lots` rows. This is a
**bookkeeping-telemetry-only defect** — it does not corrupt any legacy data,
does not affect any trading decision, and does not expose the report text
to a wrong price (the report manifest path used a different, correct id
source and safely defaulted to `unknown_no_mark`). It does mean the
`valuation_marks` table currently contains 3 misleading rows that should not
be trusted as-is, and this needs a follow-up staging fix (out of scope for
this READ-ONLY task) before the valuation_marks data can be relied upon.

**Recommended next step (not performed here, pending your direction):** a
P0L-18 staging fix to `_open_trades()` so it passes the ticker's real
`trades.id` (e.g. by extending `get_open_positions()` to include `id`, or by
looking it up via `get_trades(status="OPEN")` which already returns full
rows) as `trade_id`, re-tested against a copy before any further production
deployment.
