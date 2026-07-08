# INTC Override Durable Fix Plan — Read-Only Design

Generated: 2026-07-08
Scope: design only. No code patches, no DB writes, no broker action, no cash movement, no status changes.

## Executive Summary

- The failure is a missing lifecycle state: Atlas can represent `OPEN` and `CLOSED`, but not `OPEN + STOP_BREACHED + PROFESSOR_HOLD_OVERRIDE_ACTIVE`.
- The minimal durable fix needs both a DB write path and a code patch: store the override in a structured table/event, and make exit/report logic read it.
- INTC production correction, after approval, should reopen trade `id=16`, clear provisional local exit fields, and add an active Professor hold override. No cash credit should be added unless a broker sell is confirmed.
- The exit engine must suppress automatic close while an active Professor hold override exists, but the report must still show a stop-breach risk warning in Holdings.
- Broker confirmation pending must require a real broker-sell-submitted/confirmed lifecycle state, not just a local `CLOSED` row without cash.
- Production changes in this design pass: NONE.

---

## INTC_OVERRIDE_FIX_PLAN_STATUS

READ_ONLY_DESIGN_COMPLETE

No production files were patched.
No production DB rows were changed.
No broker actions were touched.
No cash was moved.
No strategy/risk/stop/target rules were changed.

---

## storage_model

### Preferred minimal durable storage

Use a new structured table for active manual overrides, plus optional event-journal entries for audit trail.

Recommended table:

```sql
CREATE TABLE IF NOT EXISTS manual_trade_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    override_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'Prof',
    deactivated_at DATETIME,
    deactivated_reason TEXT,
    source_message TEXT,
    UNIQUE(trade_id, override_type, status)
);
```

Recommended override row for INTC after approval:

```json
{
  "trade_id": 16,
  "ticker": "INTC",
  "override_type": "PROFESSOR_HOLD_OVERRIDE",
  "status": "ACTIVE",
  "reason": "Professor explicitly said: I'm keeping INTC. Move it to holdings.",
  "created_by": "Prof",
  "source_message": "I'm keeping INTC. Move it to holdings."
}
```

### Why a table, not only notes?

`trades.notes` is free text. The exit engine does not and should not parse free text to determine trading lifecycle. The override must be structured and queryable.

### Active/inactive handling

Active override:

```text
status='ACTIVE'
deactivated_at IS NULL
```

Inactive override:

```text
status='INACTIVE'
deactivated_at=<timestamp>
deactivated_reason=<reason>
```

Manual override should be removed only by explicit Professor instruction, broker-confirmed sell, or a future approved rule.

### Audit trail

Also add a `portfolio_event_journal` event when override is created/deactivated:

```text
event_type='PROFESSOR_HOLD_OVERRIDE_ACTIVE'
legacy_trades_id=16
ticker='INTC'
prof_approved=1
payload_json={...}
```

And on removal:

```text
event_type='PROFESSOR_HOLD_OVERRIDE_DEACTIVATED'
linked_reversal_id=<active_event_id>
prof_approved=1
```

The table is the current-state authority; event journal is the historical audit trail.

---

## DB_correction_needed: YES

Production DB currently has INTC locally closed again after the next intraday cycle. To match broker reality and Professor intent, a production DB correction is needed after explicit approval.

### exact_DB_write_plan

After approval only:

1. Backup DB:

```bash
cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/atlas.db.bak_intc_override_fix_$(date +%Y%m%d_%H%M%S)
```

2. Restore INTC trade `id=16` to open, preserving broker and risk fields:

```sql
UPDATE trades
SET status='OPEN',
    exit_price=NULL,
    exit_at=NULL,
    exit_fees=0,
    realized_pnl=NULL,
    realized_pnl_pct=NULL,
    updated_at=CURRENT_TIMESTAMP
WHERE id=16
  AND ticker='INTC';
```

Preserve:

```text
quantity: 7.70534157
entry_price: 129.78
entry_fees: 2.10
stop_loss: 113.02
target_price: 162.25
risk_pct: 0.5
broker_ref: P780203310
manual_stop_lock: unchanged
```

3. Add active Professor hold override:

```sql
INSERT INTO manual_trade_overrides
    (trade_id, ticker, override_type, status, reason, created_by, source_message)
VALUES
    (16, 'INTC', 'PROFESSOR_HOLD_OVERRIDE', 'ACTIVE',
     'Professor explicitly said to keep INTC and move it to holdings despite stop breach.',
     'Prof',
     'I am keeping INTC. Move it to holdings.')
ON CONFLICT(trade_id, override_type, status) DO UPDATE SET
    reason=excluded.reason,
    source_message=excluded.source_message,
    created_at=CURRENT_TIMESTAMP,
    deactivated_at=NULL,
    deactivated_reason=NULL;
```

4. Add audit event:

```sql
INSERT INTO portfolio_event_journal
    (event_type, ticker, legacy_trades_id, occurred_at, effective_at, payload_json,
     source, prof_approved, idempotency_key)
VALUES
    ('PROFESSOR_HOLD_OVERRIDE_ACTIVE', 'INTC', 16, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
     '{"reason":"Professor override: keep INTC despite stop breach"}',
     'prof_manual_override', 1,
     'prof_hold_override_INTC_trade_16_active');
```

5. Do not add a cash ledger row.

Reason: no broker sell occurred and no broker sell cash credit exists.

6. Verify:

```sql
SELECT id,ticker,status,quantity,entry_price,stop_loss,target_price,exit_price,exit_at,realized_pnl,realized_pnl_pct
FROM trades WHERE id=16;

SELECT * FROM manual_trade_overrides WHERE trade_id=16 AND status='ACTIVE';

SELECT * FROM cash_ledger WHERE reason LIKE '%INTC%' ORDER BY id;
```

Expected:

```text
INTC status: OPEN
exit fields: NULL
active override: present
cash ledger: only original buy debit, no sell credit
```

---

## code_patch_needed: YES

A DB-only correction will fail again on the next cycle because `evaluate_exit()` will re-close INTC when live price is below stop. Code must understand and respect the override.

---

## exact_files_likely_need_patch

### 1. `/Users/yasser/scripts/atlas_db.py`

Add helper functions:

```python
def has_active_manual_hold_override(trade_id=None, ticker=None): ...
def get_active_manual_hold_overrides(): ...
def create_manual_hold_override(trade_id, ticker, reason, source_message=None): ...
def deactivate_manual_hold_override(trade_id, ticker, reason): ...
```

Add schema migration for `manual_trade_overrides`.

Optionally add audit-journal emit helper for `PROFESSOR_HOLD_OVERRIDE_ACTIVE` and `PROFESSOR_HOLD_OVERRIDE_DEACTIVATED`.

### 2. `/Users/yasser/scripts/atlas_portfolio.py`

Patch `evaluate_exit(lot, dry_run=True, regime=None)`.

Current behavior:

```text
if last <= hard_stop:
    action = SELL
    if not dry_run: atlas_db.close_trade(...)
```

Required behavior:

```python
manual_override = atlas_db.has_active_manual_hold_override(
    trade_id=lot.get('id'),
    ticker=ticker,
)

if last <= hard_stop and manual_override:
    return {
        "ticker": ticker,
        "action": "HOLD",
        "manual_override": True,
        "stop_breached": True,
        "system_wanted": "SELL",
        "reason": f"Professor hold override active; stop breached; last {last:.2f} <= stop {hard_stop:.2f}",
        "last": round(last, 2),
        "stop": round(hard_stop, 2),
        "target": round(target, 2),
        "qty": qty,
        "entry": round(entry, 2),
    }
```

Critical: no `close_trade()` when override is active.

### 3. `/Users/yasser/scripts/atlas_intraday.py`

Patch report rendering:

- `_sell_now_lines()` must not include rows where `manual_override=True`.
- `_holding_lines()` / holding block must show overridden positions as holdings with clear warning.
- Add or adapt display:

```text
HOLDING — MANUAL OVERRIDE
INTC
Live price: 106.73
Entry: 129.78
Stop: 113.02 breached
System wanted: SELL
Professor override: HOLD
Broker sell placed: NO
Broker confirmation pending: NO
Risk: HIGH
```

### 4. `/Users/yasser/scripts/atlas_report_blocks.py`

If holdings are rendered centrally here, add support for row flags:

```text
manual_override
stop_breached
system_wanted
```

The holding block should show `manual override / stop breached / high risk` instead of normal green/red P/L only.

### 5. `/Users/yasser/scripts/atlas_report_authority.py`

Patch broker confirmation rendering or source rows so pending broker confirmation requires an actual broker sell submitted state, not just local `CLOSED`.

### 6. `/Users/yasser/scripts/atlas_eod_positions.py` or any EOD/positions report that calls pending broker confirmation helper

If it uses the same helper, it may inherit the fix. If not, patch similarly.

---

## report_behavior_after_fix

When INTC is below stop and override is active:

```text
━━━ 💼 HOLDING (...) ━━━

INTC — Intel
Entry: 129.78
Now: 106.73
Stop: 113.02 — BREACHED
Target: 162.25
Status: MANUAL OVERRIDE — Professor holding despite stop breach
System wanted: SELL
Broker sell placed: NO
Broker confirmation pending: NO
Risk: HIGH
```

SELL NOW section:

```text
━━━ 🔴 SELL NOW ━━━
✅ none — manual override active for INTC
```

Or, if other sells exist, INTC must not be included while override active.

Pending broker confirmation section:

```text
INTC must NOT appear
```

Reason: no broker sell was submitted and Professor override says hold.

Risk warning remains visible:

```text
Stop breached; high risk; Professor override active.
```

---

## smoke_test_plan

### Test 1 — stop breached, no override

Setup copied/staging DB row:

```text
trade OPEN
last price below stop
no active manual override
```

Expected:

```text
evaluate_exit -> SELL
SELL NOW includes ticker
if live mode closes locally and no broker/cash proof -> pending broker visibility may appear depending lifecycle state
```

### Test 2 — stop breached, override active

Setup copied/staging DB row:

```text
trade OPEN
last price below stop
manual_trade_overrides active for trade_id
```

Expected:

```text
evaluate_exit -> HOLD or ALERT with manual_override=True
trade remains OPEN
SELL NOW excludes ticker
HOLDING includes ticker as MANUAL OVERRIDE / STOP BREACHED / HIGH RISK
pending broker confirmation excludes ticker
cash unchanged
```

### Test 3 — broker sell submitted, no fill yet

Setup copied/staging DB/event state:

```text
trade has BROKER_SELL_SUBMITTED event
no BROKER_SELL_FILLED event
no cash credit
```

Expected:

```text
SELL TRIGGERED / BROKER CONFIRMATION PENDING includes ticker
broker_confirmed: NO
cash_credit: NO
```

### Test 4 — broker fill/cash credit confirmed

Setup copied/staging DB/event state:

```text
BROKER_SELL_FILLED event exists
cash_ledger sell credit exists
trade CLOSED
```

Expected:

```text
HOLDING excludes ticker
SELL NOW excludes ticker
pending broker confirmation excludes ticker
closed trade appears in history/realized P&L only
```

### Test 5 — override deactivated

Setup:

```text
manual override exists but status INACTIVE
price below stop
```

Expected:

```text
evaluate_exit -> SELL
SELL NOW includes ticker
```

### Test 6 — override survives next cycle

Run two consecutive dry-runs/live-safe simulated cycles against copied DB:

Expected:

```text
INTC remains OPEN both cycles
manual override still active
no cash movement
no local close
```

---

## approval_required_before_write: YES

Any production DB correction or code patch requires explicit Professor approval.

---

## production changes: NONE

No production code changed.
No production DB changed.
No broker action taken.
No cash moved.
No stops, targets, exits, risk, or strategy changed.
