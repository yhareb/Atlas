# P0K-2 Staging-Only INTC DB Correction Package

**Scope:** staging only — worked exclusively against a copy at `/tmp/atlas_p0k2/atlas_copy_p0k2.db`. Production `atlas.db` was never opened for writing (SHA256 verified unchanged before/after — see §7).

**P0K2_STATUS: STAGED_READY_FOR_REVIEW** (not deployed — awaiting Prof approval)

## 1. Copied DB Path

```
/tmp/atlas_p0k2/atlas_copy_p0k2.db
```
Created via `cp /Users/yasser/scripts/atlas.db /tmp/atlas_p0k2/atlas_copy_p0k2.db` at 20260707_210058+0400.

## 2. INTC Before Row (copied DB, pre-correction)

```json
{
  "id": 16,
  "ticker": "INTC",
  "status": "CLOSED",
  "quantity": 7.70534157,
  "entry_price": 129.78,
  "entry_at": "2026-06-25 14:08:30",
  "exit_price": 112.97,
  "exit_at": "2026-07-07 13:40:20",
  "entry_fees": 2.1,
  "exit_fees": 0.0,
  "realized_pnl": -119.77,
  "realized_pnl_pct": -13.18,
  "notes": "...stop 113.02; target 162.25...| Broker fill confirmed ref P780203310",
  "stop_loss": 113.02,
  "risk_pct": 0.5,
  "target_price": 162.25,
  "broker_ref": "P780203310",
  "manual_stop_lock": 0,
  "current_price": 116.21,
  "last_price": 116.21,
  "last_price_at": "2026-07-07 13:36:59"
}
```

Re-confirmed before correction: no `cash_ledger` row references INTC's close (only the original entry debit, id 6, `-1002.10`, ts 2026-06-25 14:26:24).

## 3. Correction Applied (copied DB only)

```sql
UPDATE trades
SET status = 'OPEN',
    exit_price = NULL,
    exit_at = NULL,
    realized_pnl = NULL,
    realized_pnl_pct = NULL,
    updated_at = '2026-07-07 21:01:15'
WHERE id = 16;
```

`quantity`, `entry_price`, `entry_at`, `entry_fees`, `stop_loss`, `risk_pct`, `target_price`, `broker_ref`, `manual_stop_lock`, `notes`, `current_price`, `last_price`, `last_price_at` — all preserved unchanged, exactly as instructed.

## 4. INTC After Row (copied DB, post-correction)

```json
{
  "id": 16,
  "ticker": "INTC",
  "status": "OPEN",
  "quantity": 7.70534157,
  "entry_price": 129.78,
  "entry_at": "2026-06-25 14:08:30",
  "exit_price": null,
  "exit_at": null,
  "entry_fees": 2.1,
  "exit_fees": 0.0,
  "realized_pnl": null,
  "realized_pnl_pct": null,
  "notes": "...stop 113.02; target 162.25...| Broker fill confirmed ref P780203310",
  "updated_at": "2026-07-07 21:01:15",
  "stop_loss": 113.02,
  "risk_pct": 0.5,
  "target_price": 162.25,
  "broker_ref": "P780203310",
  "manual_stop_lock": 0,
  "current_price": 116.21,
  "last_price": 116.21,
  "last_price_at": "2026-07-07 13:36:59"
}
```

## 5. Cash Ledger Change Needed

**cash_ledger_change_needed: NO** (for this specific correction step). Reasoning: reversing a CLOSED→OPEN status correction with no matching close credit in the first place is *consistency-neutral* — there was never a "sale proceeds" cash_ledger row to reverse. No new cash_ledger row was created in the copied DB. This does **not** mean the cash ledger is fully consistent overall — see §8 open item.

## 6. Open Positions After Correction (copied DB)

`get_open_positions()`-equivalent query (`WHERE status='OPEN'`) now returns **5 open positions**:

| Ticker | Qty | Entry | Stop | Target |
|---|---|---|---|---|
| INTC | 7.70534157 | 129.78 | 113.02 | 162.25 |
| SYNA | 7.90888959 | 126.44 | 113.35 | 156.61 |
| RL | 7.40119 | 405.34 | 387.56 | 446.21 |
| BAC | 8.75657 | 57.10 | 57.11 | 60.62 |
| ABNB | 20.97462 | 143.03 | 135.96 | 157.17 |

**Confirmed: INTC now appears in HOLDING** in the copied-DB open-positions query, alongside the other 4 previously-reported holdings.

## 7. Account/Equity Impact (copied DB)

Using Professor's broker screenshot figures (qty 7.70534157, broker price ~$108.51, broker displayed value ~$850.75):

| Metric | Value |
|---|---|
| Original invested (entry) | qty × entry_price = 7.70534157 × 129.78 = **$1,000.00** |
| Value at broker's current price | 7.70534157 × 108.51 = **$836.11** (close to broker's displayed ~$850.75; small diff likely rounding/fee/timing) |
| Value at Atlas's stale `last_price` (116.21, timestamped 13:36:59 — pre-close snapshot) | 7.70534157 × 116.21 = **$895.44** |
| Unrealized P/L vs. broker's current price | **−$163.89** (−16.4%) |
| Unrealized P/L vs. Atlas's stale last_price | −$104.56 (−10.5%) — **note: this stale price predates the correction and would need a live price refresh on next Atlas cycle to be accurate** |

No production equity/cash was touched — this is a copied-DB-only recomputation for planning purposes. Reopening INTC in the copied DB does not change `cash_ledger` (no credit was ever added for the erroneous close, so nothing needs to be subtracted back out), meaning **total account equity in the copied DB is consistent with INTC never having been sold** — correct behavior for this correction.

## 8. Below-Stop / Next-Cycle Risk Check

**INTC_below_stop_after_correction: YES**

- Stop loss: **113.02**
- Broker's current displayed price: **108.51** — already **below stop by $4.51 (−4.0%)**
- Atlas's stale cached price (116.21, from 13:36:59) is stale and **above** stop, but that price predates both the original stop-hit close and Prof's newer broker screenshot — it will be overwritten by a live quote fetch on the next `atlas_intraday.py`/`atlas_portfolio.run_exits()` cycle.

**expected_next_Atlas_action_for_INTC:** On the next intraday cycle (or any `run_exits()` call) against this corrected copied DB, Atlas would fetch a live/current INTC quote. If that live quote is at or below $108.51 (consistent with the broker screenshot) — or anywhere ≤ 113.02 — the position is **already through its stop** and `run_exits()` would classify it as a **SELL (stop-loss exit)** immediately on the next cycle, generating a new stop-hit close (this time hopefully with the broker sell event and matching cash_ledger credit recorded together, resolving the reconciliation gap). This is expected/correct behavior given the stop level and current market price — **not a bug to fix, but the natural consequence of reopening a position that is genuinely below its stop.**

## 9. Production Correction Plan (NOT EXECUTED — plan only, pending approval)

If Prof confirms via broker statement/screenshot that INTC is indeed still open and this correction should be applied to production:

1. **Backup first:** `cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/archive/atlas_db_20260707_210058_p0k2_predeploy.bak.db`
2. **Apply the identical UPDATE** to production `atlas.db` (same SQL as §3, targeting `trades.id=16` only):
   ```sql
   UPDATE trades
   SET status = 'OPEN', exit_price = NULL, exit_at = NULL,
       realized_pnl = NULL, realized_pnl_pct = NULL, updated_at = <timestamp>
   WHERE id = 16;
   ```
3. **No cash_ledger row change** — consistent with the copied-DB finding (§5); the erroneous close never added a credit, so none needs removing.
4. **Verify:** re-run `SELECT * FROM trades WHERE id=16` and the open-positions query on production immediately after, confirm row matches §4 exactly and INTC appears in the 5-position HOLDING list.
5. **Expect an immediate stop-hit SELL** on the very next `atlas_intraday.py` cycle per §8 — this is expected and correct, not a defect; Prof should be aware the position will likely re-close within one cycle given the broker's current sub-stop price.
6. **Do NOT touch** `stop_loss`, `target_price`, `entry_price`, `quantity`, `broker_ref`, or `manual_stop_lock` — all confirmed preserved in the staged version.
7. **This plan requires explicit Prof approval before execution** — no production write has occurred.

## Summary

| Field | Value |
|---|---|
| P0K2_STATUS | STAGED_READY_FOR_REVIEW |
| copied_db_path | `/tmp/atlas_p0k2/atlas_copy_p0k2.db` |
| cash_ledger_change_needed | NO |
| INTC_below_stop_after_correction | YES (broker price 108.51 < stop 113.02) |
| expected_next_Atlas_action_for_INTC | Immediate stop-hit SELL on next Atlas cycle once live price is fetched |
| approval_required | YES |
| production changes | NONE — production `atlas.db` SHA256 verified unchanged: `a01c1eb34abdbf36f0596df300603491abb68f1aca88c98a46f07f6b8d9e7087` before and after this work; production INTC row confirmed still `status=CLOSED` |
