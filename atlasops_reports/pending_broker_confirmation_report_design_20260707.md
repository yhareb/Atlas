# READ-ONLY Pending Broker-Confirmation Report Design

**Date:** 2026-07-07
**Scope:** Design only. No patch/deploy/DB writes/strategy/TFE/routing/scheduler/env/Telegram/stops/targets/exits changes.

## Problem
EOD correctly omits INTC because `trades.status=CLOSED`, but INTC has no `BROKER_SELL_FILLED` event and no `cash_ledger` sell credit. In a manual-trading system, a position exiting the report entirely — with zero visible trace that a broker confirmation is still owed — is a silent gap Prof needs surfaced, not hidden.

## 1. All CLOSED trades without BROKER_SELL_FILLED and/or no cash_ledger sell credit

11 `CLOSED` trades total. Cross-referenced against `portfolio_event_journal.event_type='BROKER_SELL_FILLED'` (7 rows: TSM/5, LRCX/12, MS/17, KLIC/44, IRDM/45, ALGM/46, MSM/84) and `cash_ledger` sell-credit rows matched by ticker text in `reason`:

| trades.id | ticker | exit_price | exit_at | BROKER_SELL_FILLED? | cash_ledger credit? | Category |
|---|---|---|---|---|---|---|
| 1 | AAPL | 299.81 | 2026-06-22 15:27:26 | NO | NO | Backfilled test/demo trade (entry=exit price, 12s hold, `RECONCILIATION_EXCEPTION` journal only) |
| 2 | PBXT | 102.33 | 2026-06-22 15:49:49 | NO | NO | Same as above |
| 3 | IBXT | 101.0 | 2026-06-22 15:49:52 | NO | NO | Same as above |
| 5 | TSM | 446.74 | 2026-06-23 18:22:22 | YES | YES | Fully confirmed |
| 12 | LRCX | 433.01 | 2026-06-30 18:06:36 | YES | YES | Fully confirmed |
| **16** | **INTC** | **112.12** | **2026-07-07 17:10:22** | **NO** | **NO** | **⚠️ Real open broker-confirmation gap** |
| 17 | MS | 214.8 | 2026-06-29 13:41:34 | YES | YES | Fully confirmed |
| 44 | KLIC | 132.1375 | 2026-06-30 18:07:00 | YES | YES | Fully confirmed |
| 45 | IRDM | 52.02 | 2026-07-07 13:31:00 | YES | YES | Fully confirmed |
| 46 | ALGM | 61.46 | 2026-07-02 11:38:00 | YES | YES | Fully confirmed |
| 84 | MSM | 119.96 | 2026-07-06 12:18:00 | YES | YES | Fully confirmed |

**affected_trades = [1 (AAPL), 2 (PBXT), 3 (IBXT), 16 (INTC)]** — but these split into two clearly distinct categories:

- **AAPL/PBXT/IBXT (ids 1/2/3):** entry_price == exit_price, held for 2–12 seconds, `realized_pnl=0.0`, zero broker_ref, journaled only as `RECONCILIATION_EXCEPTION` (not `STOP_HIT_DETECTED`) — these are historical backfill/demo artifacts from before live broker trading began (confirmed in prior P0L-5/P0L-18 sessions), not live unconfirmed positions. They carry no real economic exposure and no pending broker action.
- **INTC (id 16):** real trade, real broker-confirmed **entry** (`cash_ledger.id=6`, broker_ref=`P780203310`), stop-hit detected with a live quote, non-zero `realized_pnl=-125.72`, but **no exit-side broker confirmation yet**. This is the one live, economically real pending-confirmation case.

## 2. Confirm INTC is one of them
**YES** — INTC (`trades.id=16`) is the sole live/real case in the affected set requiring visibility. AAPL/PBXT/IBXT are historical backfill artifacts (recommend excluding them from the new report section by requiring `broker_ref IS NOT NULL` or `entry_price != exit_price`, see design below).

## 3. Reports that currently hide these rows

| Report | File | Filter | Hides INTC? |
|---|---|---|---|
| Intraday | `atlas_intraday.py` | `_open_trades()` (line 838) → `atlas_db.get_trades(status="OPEN")` | YES |
| EOD Positions | `atlas_eod_positions.py` | `_open_trades()` (line 113) → `atlas_db.get_trades(status="OPEN", limit=1000)` | YES |
| Macro Postmarket | `atlas_macro_postmarket.py` | N/A — does not reference `get_trades`, holdings, or position status at all | Not applicable (never showed holdings) |
| Holdings summary | — | No standalone holdings-summary script found in `/Users/yasser/scripts/` | N/A |

**reports_affected = [atlas_intraday.py, atlas_eod_positions.py]** — both use the identical `status="OPEN"` filter pattern.

## 4. Proposed new report section (design only)

Add a section to both `atlas_intraday.py` and `atlas_eod_positions.py` report bodies, placed after the existing `HOLDING` section:

```
━━━ ⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING (N) ━━━

1. ⚠️ INTC (Intel Corporation)
   🚦 Exit trigger: $112.12 (stop $113.02)
   🕐 Triggered: 2026-07-07 17:10:22
   📊 Est. P/L: -$125.72 (-13.84%)
   broker_confirmed: NO
   cash_credit: NO
```

**Query logic (design, not implemented):**
```python
def _pending_broker_confirmation_trades():
    """
    Trades where status=CLOSED via stop-hit detection but broker sell
    fill / cash credit is not yet confirmed. Excludes pre-broker
    backfill artifacts (entry_price == exit_price, no broker_ref).
    """
    rows = atlas_db.get_trades(status="CLOSED", limit=1000)
    pending = []
    for t in rows:
        if t["entry_price"] == t["exit_price"]:
            continue  # backfill/demo artifact, not a real position
        if not t.get("broker_ref"):
            continue  # never had a real broker entry either
        has_sell_event = atlas_db.journal_has_event(
            legacy_trades_id=t["id"], event_type="BROKER_SELL_FILLED"
        )
        has_cash_credit = atlas_db.cash_ledger_has_credit_for_trade(t["id"])
        if not has_sell_event and not has_cash_credit:
            pending.append(t)
    return pending
```

Fields per row: `ticker`, `exit_price` (trigger price), `stop_loss`, `exit_at` (trigger time), `realized_pnl`/`realized_pnl_pct` (estimated P/L — clearly labeled "estimated" since it's not yet broker-confirmed), `broker_confirmed: NO`, `cash_credit: NO`.

## 5. Report-only confirmation
This design touches **display/query logic only**:
- No change to `trades.status` lifecycle (stop-hit detection, closing logic, `STOP_HIT_DETECTED`/`BROKER_SELL_FILLED` event emission — all untouched).
- No change to strategy/TFE/scoring/entry logic.
- No change to stops, targets, or exit trigger logic — this section only *displays* an exit that already triggered; it does not re-evaluate or re-trigger anything.
- No change to risk sizing or position management.
- New section is purely additive: existing `HOLDING`/other sections keep their current filters and behavior unchanged; this is a new read-only query appended to the report body.

## 6. Files likely affected (not patched — recommendation only)

| File | Change needed |
|---|---|
| `atlas_intraday.py` | Add `_pending_broker_confirmation_trades()` helper + new report section builder + insert into report body assembly (near line 700/1602 where `_open_trades()` is currently called) |
| `atlas_eod_positions.py` | Same pattern — add helper + section builder + insert near line 159 |
| `atlas_db.py` | Would need 2 small new read-only helper queries: `journal_has_event(legacy_trades_id, event_type)` and `cash_ledger_has_credit_for_trade(trade_id)` (or equivalent inline SQL in the report scripts directly, avoiding any `atlas_db.py` change if preferred — smaller footprint) |

`atlas_macro_postmarket.py` is **not** affected — it never displayed holdings/positions in the first place.

---

## Return Fields

- **STATUS:** DESIGN_READY
- **affected_trades:** [1 (AAPL, backfill artifact), 2 (PBXT, backfill artifact), 3 (IBXT, backfill artifact), 16 (INTC, real pending confirmation)]
- **INTC_pending_confirmation:** YES
- **reports_affected:** [atlas_intraday.py, atlas_eod_positions.py] — atlas_macro_postmarket.py not affected (no holdings display); no standalone holdings-summary script exists
- **proposed_report_section:** "⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING" — ticker, exit trigger price, stop, trigger time, estimated P/L, broker_confirmed=NO, cash_credit=NO; filtered to exclude backfill artifacts via `entry_price != exit_price` AND `broker_ref IS NOT NULL`
- **files_likely_affected:** atlas_intraday.py, atlas_eod_positions.py, optionally atlas_db.py (2 small read-only helper queries)
- **risk_level:** LOW (report-only, additive, no lifecycle/strategy/stop/target/exit changes)
- **patch_recommended:** YES (surfacing a real, live, unconfirmed broker exit is a genuine visibility gap in a manual-trading system — recommend proceeding to a staged patch once approved)
- **production changes:** NONE
