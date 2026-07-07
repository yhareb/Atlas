# READ-ONLY INTC EOD Reconciliation Check

**Date:** 2026-07-07
**Scope:** READ-ONLY. No patch/deploy/DB writes/strategy/report/routing/scheduler/env/Telegram/stops/targets/exits changes.

## Question
EOD report shows 4 holdings, no INTC. Is this correct?

## Findings

### 1. Current `trades` row for INTC
```
id=16  ticker=INTC  status=CLOSED  entry_price=129.78  exit_price=112.12
entry_at=2026-06-25 14:08:30  exit_at=2026-07-07 17:10:22  quantity=7.70534157
```

### 2. Is INTC CLOSED after the 17:10:22 stop-hit at 112.12?
**YES.** `trades.id=16` status=CLOSED, exit_price=112.12, exit_at=2026-07-07 17:10:22 — matches exactly.

Full history (from `portfolio_event_journal`, legacy_trades_id=16):
| id | event_type | occurred_at | note |
|---|---|---|---|
| 82 | BROKER_BUY_FILLED | 2026-06-25 14:08:30 | entry, matched cash_ledger id=6 |
| 83 | STOP_HIT_DETECTED | 2026-07-07 13:40:20 | first close @112.97 — later reverted (P0K3 anomaly, no matching cash credit) |
| 84 | REVERSAL | 2026-07-07 21:04:41 | *(historical journal entry, occurred_at appears to be a backfill/logging artifact — see note below)* P0K3 correction reopened trade 16 per Prof's broker screenshot showing INTC still live |
| 85 | STOP_HIT_DETECTED | 2026-07-07 17:10:22 | **second (current, live) close @112.12**, confirmed via P0K-5 next-cycle verification with a real live quote; no matching cash_ledger credit posted yet — known lag pattern, not a new anomaly |

Note: event id=84's `occurred_at` (21:04:41) postdates id=85 (17:10:22) in this listing — this reflects the historical P0K reversal/re-close sequence already documented in prior sessions (P0K-1 through P0K-5), not a new inconsistency; not re-investigated further as it's outside this task's scope.

### 3. Broker-confirmed sell / cash_ledger credit for INTC?
**NO.** Only one INTC row exists in `cash_ledger`: id=6, the original **buy** fill (`-1002.10`, "Broker fill INTC ... 7.70534157 sh @ 129.78"). No sell/credit row for INTC exists anywhere in `cash_ledger` (21 total rows checked, none reference an INTC sell).

### 4. Does EOD report correctly filter only OPEN trades?
**YES.** `atlas_eod_positions.py:113-115`:
```python
def _open_trades() -> list[dict[str, Any]]:
    rows = atlas_db.get_trades(status="OPEN", limit=1000)
    ...
```
Strict `status="OPEN"` filter against the legacy `trades` table. INTC (`status=CLOSED`) is correctly excluded by this filter — this is the same simple legacy-table query, unrelated to the bookkeeping/valuation_marks lot-attribution work (P0L-17 through P0L-23).

Corroborating log evidence — two EOD-position reports fired today:
- Earlier: **5 holdings** (INTC still counted, "Worst: INTC −6%")
- Later (after the 17:10:22 stop-hit): **4 holdings** (SYNA/RL/BAC/ABNB only, "Cash: $26,424")

This is exactly the expected before/after behavior of the filter reacting to INTC's status flip.

### 5. Is broker confirmation still pending?
**YES.** No `BROKER_SELL_FILLED` event exists for INTC in `portfolio_event_journal` — only `STOP_HIT_DETECTED` (twice). No cash_ledger sell credit posted. Broker-side sell confirmation remains outstanding.

### 6. Do bookkeeping tables show STOP_HIT_DETECTED but not BROKER_SELL_FILLED?
**YES, confirmed exactly.** `portfolio_event_journal` for INTC contains: `BROKER_BUY_FILLED` (1), `STOP_HIT_DETECTED` (2), `REVERSAL` (1) — **zero** `BROKER_SELL_FILLED` events. `position_lots` id=67 (legacy_trades_id=16) status=CLOSED, consistent with the stop-hit detection but with no broker-fill event backing the closure yet.

## Conclusion
The trade-level `status=CLOSED` (driving the EOD OPEN-filter) is set from **stop-hit detection**, not from a confirmed broker sell fill. The EOD report's *filtering logic* is behaving correctly given the current `trades.status` value — it's doing exactly what it's designed to do. But the *underlying trade state* itself is provisional: INTC is being treated as closed on a detected stop-hit while broker-side sell confirmation and the corresponding cash_ledger credit are still outstanding. This is a known/pre-existing lag pattern (explicitly flagged in the P0K series and again in journal event 85's own note: "known lag pattern, not a new anomaly") — not a new bug, and not something this read-only check changes.

---

## Return Fields

- **INTC_EOD_STATUS:** CONFIRMED_CORRECT_GIVEN_CURRENT_TRADE_STATE
- **INTC_trade_status:** CLOSED (trades.id=16)
- **INTC_exit_price_exit_at:** 112.12 @ 2026-07-07 17:10:22
- **broker_sell_confirmed:** NO
- **cash_ledger_credit_exists:** NO
- **EOD_omission_correct:** YES (EOD filter is `status="OPEN"` on legacy `trades`; INTC=CLOSED is correctly excluded — the filter logic is not at fault. The open question is upstream: whether trades.status=CLOSED should have been set yet without a confirmed broker sell fill.)
- **remaining_action_needed:** Broker-side sell confirmation for INTC is still outstanding (no BROKER_SELL_FILLED event, no cash_ledger credit). This is a known lag pattern per prior P0K/P0L journal notes, not flagged as a new anomaly. No action taken by this read-only check; any correction to trade state or cash_ledger would require a separate explicit work order.
- **production changes:** NONE
