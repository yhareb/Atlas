# INTC Override Audit — Read-Only Investigation

Generated: 2026-07-08
Scope: Audit only. No code patches, no DB writes, no status changes, no cash movement, no Telegram sends beyond the final reply.

## Executive Finding

Professor explicitly told Atlas: "I'm keeping INTC. Move it to holdings."

Atlas did temporarily persist that as text in the trade note and changed the legacy `trades` row back to `OPEN`. However, there is no durable, machine-readable manual-hold override state that the exit engine or report builder consults. On the next intraday cycle, the normal stop-loss logic saw live INTC below its stored stop and closed it again.

The report then showed INTC in `SELL NOW` and `SELL TRIGGERED / BROKER CONFIRMATION PENDING` because the database had again become `CLOSED` with an exit price and no matching broker sell cash credit.

This is a lifecycle-state bug, not a broker fact.

## Required Outputs

### current_INTC_state

From `/Users/yasser/scripts/atlas.db`, table `trades`, row `id=16`:

```json
{
  "id": 16,
  "ticker": "INTC",
  "status": "CLOSED",
  "quantity": 7.70534157,
  "entry_price": 129.78,
  "entry_fees": 2.1,
  "exit_price": 106.73,
  "exit_at": "2026-07-08 16:50:17",
  "exit_fees": 0.0,
  "realized_pnl": -163.44999999999996,
  "realized_pnl_pct": -17.991986438588377,
  "stop_loss": 113.02,
  "target_price": 162.25,
  "risk_pct": 0.5,
  "broker_ref": "P780203310",
  "manual_stop_lock": 0,
  "current_price": 129.78,
  "last_price": 129.78,
  "last_price_at": "2026-07-08 16:05:40",
  "updated_at": "2026-07-08 16:50:17"
}
```

Important: the `current_price` / `last_price` fields in the trade row are stale at the entry price. The live engine check showed current INTC around `$106.83`, and the intraday report used `$106.73` for the sell trigger.

### professor_override_persisted

PARTIAL / NOT SUFFICIENT.

A human-readable note was appended to `trades.notes`, but no durable machine-readable override state exists for the exit engine or report builder.

Trade note contains:

```text
Prof correction 2026-07-08 16:02:45: INTC not sold at broker; position remains open; cleared provisional Atlas stop-close fields. Prof will keep it.

Prof confirmed 2026-07-08 16:47:57: keep INTC; ensure it remains in holdings/open positions.
```

But the next cycle still closed the row again.

### override_storage_location

Observed storage:

- `trades.notes`: YES, human-readable only.
- `trades.status`: TEMPORARILY set back to `OPEN`, but later overwritten by exit logic.
- `portfolio_event_journal`: has a prior reversal event, not a durable hold override.
- `manual_stop_lock`: NO, remains `0`; also this field only locks stop movement, not sell suppression.
- dedicated override table: NO observed.
- handoff state: NO durable override found.
- memory/RAG: NO machine-readable trading state found.
- broker confirmation state: NO real broker sell confirmation found.

Relevant `portfolio_event_journal` rows for INTC:

```text
id=82 BROKER_BUY_FILLED legacy_trades_id=16
id=83 STOP_HIT_DETECTED @ 112.97, later reverted
id=84 REVERSAL, prof_approved=1, note: reopened trade id 16 to OPEN per Prof broker screenshot
id=85 STOP_HIT_DETECTED @ 112.12, no matching cash ledger credit
```

There is no event type like `PROFESSOR_HOLD_OVERRIDE` or `MANUAL_HOLD_OVERRIDE_ACTIVE`.

### broker_sell_submitted

UNKNOWN from code/DB alone.

What can be proven:

- No matching INTC broker sell cash credit exists in `cash_ledger`.
- No `BROKER_SELL_FILLED` event exists for INTC in `portfolio_event_journal`.
- The report labels `broker_confirmed: NO`.

What cannot be proven from local DB alone:

- Whether an actual broker sell order was submitted and failed/cancelled, unless a broker-side order screenshot/API record is provided.

Given Professor says he has not sold and is keeping INTC, operational state should treat broker sell submitted as `NO` unless proven otherwise.

### why_SELL_NOW_still_fired

Because `atlas_portfolio.evaluate_exit()` does not check Professor override state.

Logic path from `/Users/yasser/scripts/atlas_portfolio.py`:

```text
875  def evaluate_exit(lot, dry_run=True, regime=None):
909      live_last = _last_price(ticker)
910      last = float(live_last if live_last is not None else closes[-1])
911      persisted_stop = lot.get("stop_loss")
912      fallback_stop = entry - (ATR_STOP_MULT * atr)
913      hard_stop = float(persisted_stop) if persisted_stop is not None else fallback_stop
...
1042     if last >= target:
1043         action, reason, price = "SELL", f"2R target hit; last {last:.2f} >= target {target:.2f}", round(last, 2)
1044     elif last <= hard_stop:
1045         action, reason, price = "SELL", f"Persisted stop hit; last {last:.2f} <= stop {hard_stop:.2f}", round(last, 2)
...
1067     if not dry_run:
1068         try:
1069             atlas_db.close_trade(ticker, price, quantity=qty)
```

Current live values:

```text
last around 106.73 / 106.83
stop 113.02
last <= stop
```

So the engine produced `SELL` and, in live mode, closed the trade again.

The note saying Professor wanted to keep INTC was not consulted anywhere in that decision path.

### why_pending_broker_confirmation_appeared

Because after the engine closed INTC locally, `atlas_db.get_pending_broker_confirmation_trades()` classifies closed trades with no broker sell proof as pending broker confirmation.

Logic from `/Users/yasser/scripts/atlas_db.py`:

```text
965  def get_pending_broker_confirmation_trades(limit=500):
968      Returns CLOSED trades where Atlas detected a sell/stop-hit but the
969      broker-side fill has not yet been confirmed and no matching
970      cash_ledger sell credit has been posted.
...
989      SELECT ... FROM trades
996      WHERE status = 'CLOSED'
997        AND broker_ref IS NOT NULL
998        AND broker_ref != ''
999        AND entry_price IS NOT NULL
1000       AND exit_price IS NOT NULL
1001       AND entry_price != exit_price
...
1017     SELECT DISTINCT legacy_trades_id FROM portfolio_event_journal
1018     WHERE event_type = 'BROKER_SELL_FILLED'
...
1032     SELECT DISTINCT reason FROM cash_ledger WHERE reason LIKE 'Broker sell <ticker>%'
...
1045     if c["id"] in confirmed_ids: continue
1047     if tk in credited_tickers: continue
1049     pending.append(c)
```

Because INTC had:

```text
status = CLOSED
broker_ref = P780203310
entry_price != exit_price
no BROKER_SELL_FILLED event
no cash_ledger reason starting with Broker sell INTC
```

…it appeared in `SELL TRIGGERED / BROKER CONFIRMATION PENDING`.

This is internally consistent with the current DB state, but wrong for Professor's intended state because no actual broker sell was submitted/confirmed.

### missing_lifecycle_state

The missing state is a durable, machine-readable manual hold override.

Needed concept:

```text
PROFESSOR_HOLD_OVERRIDE_ACTIVE
```

This must be distinct from:

- `OPEN`
- `CLOSED`
- `PENDING_FILL`
- `STOP_HIT_DETECTED`
- `BROKER_SELL_SUBMITTED`
- `BROKER_SELL_FILLED`
- `CASH_CREDIT_POSTED`

Right now Atlas has no state that means:

```text
The stop is breached, but Professor explicitly chose to keep holding, so do not close automatically and do not show broker confirmation pending.
```

### correct_state_model

Required lifecycle invariant:

1. STOP HIT is a risk event.
2. SELL NOW is an actionable engine state.
3. BROKER CONFIRMATION PENDING requires an actual submitted broker sell.
4. PROFESSOR HOLD OVERRIDE suppresses SELL NOW but does not erase the risk warning.
5. A manually overridden position must appear in HOLDING as:
   - manual override
   - stop breached
   - high risk
6. Manual override must survive next cycle.

Proposed model:

```text
OPEN + stop not breached
  -> normal HOLDING

OPEN + stop breached + no override
  -> SELL NOW
  -> if actual broker sell submitted: BROKER CONFIRMATION PENDING
  -> if broker fill confirmed: CLOSED + cash credit

OPEN + stop breached + Professor hold override active
  -> HOLDING — MANUAL OVERRIDE
  -> show: stop breached / high risk / system wanted sell
  -> suppress SELL NOW
  -> suppress BROKER CONFIRMATION PENDING
  -> do not close unless override removed or broker sell confirmed
```

### exact_files_or_state_paths_involved

Primary DB:

```text
/Users/yasser/scripts/atlas.db
```

Tables involved:

```text
trades
cash_ledger
portfolio_event_journal
position_lots
handoff
```

Primary code paths:

```text
/Users/yasser/scripts/atlas_portfolio.py
  evaluate_exit()
  run_exits()

/Users/yasser/scripts/atlas_db.py
  close_trade()
  get_open_positions()
  get_pending_broker_confirmation_trades()

/Users/yasser/scripts/atlas_intraday.py
  _sell_now_lines()
  _holding_lines()
  _pending_broker_confirmation_lines()
  _open_trades()
  _authority_open_position_rows()

/Users/yasser/scripts/atlas_report_authority.py
  render_pending_broker_confirmation()
  render_open_positions()
```

Current evidence artifact:

```text
/Users/yasser/scripts/atlas_intraday.log
```

Relevant log/report evidence:

```text
SELL  INTC   x7     @ 106.73  — Persisted stop hit; last 106.73 <= stop 113.02

━━━ 🔴 SELL NOW ━━━
🚨 INTC (Intel)
   👀 Now $106.73
   💲 Entry $129.78
   stop hit; last 106.73 <= stop 113.02

━━━ ⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING (1) ━━━
⚠️ INTC
   🚦 Exit trigger [DB]: $106.73 (stop [DB]/[TFE] $113.02)
   🕐 Triggered [DB]: 2026-07-08 16:50:17
   broker_confirmed [BROKER]: NO
   cash_credit [DB]: NO
```

### proposed_fix_plan

No production change made in this audit. Proposed plan only:

1. Add a durable manual override state.
   - Best: new table, e.g. `manual_trade_overrides` or existing event journal event type `PROFESSOR_HOLD_OVERRIDE_ACTIVE` plus an active-state resolver.
   - Must include ticker/trade_id, reason, created_at, active flag, and optional expiry/removal event.

2. Modify exit evaluation to check active override before returning `SELL` or calling `close_trade()`.
   - If stop breached and override active: return `HOLD` or `ALERT` with `manual_override=True`, `stop_breached=True`, `system_wanted='SELL'`.
   - Do not write `CLOSED`.
   - Do not create realized P/L.

3. Modify report rendering.
   - Holdings should include overridden position even when stop breached.
   - Display should be:
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
     ```

4. Modify pending broker confirmation criteria.
   - Do not infer broker confirmation pending from `CLOSED` alone unless there is a broker sell submission event or explicit sell-submitted state.
   - Better lifecycle states:
     - `STOP_HIT_DETECTED`
     - `BROKER_SELL_SUBMITTED`
     - `BROKER_SELL_FILLED`
     - `CASH_CREDIT_POSTED`
   - `BROKER CONFIRMATION PENDING` should require `BROKER_SELL_SUBMITTED` and no fill yet.

5. Repair production INTC state only after explicit approval.
   - Reopen `trades.id=16` if broker still shows open.
   - Add active manual override state.
   - Do not add cash ledger entry unless broker sell cash exists.
   - Do not alter strategy/risk rules.

### DB_write_required_to_correct_state

YES.

A production write is required to correctly persist the desired state because the current production DB has INTC back as `CLOSED`.

Required writes would likely include:

1. Restore `trades.id=16` to `OPEN` and clear exit/realized fields.
2. Add a durable active manual hold override.

No write was made during this audit.

### approval_required_before_any_write

YES.

### production changes

NONE.

## Direct Audit Questions

### 1. Did Atlas actually persist Professor's instruction “keep INTC / move to holdings” anywhere durable?

Partially.

It persisted the instruction only as human-readable text in `trades.notes` and temporarily changed `trades.status` back to `OPEN`. That is not sufficient because the exit engine does not read that note as an override.

### 2. If yes, where?

- DB column: `trades.notes` only, as free text.
- Event journal: no active manual-hold override event was found.
- Override table: none found.
- Memory/RAG: no machine-readable trading state found.
- Handoff state: no active override found.
- Other state file: none found in this audit.

### 3. If no, explain why the command stayed as chat text and did not become engine/report state.

The command was converted into a note and temporary open status, but not into a formal lifecycle state. The engine/report logic only keys on structured fields such as `status`, `stop_loss`, `exit_price`, cash ledger, and event types. It does not parse `trades.notes` for “Prof will keep it.”

### 4. What is INTC's current DB state?

Current production state at audit time:

```text
trade id: 16
status: CLOSED
quantity: 7.70534157
entry: 129.78
current/live price: engine around 106.83; report used 106.73; DB current_price stale at 129.78
stop: 113.02
target: 162.25
exit_price: 106.73
exit_at: 2026-07-08 16:50:17
realized_pnl: -163.45
realized_pnl_pct: -17.99
broker_ref: P780203310
cash ledger: only buy debit exists; no INTC sell credit exists
```

### 5. Why did Intraday still place INTC in SELL NOW?

Because after INTC was reopened, the next live exit cycle saw `last <= stop` and returned `SELL`. There was no manual override check.

### 6. Why did Intraday place INTC in broker-confirmation pending?

Because the live exit cycle closed the local trade row, then the report helper found a closed trade with a broker ref, exit price, no broker sell event, and no cash sell credit.

### 7. Was an actual broker sell submitted?

UNKNOWN from local state. Professor says he did not sell and is keeping it. No broker sell fill or cash credit exists locally.

### 8. If no broker sell was submitted, why is broker confirmation pending being shown?

Because the current implementation uses local closed-trade state as a proxy for sell-triggered exposure and then labels missing broker/cash proof as pending confirmation. It does not require a distinct `BROKER_SELL_SUBMITTED` event.

### 9. Trace the exact logic path

Stop-hit detection:

```text
atlas_portfolio.evaluate_exit()
last <= hard_stop -> action SELL
if not dry_run -> atlas_db.close_trade()
```

Sell-now section:

```text
atlas_intraday._sell_now_lines()
sells = exit_results where action == SELL
renders INTC in SELL NOW
```

Holdings section:

```text
atlas_intraday._holding_lines()
positions = atlas_db.get_open_positions()
INTC absent once status becomes CLOSED
```

Pending broker confirmation section:

```text
atlas_intraday._pending_broker_confirmation_lines()
rows = atlas_db.get_pending_broker_confirmation_trades()
trades.status='CLOSED' + broker_ref + exit_price + no sell cash + no broker sell event -> pending
```

Manual override handling:

```text
No active machine-readable override handling found in evaluate_exit(), _sell_now_lines(), _holding_lines(), or get_pending_broker_confirmation_trades().
```

### 10. Identify the missing lifecycle state

Missing state:

```text
PROFESSOR_HOLD_OVERRIDE_ACTIVE
```

It must be durable, queryable by exit logic, and reportable in holdings.

## Final Conclusion

The system currently cannot distinguish:

```text
STOP HIT + system should sell
```

from:

```text
STOP HIT + Professor explicitly overrode and wants to hold
```

Therefore it re-triggered the stop, locally closed INTC, removed it from holdings, and then reported it as broker-confirmation pending.

That is wrong for Professor's intended state.

Production changes: NONE.
