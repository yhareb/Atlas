# P0 PENG Portfolio-Ledger Incident — Read-Only Investigation

**STATUS = CONFIRMED**  
**Production touched by AtlasOps = NO**  
**Investigation timestamp:** 2026-07-10 10:10:24 EDT / 18:10:24 +04

## Current PENG ledger state

- Canonical row: `trades.id=111`, ticker `PENG`, **status `CLOSED`**.
- Quantity `26.42008`; entry `$75.70` at `2026-07-08 16:36:12`; broker reference present.
- Recorded exit `$75.42` at **`2026-07-10 13:40:12` DB time / 09:40:12 EDT**; row updated `13:40:13`.
- Recorded realized P&L `-$7.28` (`-0.369881%`).
- Stop `$75.71`; manual stop lock `0`.
- No PENG broker-sell cash credit exists. Latest cash balance remained `$25,374.95`.
- No `BROKER_SELL_FILLED` journal event, broker reconciliation row, broker display sell snapshot, sell evidence attachment, or Professor-authorized manual override exists for PENG.
- PENG is the **only** broker-entry CLOSED row currently lacking both a broker-sell event and broker-sell cash credit (`1/9`).

## Exact unauthorized close

**Timestamp:** `2026-07-10 13:40:12` DB time / `09:40:12 EDT`; audit event at `2026-07-10 17:40:13.010029 +04` (`09:40:13 EDT`).  
**Mechanism:** scheduled `com.atlas.intraday` launched `atlas_intraday.py` at 09:40 EDT in LIVE mode. The manager evaluated exits, detected `75.42 <= 75.71`, and the generic live exit path called the legacy non-broker-confirmed `atlas_db.close_trade()` function. That function marked the trade CLOSED but contains no cash-credit write.

Runtime evidence:

- `atlas_intraday.log:453140-453142`: manager run at 17:40 host time, `Mode: LIVE — orders WILL be written`.
- `atlas_intraday.log:453155-453168`: exit evaluation; `SELL PENG x26 @ 75.42 — Persisted stop hit; last 75.42 <= stop 75.71`.
- PostgreSQL `ops_db_events`: `trades|UPDATE|111|PENG|close_trade` at 17:40:13 +04.
- `report_snapshots.id=84`, generated 13:46:49 UTC / 09:46:49 EDT: PENG under SELL NOW.
- `report_snapshots.id=85`, generated 13:56:00 UTC / 09:56 EDT: PENG absent; runtime report header says 09:55 AM ET and four positions.

## Root cause and call chain

1. `com.atlas.intraday.plist:9-10` executes `/usr/bin/python3 /Users/yasser/scripts/atlas_intraday.py` every ten minutes (`:18-23`).
2. `atlas_intraday.py` calls the manager in live scheduled mode and renders its returned exit results.
3. `atlas_manage.py:494-498` calls `port.run_exits(dry_run=not live)`; because the scheduled run is live, `dry_run=False`.
4. `atlas_portfolio.py:1134-1140` iterates every open lot and calls `evaluate_exit(..., dry_run=False)`.
5. `atlas_portfolio.py:1087-1090` unconditionally calls `atlas_db.close_trade(ticker, price, quantity=qty)` for a live exit decision. **There is no broker-fill/Professor-approval gate at this call site.**
6. `atlas_db.py:719-818` is the legacy FIFO close function. At `:775-783` it updates `trades.status='CLOSED'`, exit fields, and realized P&L; at `:811` it commits. It does **not** append a cash-ledger credit.
7. In contrast, the broker-confirmed path `atlas_db.close_trade_broker_confirmed()` requires broker data (`:821-860`), updates the row (`:876-884`), and posts the cash credit (`:885-887`). Broker ingestion calls that function at `atlas_broker_ingest.py:320-323`.

### Why PENG disappeared but cash did not increase

The report's holdings source reads only OPEN trades. Once `close_trade()` changed PENG to CLOSED, subsequent cycles omitted it. The same legacy function does not credit `cash_ledger`, so cash remained unchanged. The 09:46 report still displayed the current run's in-memory SELL result, while the 09:55/09:56 cycle re-read the DB and found no OPEN PENG row.

A secondary precision defect is visible in `close_trade()`: quantities are converted with `int()` (`atlas_db.py:744,749,761`), so `26.42008` became `26` for exit/P&L calculation. Because the whole-lot comparison also uses the truncated quantity, the full fractional-share row was marked CLOSED while P&L was computed on 26 shares.

## Policy boundary verification

**Confirmed violated.**

- Expected: stop hit produces SELL NOW advisory output only; PENG remains OPEN until a confirmed broker sell fill or explicit Professor-authorized ledger correction.
- Actual: stop detection directly caused the live TFE exit path to call the mutating legacy close function.
- Profit Protection P0P2a was **not the cause**. `atlas_profit_protection_advisory.py:2-5,28,124-149` is calculation/render-only, declares advisory-only, performs no DB/broker action, and explicitly renders “no DB update.” `atlas_intraday.py:1651-1657` only renders those cards after holdings.
- PENG notes explicitly state its `$85.94` advisory stop was advisory only; the close was instead triggered by the production DB stop `$75.71`.

## Exposure scope

**Other positions may be exposed: YES.** The defect is generic, not ticker-specific. Every OPEN position processed by `run_exits()` in a scheduled live run can be marked CLOSED by `evaluate_exit()` when any live exit rule returns SELL, before broker confirmation. The same path also truncates fractional quantities. Current evidence identifies PENG as the only presently unresolved broker-entry CLOSED row, but future stop/target/time exits remain exposed until the mutating call is gated.

## Production baseline and process evidence

Initial capture at 10:03:32 EDT:

- `atlas.db` SHA256: `2471c3d41f5140c7ee0c0506f944ddb2f3ec4294340eca5d7d5fe89c277b9c49`; integrity `ok`.
- Counts: trades 95, cash_ledger 25, signals 33,556, pending_pullbacks 54, handoff 16; full table-count inventory was captured read-only.
- `com.atlas.intraday` was running as PID 36092; lock `/tmp/atlas_intraday.lock` was fresh. No independent `atlas_manage.py` or `market_scout.py` process was found.
- Relevant launchd job: `com.atlas.intraday`, run count 1,575, last exit 0, six ten-minute calendar triggers.

At 10:10:24 EDT, a new scheduled cycle had started (fresh lock); DB SHA/counts had naturally drifted to SHA `837161266b11eef07e62be2d2d5c51dbb330ce2c046a9c6fef31c2309ca00449`, trades 96, signals 33,626. This was scheduler activity, not AtlasOps. AtlasOps made no production write, code change, schedule change, restart, cache action, DB edit, or Telegram send.

## Safest staged repair plan

### A. PENG ledger correction — do not execute yet

1. First obtain current broker evidence confirming whether PENG remains held and its exact quantity; do not infer a fill from Atlas.
2. After explicit Professor approval, wait for a production idle window and create a timestamped `archive/` DB backup with SHA verification.
3. Apply one narrowly scoped, idempotent correction to trade 111 only: restore `status='OPEN'`; clear the unauthorized `exit_price`, `exit_at`, `exit_fees`, `realized_pnl`, and `realized_pnl_pct`; preserve entry/broker/stop/target fields; append an explicit Professor-authorized correction note/audit event. Do **not** alter cash because no sell credit was posted.
4. Verify PENG is OPEN exactly once, cash remains `$25,374.95`, no broker-sell event is fabricated, DB integrity passes, and PENG reappears as a holding. Preserve the unauthorized-close evidence in audit/history rather than erasing provenance.

### B. Code defect — staging only after approval

Likely files:

- `/Users/yasser/scripts/atlas_portfolio.py` — stop live exit decisions from calling legacy `close_trade()` without confirmation.
- `/Users/yasser/scripts/atlas_db.py` — retire/restrict the unsafe generic close path for broker-backed positions and remove integer quantity truncation; keep `close_trade_broker_confirmed()` authoritative.
- `/Users/yasser/scripts/atlas_intraday.py` and possibly `/Users/yasser/scripts/atlas_report_authority.py` — render stop hits as SELL NOW / broker-confirmation-pending while retaining the OPEN holding ledger state.
- Tests under `/Users/yasser/scripts/tests/`.

Staged behavior:

1. Copy current production files and DB to `/tmp`; verify source/copy SHAs.
2. A stop-hit live simulation must emit `action=SELL`/SELL NOW advisory but perform **zero writes** to `trades`, `cash_ledger`, `portfolio_event_journal`, stops, or broker state.
3. Only `close_trade_broker_confirmed()` (broker evidence) or a separate explicit Professor-authorized correction command may transition OPEN → CLOSED and post the matching cash credit/event atomically.
4. Preserve Profit Protection as report-only and prove it cannot alter stops or close trades.

## Required tests

- Stop hit, target hit, and time-exit: SELL advisory emitted; trade remains OPEN; cash unchanged.
- Repeated ten-minute cycles: advisory repeats/retains pending state without duplicate writes.
- Confirmed broker sell: exact decimal quantity closes once; cash credit, broker event, and trade transition are consistent and idempotent.
- Missing/partial broker evidence: fail closed; no transition.
- Professor-authorized correction fixture: only exact trade changes; audit provenance required.
- Fractional quantity regression (`26.42008`): no `int()` truncation; Decimal-safe calculations.
- P0P2a regression: advisory render cannot mutate DB stop/status/cash.
- Copied-DB before/after counts and row diffs; `PRAGMA integrity_check`; production SHA unchanged.
- Full staged intraday dry-run with Telegram suppressed and no production lock/DB usage.

## Rollback approach

- **Ledger correction:** full-file restore from the timestamped pre-correction DB backup, then SHA/integrity/count verification.
- **Code:** retain per-file timestamped backups in `archive/`; if production deployment is later approved and smoke verification fails, restore all changed files as one unit, compile-check, SHA-verify against backups, and leave the DB untouched.

**approval_required = YES** — stop here. No correction or staging build has been performed.

## Protected-source handling

The work order explicitly authorized tracing the portfolio call chain under the standing Professor alpha-work override. Only the small necessary function/call-site ranges were inspected; no scoring, pillar, sizing, or alpha formulas are reproduced.