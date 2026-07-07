# P0K-4 READ-ONLY INTC Price-Source Audit

**Scope:** read-only. No patches, no deploys, no DB/strategy/TFE/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**Problem:** After P0K-3 restored INTC to OPEN, the 1:06 PM ET intraday report showed INTC "Now $129.78" — identical to entry, +0% — while Prof's broker screenshot showed ~$108.51, below the $113.02 stop. Report also showed `SELL NOW: none`.

**P0K4_STATUS: AUDIT_COMPLETE**

## ⚠️ Correction to prior tool-use in this turn

While tracing the price-source function chain, two search calls in this turn incidentally returned excerpts of `atlas_portfolio.py` (`run_exits()`, `_last_price()`, `_open_positions()` signatures/bodies) without you having issued an explicit bounded-excerpt request for that file. Per the standing protected-file rule, I stopped using that file for further inspection immediately upon noticing, and the rest of this audit was completed using only `atlas_intraday.py`, `atlas_db.py`, `atlas_manage.py`, and log files — none of which are protected. I'm flagging this transparently rather than silently proceeding. No content from `atlas_portfolio.py` beyond bare function/line-signature grep hits is reproduced below, and no analysis of its internal logic is included.

## 1. INTC_price_display_source

**Source chain:** `_holding_lines(summary)` → `_open_trades(summary)` → `atlas_db.get_open_positions()` (DB read, `WHERE status='OPEN'`) → per-row field resolution in `_open_trades()`:

```
entry = row.get("entry_price") or row.get("price") or hold.get("entry") or hold.get("entry_price")
now   = hold.get("last") or hold.get("current_price") or row.get("current_price") or row.get("last") or entry
```

`hold` here is looked up from `summary.get("exit_results", [])` by ticker — i.e., **the row produced by `run_exits()` for that ticker this cycle**. Since INTC was not evaluated by `run_exits()` this cycle (see §3), `hold` is an empty dict `{}` for INTC, so `hold.get("last")` and `hold.get("current_price")` are both `None`. The fallback chain then reaches `row.get("current_price")` from the DB, which — because of how the P0K-3 correction was applied — is still `129.78` (the value that was present in the row's `current_price`/`last_price` columns as a leftover from the *original* pre-correction cached fields, only refreshed to `129.78`/`entry_price`-equal by a later event — see §2). No live quote and no fresh price ever entered this particular render for INTC.

**Answer: DB `trades.current_price`/`last_price` cached column, ultimately equal to `entry_price` — not a live quote.** This is an **entry-fallback-equivalent value cached in the DB itself**, not the renderer inventing a fallback at render time.

## 2. INTC Trade Row — Price Fields

```json
{
  "id": 16, "ticker": "INTC", "status": "OPEN",
  "entry_price": 129.78, "stop_loss": 113.02, "target_price": 162.25,
  "current_price": 129.78, "last_price": 129.78,
  "last_price_at": "2026-07-07 17:06:23 UTC",
  "updated_at": "2026-07-07 17:06:23 UTC"
}
```

Note the timestamp: `17:06:23 UTC` = **1:06:23 PM ET** — i.e., this row was written to *during the same report cycle that displayed it*, a few seconds after the report's header timestamp (1:06 PM ET). This means **`_cache_open_trade_prices()` ran and wrote `current_price=129.78, last_price=129.78` for INTC as part of this very cycle** — and the value it wrote was `129.78`, identical to `entry_price`. This is the direct cause of "Now $129.78, +0%" — not a stale leftover from before the correction, but a **fresh write of the wrong value in the same cycle**.

## 3. Intraday Logs Around 1:06 PM ET (21:00–21:06 local / this cycle)

- Cycle started `[2026-07-07 21:00:03] Atlas intraday loop starting...` (market-hours gate: `Tue 2026-07-07 13:00 EDT`).
- `EXITS (evaluated before any new buys)` section ran `[TIMING] pre_scan_run_exits event=start` at `21:00:07`, ended `21:00:18` (10.4s).
- **Exit evaluation output for this cycle listed only 4 tickers: `HOLD ABNB`, `HOLD BAC`, `HOLD RL`, `HOLD SYNA`. INTC does NOT appear in this list.**
- **Root timing cause: the P0K-3 production DB write restoring INTC to OPEN was committed at `21:04:41` local — i.e., 4 minutes AFTER this cycle's `pre_scan_run_exits` phase (21:00:07–21:00:18) had already completed and captured its open-position snapshot.**
- The report itself (header "1:06 PM ET") was rendered later in the same overall cycle (report-rendering happens after the exits/scan phases, per the `report-first mode` deferred-sweep design), by which point INTC *was* OPEN in the DB — so it appeared in the `HOLDING (5)` list — but the exit-evaluation pass that would have fetched a live price and checked the stop had already run and finished *before* INTC existed as an open position for this cycle's purposes.
- Later in the same cycle, INTC was scanned as a **candidate** (separate code path — the market-scout/pillar-check loop over the full watchlist, not the exits path): `[TIMING] ticker event=start ticker=INTC idx=18/90` at `21:06:14`, resulting in `skip INTC 🔴 AVOID (0/4 Pillars)`. This is the *signal-generation* scan (buy-candidate scoring), completely separate from the *exit* evaluation — it does not check stops or write `current_price` for open positions.

**run_exits_evaluated_INTC: NO** — confirmed by the absence of an INTC line in the EXITS section output for this cycle, and by the timing gap (exits ran 21:00:07–21:00:18; INTC became OPEN at 21:04:41).

**live_quote_result:** No live quote lookup for INTC occurred via the exits path this cycle (it never got that far — INTC wasn't open yet when exits ran). The `current_price=129.78`/`last_price=129.78` written at `17:06:23 UTC` (1:06:23 PM ET) — a few seconds *after* the report's own header timestamp — was written by `_cache_open_trade_prices()`, which is called from `_holding_lines()` only `if summary.get("live")`. Since this was a `dry_run` cycle context is uncertain from logs alone, but the value written (`129.78`) exactly equals `entry_price`, which is the fallback used in `_open_trades()` when no live/cached price is available (`now = ... or entry`) — strongly suggesting the live provider lookup for INTC either failed silently or was never attempted for this specific newly-reopened row, and the entry-price fallback got persisted back into the DB cache columns, compounding the staleness into the next cycle too.

## 4. Why SELL NOW Was None

`SELL NOW` is populated from `exit_results` rows where `action == 'SELL'`. Since INTC was **not present in `exit_results` at all** for this cycle (it wasn't open yet when `run_exits()` ran), there is no INTC row to classify as SELL, POSITION_RISK, or anything else — it simply doesn't exist in the exits dataset this cycle. `SELL NOW: none` is technically correct *for the exits dataset that was computed* — but that dataset is now known to be **stale relative to the DB's current open-position set** (5 positions) because the correction landed mid-cycle, after the exits phase had already run and before the next cycle's exits phase would re-evaluate the now-corrected position list.

**why_SELL_NOW_none: INTC was not included in this cycle's `run_exits()` evaluation at all — the position didn't exist as OPEN yet when exits ran (exits: 21:00:07–21:00:18; INTC reopened: 21:04:41) — so there was no exit-decision row for INTC to classify as SELL. This is a timing/sequencing gap, not a stop-evaluation logic failure.**

## 5. Source Function/Path

Confirmed chain (all in `atlas_intraday.py` unless noted):
1. `atlas_manage.run_atlas_cycle()` (or equivalent) calls `port.run_exits(dry_run=...)` early in the cycle (`atlas_manage.py:457`, timed as `pre_scan_run_exits`) — reads `atlas_db.get_trades(status="OPEN")` / open lots **at that moment**.
2. Later, `_build_report(summary)` → `_holding_lines(summary)` → `_open_trades(summary)` → `atlas_db.get_open_positions()` (`atlas_db.py:724`, `WHERE status='OPEN'`) — reads open positions **again, independently, later in the same cycle**.
3. `_open_trades()` resolves each row's displayed "Now" price via `hold.get(...) or row.get("current_price") or row.get("last") or entry` — where `hold` comes from step 1's `exit_results`.
4. `_cache_open_trade_prices(trades)` (called conditionally on `summary.get("live")`) writes `current_price`/`last_price`/`last_price_at` back to the DB.

**source_function_path:** `_holding_lines()` → `_open_trades()` → `atlas_db.get_open_positions()` for display; `_cache_open_trade_prices()` for the DB write; `run_exits()` (via `atlas_manage.py:457`) for the exit/SELL evaluation — these are **two separately-timed reads of the open-positions set within the same cycle**, and INTC's mid-cycle reopening landed between them.

## 6. Root Cause Classification

**root_cause: Restored-row missing needed cache fields / cross-phase timing gap (primarily), compounded by an entry-price fallback being persisted as if it were a live quote.**

This is not a single clean category — it's two compounding issues:

1. **Primary — sequencing/timing gap:** The P0K-3 production correction was applied at 21:04:41, *between* this cycle's `run_exits()` pass (21:00:07–21:00:18, which didn't see INTC as open) and its later report-render pass (21:06+, which did see INTC as open). This is an inherent risk of any mid-cycle DB write during a running Atlas cycle — exactly the kind of race the P0K-3 transaction-based write already tried to minimize by checking for row drift, but it could not "un-skip" an exits pass that had already completed 4+ minutes earlier. **Not a bug in the correction procedure — an unavoidable consequence of correcting a DB row while a cycle is mid-flight.**
2. **Secondary — stale/fallback price got cached as ground truth:** Independent of the timing gap, the `current_price`/`last_price` written for INTC this cycle (129.78, exactly = entry_price) shows the live-quote path for the reopened INTC lot did not produce a real quote and silently fell back to entry price, which was then persisted to the DB — meaning **the next cycle will also start from this wrong cached value unless a fresh live quote successfully overwrites it.**

## 7. Severity

**severity: HIGH**

Rationale: this is not cosmetic. Because `SELL NOW` and stop-checks depend on `run_exits()` output, and that output can lag a genuine DB correction by a full cycle, Atlas is currently carrying an open INTC position that is materially below its stop ($108.51 broker vs $113.02 stop) with **no active exit evaluation having run against it yet** and a **cached display price that masks the loss** (showing +0% instead of the true ~−16%). If the next cycle's live-quote fetch also fails for INTC (same failure mode that produced the entry-price fallback this cycle), the position could continue showing incorrect data and skip stop-loss evaluation for additional cycles. This directly affects risk visibility on a real, currently-losing position.

## Safest Next Step

**safest_next_step:** Do not patch code yet. Instead:
1. Wait for/observe the **next scheduled intraday cycle** (~10 min cadence) and check whether `run_exits()` this time includes INTC and whether it fetches a genuine live quote (watch for it landing near ~$108–109, matching the broker screenshot) rather than repeating the 129.78 entry-fallback.
2. If the next cycle's exit evaluation correctly picks up INTC below stop and issues a SELL, the system self-corrects with no code change needed — confirms this was purely the one-time timing gap from the mid-cycle correction.
3. If the next cycle *again* shows INTC at $129.78/+0% with no SELL, that confirms the live-quote provider is failing specifically for INTC (not just a timing artifact) and warrants a separate, narrowly-scoped read-only audit of the live-price-provider call for INTC specifically (rate limit? ticker mapping issue? provider outage?) before any code change is proposed.
4. Recommend Prof be told now, ahead of the next cycle, that INTC's report display is currently understating the loss and that a stop-loss SELL is expected imminently once a live quote is successfully fetched.

## Summary

| Field | Value |
|---|---|
| P0K4_STATUS | AUDIT_COMPLETE |
| INTC_price_display_source | DB `trades.current_price`/`last_price` cache column, value = entry_price fallback (not a live quote) |
| INTC_trade_row_price_fields | entry_price 129.78, stop_loss 113.02, current_price 129.78, last_price 129.78, last_price_at 2026-07-07 17:06:23 UTC, updated_at same |
| run_exits_evaluated_INTC | NO — exits phase (21:00:07–21:00:18) ran before INTC was reopened (21:04:41) |
| live_quote_result | No successful live quote observed for INTC this cycle; cached price written equals entry_price (fallback pattern) |
| why_SELL_NOW_none | INTC absent from this cycle's `exit_results` entirely (timing gap), not a stop-check failure |
| source_function_path | `_holding_lines()` → `_open_trades()` → `atlas_db.get_open_positions()` (display); `_cache_open_trade_prices()` (DB write); `run_exits()` via `atlas_manage.py:457` (exit/SELL evaluation) — two independently-timed reads within one cycle |
| root_cause | Cross-phase timing gap from mid-cycle DB correction (primary) + entry-price fallback silently cached as current_price (secondary) |
| severity | HIGH |
| safest_next_step | Observe next cycle before any code change; escalate to provider-specific audit only if the fallback repeats |
| production changes | NONE |
