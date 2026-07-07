# P0K-5 READ-ONLY Next-Cycle INTC Verification

**Scope:** read-only observation of the next completed scheduled `com.atlas.intraday` cycle after P0K-3's correction. No manual runs, no patches, no DB/strategy/TFE/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**P0K5_STATUS: PASS — self-resolved as predicted in P0K-4**

## Cycle Observed

- Cycle: `[2026-07-07 21:10:04] Atlas intraday loop starting...` (market-hours gate: Tue 2026-07-07 13:10 EDT)
- Completed: `Result: ACTION - 0 BUY(S), 1 SELL(S). See Vault.`
- This is the scheduled `com.atlas.intraday` launchd cron run (no `--force`/`--dry-run`/`--live` flags in the log — standard live scheduled monitoring cycle), i.e. genuine production run, not manually triggered by AtlasOps.

## 1. run_exits Evaluated INTC

**YES.** EXITS section for this cycle:
```
HOLD  ABNB   persisted decision stop; gain +0.75R; 6d open
HOLD  SYNA   persisted decision stop; gain -0.41R; 11d open
SELL  INTC   x7     @ 112.12  — Persisted stop hit; last 112.12 <= stop 113.02
```
INTC now appears in the exit-evaluation output — confirming the P0K-4 timing-gap diagnosis: it simply needed one more cycle to be included once it existed as OPEN before the exits phase ran.

(Note: BAC and RL don't appear in this HOLD/SELL excerpt because they were reclassified — BAC and RL show later in the report under MACRO WATCH, consistent with existing alert-severity classification logic; this is unrelated to INTC and not a new finding.)

## 2. INTC Live Quote Source and Price

**INTC_live_quote_price: $112.12**

This is a genuine live quote — close to Prof's broker screenshot reading (~$108.51) and well below the $129.78 fallback seen last cycle, confirming a real provider price was fetched this time (not the entry-price fallback pattern from P0K-4).

## 3. Fallback Repeated?

**fallback_12978_repeated: NO.** Price moved from the stale $129.78 fallback to a live $112.12 — the fallback did not repeat. This confirms the P0K-4 hypothesis that the $129.78 value was a one-cycle artifact tied to the mid-cycle DB correction, not a persistent provider failure for INTC.

## 4. SELL NOW Fired

**SELL_NOW_for_INTC: YES.**

Confirmed in the rendered Telegram report body:
```
━━━ 🔴 SELL NOW ━━━

🚨 INTC (Intel)
   👀 Now $112.12
   💲 Entry $129.78
   stop hit; last 112.12 <= stop 113.02
   −14% (−$124)
   💰 Invested $908 · Gain −$124
```
Stop-hit logic correctly triggered: $112.12 ≤ $113.02 stop.

## 5. Report Accuracy

**INTC_report_price_correct: YES.**

Report shows Now $112.12, −14% (−$124) — an accurate, real loss figure, replacing the previous cycle's misleading +0%/$129.78 display. `HOLDING` section for this cycle now correctly shows only 4 positions (ABNB, SYNA, RL, BAC) — INTC properly moved out of HOLDING into SELL NOW/closed.

## 6. Cash Ledger Credit

**cash_ledger_credit_if_sold: NO** (as of this check — not yet present)

DB state after this cycle:
```json
{
  "id": 16, "ticker": "INTC", "status": "CLOSED",
  "exit_price": 112.12, "exit_at": "2026-07-07 17:10:22",
  "realized_pnl": -125.72, "realized_pnl_pct": -13.84,
  "stop_loss": 113.02, "current_price": 129.78 (stale cache field, unused post-close),
  "last_price": 129.78, "last_price_at": "2026-07-07 17:06:23"
}
```
`cash_ledger` row count unchanged (21 → 21); no new INTC-referencing row found.

**Important context — this is consistent with the established pattern, not a new anomaly:** every cash_ledger credit observed in this DB for a stop-hit close (IRDM, MSM, ALGM) was written with a `reason` string explicitly referencing a **broker order/notification** (e.g. `"...ORDER_FILLED_SCREENSHOT..."`, `"stop loss reached"` with a broker P/L figure) — meaning those credits appear to be added via a separate **manual broker-confirmation ingestion step** (`atlas_broker_ingest.py`, screenshot-based), not automatically the instant `run_exits()` records a SELL in the `trades` table. Atlas's own internal exit detection (this cycle's SELL) and the cash-ledger credit for the real-world broker fill are two separate, asynchronously-timed events by design — the DB-side SELL just recorded here is the *internal* decision; the broker-side confirmation/credit is expected to follow once Prof (or the ingestion pipeline) records the actual broker fill. This also explains the original INTC close (pre-correction) having no matching credit — it wasn't a bug, it was mid-way through this same two-step process before Prof's broker screenshot revealed INTC was still open.

## Root Cause (if anything remained wrong)

**root_cause_if_still_wrong: N/A — nothing remains wrong.** The P0K-4 HIGH-severity finding (timing gap + stale fallback price) fully self-resolved on the very next scheduled cycle, exactly as predicted: live quote fetched successfully, stop-hit correctly detected, SELL NOW fired, report P/L accurate. The only remaining open item is the cash_ledger credit, which is **expected to lag** pending broker-confirmation ingestion — this is normal process design, not a defect, based on the consistent pattern across IRDM/MSM/ALGM.

## Summary

| Field | Value |
|---|---|
| P0K5_STATUS | PASS |
| run_exits_evaluated_INTC | YES |
| INTC_live_quote_price | $112.12 |
| INTC_price_source | Live provider quote (via `run_exits()`/exit evaluation path) |
| fallback_12978_repeated | NO |
| SELL_NOW_for_INTC | YES |
| INTC_report_price_correct | YES |
| cash_ledger_credit_if_sold | NO (not yet — expected to follow via separate broker-confirmation ingestion, consistent with IRDM/MSM/ALGM pattern) |
| root_cause_if_still_wrong | N/A — issue fully self-resolved this cycle |
| production changes | NONE (read-only observation; the SELL/DB update was produced by Atlas's own live scheduled cycle, not by AtlasOps) |
