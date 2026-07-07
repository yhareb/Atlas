# P0K-3 Production DB Correction — INTC Trade ID 16 — Evidence Report

**Scope:** production `atlas.db`, trade id 16 (INTC) only. Restored CLOSED→OPEN per Prof-approved P0K-2 staging plan.

**P0K3_STATUS: PASS**

## 1. Backup

```
/Users/yasser/scripts/archive/atlas_db_20260707_2107_p0k3_predeploy.bak.db
```
SHA256 (backup, taken before write): `603cb49b38d79c9e468a9e94d7c00c1e3ee52cce81672222ce310aca5d5a8db6`
This matches production `atlas.db`'s SHA256 at the same moment — backup correctly captured pre-write state.

## 2. Pre-Write Verification

Before writing, re-fetched production `trades` row id=16 and confirmed it exactly matched the audited CLOSED state from P0K-1/P0K-2 (status=CLOSED, exit_price=112.97, exit_at=2026-07-07 13:40:20, stop_loss=113.02, target_price=162.25, broker_ref=P780203310, manual_stop_lock=0, quantity=7.70534157, entry_price=129.78). **No mismatch found — proceeded.** (Abort condition was not triggered.)

The write itself was also wrapped in a `BEGIN IMMEDIATE` transaction with a second in-transaction row re-check immediately before the `UPDATE`, to guard against a race with the live `com.atlas.intraday` process (PID 6128, running concurrently at write time) — confirmed clean, no conflict.

## 3. INTC Before Row (production, pre-correction)

```json
{
  "id": 16, "ticker": "INTC", "status": "CLOSED",
  "quantity": 7.70534157, "entry_price": 129.78, "entry_at": "2026-06-25 14:08:30",
  "exit_price": 112.97, "exit_at": "2026-07-07 13:40:20",
  "entry_fees": 2.1, "exit_fees": 0.0,
  "realized_pnl": -119.77, "realized_pnl_pct": -13.18,
  "stop_loss": 113.02, "risk_pct": 0.5, "target_price": 162.25,
  "broker_ref": "P780203310", "manual_stop_lock": 0,
  "current_price": 116.21, "last_price": 116.21, "last_price_at": "2026-07-07 13:36:59"
}
```

## 4. Write Executed

```sql
UPDATE trades
SET status = 'OPEN',
    exit_price = NULL,
    exit_at = NULL,
    realized_pnl = NULL,
    realized_pnl_pct = NULL,
    updated_at = '2026-07-07 21:04:41'
WHERE id = 16;
```
Committed successfully at `2026-07-07 21:04:41`.

## 5. INTC After Row (production, post-correction)

```json
{
  "id": 16, "ticker": "INTC", "status": "OPEN",
  "quantity": 7.70534157, "entry_price": 129.78, "entry_at": "2026-06-25 14:08:30",
  "exit_price": null, "exit_at": null,
  "entry_fees": 2.1, "exit_fees": 0.0,
  "realized_pnl": null, "realized_pnl_pct": null,
  "updated_at": "2026-07-07 21:04:41",
  "stop_loss": 113.02, "risk_pct": 0.5, "target_price": 162.25,
  "broker_ref": "P780203310", "manual_stop_lock": 0,
  "current_price": 116.21, "last_price": 116.21, "last_price_at": "2026-07-07 13:36:59"
}
```
`quantity`, `entry_price`, `entry_at`, `entry_fees`, `stop_loss`, `risk_pct`, `target_price`, `broker_ref`, `manual_stop_lock`, `notes`, `current_price`, `last_price`, `last_price_at` — all preserved unchanged, exactly as approved.

## 6. Open Positions After Correction

`SELECT ... FROM trades WHERE status='OPEN'` now returns **5 rows**:

| Ticker | Qty | Entry | Stop | Target |
|---|---|---|---|---|
| INTC | 7.70534157 | 129.78 | 113.02 | 162.25 |
| SYNA | 7.90888959 | 126.44 | 113.35 | 156.61 |
| RL | 7.40119 | 405.34 | 387.56 | 446.21 |
| BAC | 8.75657 | 57.10 | 57.11 | 60.62 |
| ABNB | 20.97462 | 143.03 | 135.96 | 157.17 |

Open count: **4 → 5**, confirmed.

## 7. Cash Ledger Verification

**cash_ledger_changed: NO**

- `cash_ledger` row count: **21 before → 21 after** — unchanged.
- No new row added, no row removed.
- Only pre-existing INTC entry-fill debit remains (id 6, `-1002.10`, ts 2026-06-25 14:26:24) — no sale-credit row was ever added, so none needed reversal.

## 8. Other Table Counts (unaffected)

| Table | Before | After |
|---|---|---|
| cash_ledger | 21 | 21 |
| handoff | 13 | 13 |
| pending_pullbacks | 50 | 50 |
| signals | — | 25918 (grew from concurrent live `com.atlas.intraday` activity during this window — unrelated to this correction) |
| trades | 70 | 70 |

Only `trades.id=16`'s in-place fields were modified — no rows added or removed from any table.

## 9. Production DB Integrity Check

```
PRAGMA integrity_check;
> ok
```
**db_integrity_check: OK**

## 10. Expected Next Atlas Action for INTC

Broker's current displayed price (~$108.51, per Prof's screenshot) is already **below** the stop_loss of **113.02** by $4.51 (−4.0%). Atlas's cached `last_price`/`current_price` (116.21) is stale (timestamped 13:36:59, pre-dating both the erroneous close and this correction) and will be refreshed with a live quote on the next `atlas_intraday.py` cycle or any `atlas_portfolio.run_exits()` call.

**expected_next_Atlas_action_for_INTC:** Once a live quote is fetched and it confirms the price is at or below the $113.02 stop (consistent with the broker's ~$108.51 reading), `run_exits()` will classify INTC as a stop-loss **SELL** and close it again on the very next cycle — this time with a genuine broker-confirmed sell event expected to also produce a matching `cash_ledger` credit row (resolving the earlier reconciliation gap noted in P0K-1). This is the correct, expected behavior given the stop level and current market price — not a defect.

## 11. Rollback

**rollback_available: YES**

```bash
cp /Users/yasser/scripts/archive/atlas_db_20260707_2107_p0k3_predeploy.bak.db /Users/yasser/scripts/atlas.db
python3 -c "import sqlite3; c=sqlite3.connect('/Users/yasser/scripts/atlas.db'); print(c.execute('PRAGMA integrity_check').fetchall())"
```
Restores trade id 16 to `status=CLOSED, exit_price=112.97, exit_at=2026-07-07 13:40:20` and all other tables to their pre-correction state (backup taken immediately before the write, capturing the exact production state at that moment).

## Summary

| Field | Value |
|---|---|
| P0K3_STATUS | PASS |
| backup_path | `/Users/yasser/scripts/archive/atlas_db_20260707_2107_p0k3_predeploy.bak.db` |
| open_positions_after | 5 (INTC, SYNA, RL, BAC, ABNB) |
| cash_ledger_changed | NO |
| db_integrity_check | OK |
| expected_next_Atlas_action_for_INTC | Immediate stop-loss SELL on next cycle once live quote confirms price ≤ $113.02 stop |
| rollback_available | YES |
| production changes | INTC trade id 16 only |
