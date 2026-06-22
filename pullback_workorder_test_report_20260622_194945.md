# Atlas Pullback Work Order Test Report

Run: 20260622_194945
DB backup: /Users/yasser/scripts/atlas_db_backup_20260622_194945_pullbacktest.sqlite

## Base account
```json
{
  "account": {
    "starting_cash": 37000.0,
    "manual_cash_changes": 0.0,
    "realized_pnl": 0.0,
    "open_invested": 0,
    "cash": 37000.0,
    "equity": 37000.0
  },
  "open_positions": []
}
```

## Scenario A — extended 4/4 arms pullback, no buy
```json
{
  "id": "A",
  "name": "extended 4/4 arms pullback, no buy",
  "decision": {
    "ticker": "PBXT",
    "action": "WAIT",
    "reason": "WAITING FOR PULLBACK — PBXT (4/4 Pillars): price $110.00 = +8.0% over 10-EMA. Limit armed at $102.33 (3-day window).",
    "wait_type": "PULLBACK_ARMED",
    "entry": 102.33,
    "ema10": 101.82,
    "price": 110.0,
    "pct_over_ema": 8.0,
    "expires_at": "2026-06-25"
  },
  "pending": {
    "id": 1,
    "ticker": "PBXT",
    "status": "WAITING",
    "score": "4/4 Pillars",
    "signal": "🟢 BUY",
    "signal_json": "{\"ticker\": \"PBXT\", \"signal\": \"\\ud83d\\udfe2 BUY\", \"score\": \"4/4 Pillars\", \"entry_price\": 110.0, \"risk_card\": {\"stop_loss\": 104.0}}",
    "armed_at": "2026-06-22 15:49:45",
    "expires_at": "2026-06-25",
    "ema10": 101.81818181818181,
    "trigger_price": 102.33,
    "reference_price": 110.0,
    "pct_over_ema": 8.035714285714302,
    "filled_at": null,
    "expired_at": null,
    "updated_at": "2026-06-22 15:49:45",
    "signal_result": {
      "ticker": "PBXT",
      "signal": "🟢 BUY",
      "score": "4/4 Pillars",
      "entry_price": 110.0,
      "risk_card": {
        "stop_loss": 104.0
      }
    }
  },
  "open_lots_after": [],
  "telegram_ids": [
    226
  ]
}
```

## Scenario B — pending pullback fills through consider_buy
```json
{
  "id": "B",
  "name": "pending pullback fills through consider_buy",
  "decision": {
    "ticker": "PBXT",
    "action": "BUY",
    "reason": "Pulled back to armed 10-EMA limit 102.33 (last 100.40)",
    "entry": 102.33,
    "stop": 96.33,
    "shares": 61,
    "cost": 6242.13,
    "risk_pct": 1.0,
    "equity": 37000.0,
    "pending_id": 1,
    "from_pending_pullback": true
  },
  "ledger_open_rows": [
    {
      "id": 2,
      "ticker": "PBXT",
      "status": "OPEN",
      "quantity": 61,
      "entry_price": 102.33,
      "entry_at": "2026-06-22 15:49:47",
      "exit_price": null,
      "exit_at": null,
      "entry_fees": 0.0,
      "exit_fees": 0.0,
      "realized_pnl": null,
      "realized_pnl_pct": null,
      "parent_id": null,
      "notes": "Atlas v2 entry: Pulled back to armed 10-EMA limit 102.33 (last 100.40); stop 96.33; 1% risk on equity $37,000",
      "updated_at": "2026-06-22 15:49:47"
    }
  ],
  "vault": {
    "label": "B PBXT open push",
    "ok": true,
    "rows_pushed": 1,
    "tickers": [
      "PBXT"
    ],
    "error": null
  },
  "telegram_ids": [
    227
  ],
  "cleanup": {
    "ticker": "PBXT",
    "closed_ids": [
      2
    ]
  }
}
```

## Scenario C — pending expires after 3 trading days no touch
```json
{
  "id": "C",
  "name": "pending expires after 3 trading days no touch",
  "arm_decision": {
    "ticker": "EXPX",
    "action": "WAIT",
    "reason": "WAITING FOR PULLBACK — EXPX (4/4 Pillars): price $112.00 = +9.6% over 10-EMA. Limit armed at $102.69 (3-day window).",
    "wait_type": "PULLBACK_ARMED",
    "entry": 102.69,
    "ema10": 102.18,
    "price": 112.0,
    "pct_over_ema": 9.6,
    "expires_at": "2026-06-25"
  },
  "expire_decision": {
    "ticker": "EXPX",
    "action": "EXPIRE",
    "score": "4/4 Pillars",
    "reason": "PULLBACK EXPIRED — EXPX, no fill in 3 days.",
    "pending_id": 2
  },
  "pending_after": {
    "id": 2,
    "ticker": "EXPX",
    "status": "EXPIRED",
    "score": "4/4 Pillars",
    "signal": "🟢 BUY",
    "signal_json": "{\"ticker\": \"EXPX\", \"signal\": \"\\ud83d\\udfe2 BUY\", \"score\": \"4/4 Pillars\", \"entry_price\": 112.0, \"risk_card\": {\"stop_loss\": 106.0}}",
    "armed_at": "2026-06-15",
    "expires_at": "2026-06-21",
    "ema10": 102.18181818181817,
    "trigger_price": 102.69,
    "reference_price": 112.0,
    "pct_over_ema": 9.608540925266906,
    "filled_at": null,
    "expired_at": "2026-06-22 15:49:50",
    "updated_at": "2026-06-22 15:49:50",
    "signal_result": {
      "ticker": "EXPX",
      "signal": "🟢 BUY",
      "score": "4/4 Pillars",
      "entry_price": 112.0,
      "risk_card": {
        "stop_loss": 106.0
      }
    }
  },
  "telegram_ids": [
    228
  ]
}
```

## Scenario D — in-band signal buys immediately
```json
{
  "id": "D",
  "name": "in-band signal buys immediately",
  "decision": {
    "ticker": "IBXT",
    "action": "BUY",
    "reason": "Pulled back to 10-EMA 100.18 (close 101.00)",
    "entry": 101.0,
    "stop": 95.0,
    "shares": 61,
    "cost": 6161.0,
    "risk_pct": 1.0,
    "equity": 37000.0
  },
  "ledger_open_rows": [
    {
      "id": 3,
      "ticker": "IBXT",
      "status": "OPEN",
      "quantity": 61,
      "entry_price": 101.0,
      "entry_at": "2026-06-22 15:49:50",
      "exit_price": null,
      "exit_at": null,
      "entry_fees": 0.0,
      "exit_fees": 0.0,
      "realized_pnl": null,
      "realized_pnl_pct": null,
      "parent_id": null,
      "notes": "Atlas v2 entry: Pulled back to 10-EMA 100.18 (close 101.00); stop 95.0; 1% risk on equity $37,000",
      "updated_at": "2026-06-22 15:49:50"
    }
  ],
  "vault": {
    "label": "D IBXT open push",
    "ok": true,
    "rows_pushed": 1,
    "tickers": [
      "IBXT"
    ],
    "error": null
  },
  "telegram_ids": [
    229
  ],
  "cleanup": {
    "ticker": "IBXT",
    "closed_ids": [
      3
    ]
  }
}
```

## Telegram bodies + message IDs

### A arm extended
message_ids: [226]
ok: True
error: None

Body:
```text
⏳ WAITING FOR PULLBACK — PBXT (4/4 Pillars): price $110.00 = +8.0% over 10-EMA. Limit armed at $102.33 (3-day window).
```
stdout:
```text
[intraday] telegram chunk 1/1 sent on attempt 1: message_id=226
[intraday] telegram report sent: chunks=1 message_ids=[226]
```

### B pending fill BUY
message_ids: [227]
ok: True
error: None

Body:
```text
🦅 *Atlas Intraday — 11:49 ET*
*Regime:* RISK-ON (TEST RISK-ON)
*Account:* equity $36,882.27, cash $30,757.87, open positions 1

*🟢 BUY executed:*
PBXT 61 sh @ 102.33 — Pulled back to armed 10-EMA limit 102.33 (last 100.40)

*🔴 SELL executed:*
none

*⭐ Top candidates:*
🟢 BUY — PBXT (4/4 Pillars): entry $102.33, stop $96.33, size $6,242.13.

*⚪ WATCH (2/4):*
none

*🧠 Catalysts firing:*
none

*Result:* ACTION
```
stdout:
```text
[intraday] telegram chunk 1/1 sent on attempt 1: message_id=227
[intraday] telegram report sent: chunks=1 message_ids=[227]
```

### C pullback expired
message_ids: [228]
ok: True
error: None

Body:
```text
⌛ PULLBACK EXPIRED — EXPX, no fill in 3 days.
```
stdout:
```text
[intraday] telegram chunk 1/1 sent on attempt 1: message_id=228
[intraday] telegram report sent: chunks=1 message_ids=[228]
```

### D in-band immediate BUY
message_ids: [229]
ok: True
error: None

Body:
```text
🦅 *Atlas Intraday — 11:49 ET*
*Regime:* RISK-ON (TEST RISK-ON)
*Account:* equity $37,000.00, cash $30,839.00, open positions 1

*🟢 BUY executed:*
IBXT 61 sh @ 101.0 — Pulled back to 10-EMA 100.18 (close 101.00)

*🔴 SELL executed:*
none

*⭐ Top candidates:*
🟢 BUY — IBXT (4/4 Pillars): entry $101.00, stop $95.00, size $6,161.00.

*⚪ WATCH (2/4):*
none

*🧠 Catalysts firing:*
none

*Result:* ACTION
```
stdout:
```text
[intraday] telegram chunk 1/1 sent on attempt 1: message_id=229
[intraday] telegram report sent: chunks=1 message_ids=[229]
```

## Vault push evidence
```json
[
  {
    "label": "B PBXT open push",
    "ok": true,
    "rows_pushed": 1,
    "tickers": [
      "PBXT"
    ],
    "error": null
  },
  {
    "label": "PBXT close push",
    "ok": true,
    "rows_pushed": 1,
    "tickers": [
      "PBXT"
    ],
    "error": null
  },
  {
    "label": "D IBXT open push",
    "ok": true,
    "rows_pushed": 1,
    "tickers": [
      "IBXT"
    ],
    "error": null
  },
  {
    "label": "IBXT close push",
    "ok": true,
    "rows_pushed": 1,
    "tickers": [
      "IBXT"
    ],
    "error": null
  }
]
```

## Final account
```json
{
  "account": {
    "starting_cash": 37000.0,
    "manual_cash_changes": 0.0,
    "realized_pnl": 0.0,
    "open_invested": 0,
    "cash": 37000.0,
    "equity": 37000.0
  },
  "open_positions": [],
  "waiting_pullbacks": []
}
```
