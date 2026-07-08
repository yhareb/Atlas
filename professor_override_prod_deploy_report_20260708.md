# PROFESSOR_OVERRIDE_PROD_DEPLOY — Production Deployment Evidence Report

Generated: 2026-07-08T21:53:34
Scope: production durable Professor hold override lifecycle + approved INTC trade id 16 correction only.

## Status

PROFESSOR_OVERRIDE_PROD_DEPLOY_STATUS: PASS

## Executive Summary

- Target files and production DB were backed up before writes.
- `manual_trade_overrides` was created in production DB and event-journal CHECK compatibility was widened safely.
- Staged code was copied to production, pycache cleared, compile/import passed.
- Copied-DB smoke passed before INTC production correction.
- INTC trade id 16 is OPEN with an active Professor hold override; SELL NOW is suppressed while HOLDING shows manual override / stop breached / high risk.
- No broker action, no cash ledger movement, and no stop/target/risk/strategy changes were made.

## Required Return Fields

```yaml
PROFESSOR_OVERRIDE_PROD_DEPLOY_STATUS: PASS
backups_created: YES
DB_migration_result: PASS
event_journal_constraint_result: WIDENED_PASS
code_deploy_result: PASS
INTC_correction_result: PASS
smoke_result: PASS
INTC_status_OPEN: YES
active_override_exists: YES
SELL_NOW_suppressed_for_INTC: YES
INTC_in_HOLDING_manual_override: YES
broker_pending_excludes_INTC: YES
cash_ledger_unchanged: YES
no_broker_action: YES
no_strategy_risk_change: YES
rollback_performed: NO
attached_markdown_filename: /Users/yasser/scripts/professor_override_prod_deploy_report_20260708.md
production changes: durable Professor hold override lifecycle + INTC correction only
```

## Backups

```json
{
  "timestamp": "20260708_215329",
  "dir": "/Users/yasser/scripts/backups_prof_override_prod_20260708_215329",
  "db": "/Users/yasser/scripts/atlas.db.bak_prof_override_prod_20260708_215329",
  "file_shas": {
    "atlas_db.py": "dee59dea71a427871ef61a74c735641b9bb297df4f2292868c1598f0b986ba7b",
    "atlas_portfolio.py": "9779397a9fba9e66683699e9b8b508f9c08fa1cf6b70b183efe75e097705897d",
    "atlas_intraday.py": "a3dde41d6de982624424c953dd5eabf1cc433e6ce3396f00c40f59e4e53414d5",
    "atlas_report_blocks.py": "fa0289e8db99ff2cafb8097951570b6b884110ad06aac64c26496338501b6714",
    "atlas_report_authority.py": "cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b",
    "atlas_eod_positions.py": "12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1"
  },
  "db_sha": "e841e1096e7b07b7c2e379ef804a30d7594fe51fb17a311a43fa4a2680ffa960"
}
```

## Evidence State JSON

```json
{
  "status": "PASS",
  "timestamp_start": "2026-07-08T21:53:28",
  "prod_dir": "/Users/yasser/scripts",
  "stage_dir": "/tmp/prof_override_stage/src",
  "db": "/Users/yasser/scripts/atlas.db",
  "checks": {
    "processes": "",
    "db_locks": "",
    "prod_shas_before": {
      "atlas_db.py": "dee59dea71a427871ef61a74c735641b9bb297df4f2292868c1598f0b986ba7b",
      "atlas_portfolio.py": "9779397a9fba9e66683699e9b8b508f9c08fa1cf6b70b183efe75e097705897d",
      "atlas_intraday.py": "a3dde41d6de982624424c953dd5eabf1cc433e6ce3396f00c40f59e4e53414d5",
      "atlas_report_blocks.py": "fa0289e8db99ff2cafb8097951570b6b884110ad06aac64c26496338501b6714",
      "atlas_report_authority.py": "cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b",
      "atlas_eod_positions.py": "12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1"
    },
    "staged_shas": {
      "atlas_db.py": "cd7825fd319239ae36982b1cfdd7a5e8a0684252a4ba008e72a28be442873b11",
      "atlas_portfolio.py": "e31f4b56d7dbec2dfe4d5f91e707abf5934233b34c3bf058ce9c12a9f82ff37c",
      "atlas_intraday.py": "c1e9087083630a0bac198dc9aeff6939373977c38c01047139c2c93728259600",
      "atlas_report_blocks.py": "b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a",
      "atlas_report_authority.py": "cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b",
      "atlas_eod_positions.py": "12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1"
    },
    "broker_reality_confirmation": {
      "source": "Professor approval/directive in current chat + DB evidence; broker not touched",
      "professor_confirms_keep_intc": true,
      "db_positive_intc_cash_credit_rows": [],
      "db_broker_sell_submitted_events_trade16": [],
      "db_broker_sell_filled_events_trade16": [],
      "broker_api_touched": false
    },
    "INTC_status_OPEN": true,
    "active_override_exists": true,
    "SELL_NOW_suppressed_for_INTC": true,
    "override_survives_two_cycles": true,
    "INTC_in_HOLDING_manual_override": true,
    "broker_pending_excludes_INTC": true,
    "cash_ledger_unchanged": true,
    "no_broker_action": true,
    "no_strategy_risk_change": true
  },
  "backups": {
    "timestamp": "20260708_215329",
    "dir": "/Users/yasser/scripts/backups_prof_override_prod_20260708_215329",
    "db": "/Users/yasser/scripts/atlas.db.bak_prof_override_prod_20260708_215329",
    "file_shas": {
      "atlas_db.py": "dee59dea71a427871ef61a74c735641b9bb297df4f2292868c1598f0b986ba7b",
      "atlas_portfolio.py": "9779397a9fba9e66683699e9b8b508f9c08fa1cf6b70b183efe75e097705897d",
      "atlas_intraday.py": "a3dde41d6de982624424c953dd5eabf1cc433e6ce3396f00c40f59e4e53414d5",
      "atlas_report_blocks.py": "fa0289e8db99ff2cafb8097951570b6b884110ad06aac64c26496338501b6714",
      "atlas_report_authority.py": "cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b",
      "atlas_eod_positions.py": "12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1"
    },
    "db_sha": "e841e1096e7b07b7c2e379ef804a30d7594fe51fb17a311a43fa4a2680ffa960"
  },
  "pre": {
    "intc_initial": {
      "trade": {
        "id": 16,
        "ticker": "INTC",
        "status": "CLOSED",
        "quantity": 7.70534157,
        "entry_price": 129.78,
        "stop_loss": 113.02,
        "target_price": 162.25,
        "risk_pct": 0.5,
        "exit_price": 106.73,
        "exit_at": "2026-07-08 16:50:17",
        "realized_pnl": -163.44999999999996,
        "realized_pnl_pct": -17.991986438588377,
        "broker_ref": "P780203310",
        "manual_stop_lock": 0,
        "updated_at": "2026-07-08 16:50:17"
      },
      "cash_rows_like_intc": [
        {
          "id": 6,
          "ts": "2026-06-25 14:26:24",
          "amount": -1002.0992289546,
          "reason": "Broker fill INTC P780203310: 7.70534157 sh @ 129.78 plus fees 2.1",
          "balance_after": 30047.51
        }
      ],
      "latest_cash": {
        "id": 23,
        "ts": "2026-07-08 16:37:36",
        "amount": -2000.000056,
        "reason": "Broker fill PENG PENG_ORDER_FILLED_SCREENSHOT_20260708: 26.42008 sh @ 75.7 plus fees 0.0",
        "balance_after": 27303.28
      },
      "manual_overrides": [],
      "events": [
        {
          "id": 85,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 17:10:22",
          "effective_at": "2026-07-07 17:10:22",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.12\", \"stop_loss\": \"113.02\", \"note\": \"Second (current, live) close, confirmed via P0K-5 next-cycle verification with a real live quote. No matching cash_ledger credit posted yet -- known lag pattern, not a new anomaly.\"}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close2_live"
        },
        {
          "id": 84,
          "event_type": "REVERSAL",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 21:04:41",
          "effective_at": "2026-07-07 21:04:41",
          "payload_json": "{\"ticker\": \"INTC\", \"note\": \"P0K3 production correction: reopened trade id 16 to OPEN per Prof's broker screenshot showing INTC still live at eToro/Wio; DB had prematurely closed it via stop-hit.\"}",
          "source": "backfill_p0k3_correction",
          "prof_approved": 1,
          "idempotency_key": "legacy_trade_16_p0k3_reversal"
        },
        {
          "id": 83,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 13:40:20",
          "effective_at": "2026-07-07 13:40:20",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.97\", \"stop_loss\": \"113.02\", \"note\": \"First close, later reverted by P0K3 manual correction. No matching cash_ledger credit found (P0K-1 anomaly).\"}",
          "source": "backfill_from_p0k3_backup",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close1_reverted"
        },
        {
          "id": 82,
          "event_type": "BROKER_BUY_FILLED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-06-25 14:08:30",
          "effective_at": "2026-06-25 14:08:30",
          "payload_json": "{\"ticker\": \"INTC\", \"quantity\": \"7.70534157\", \"entry_price\": \"129.78\", \"matched_cash_ledger_id\": 6}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_buy"
        }
      ]
    },
    "integrity_before": {
      "integrity_check": [
        "ok"
      ],
      "foreign_key_check": []
    },
    "portfolio_event_journal_sql_before": "CREATE TABLE portfolio_event_journal (\n    id                  INTEGER PRIMARY KEY AUTOINCREMENT,\n    event_type          TEXT NOT NULL,\n    ticker              TEXT,\n    lot_id              INTEGER,\n    occurred_at         DATETIME NOT NULL,\n    recorded_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    effective_at        DATETIME NOT NULL,\n    payload_json        TEXT NOT NULL,\n    source              TEXT NOT NULL,\n    evidence_id         INTEGER,\n    prof_approved       INTEGER NOT NULL DEFAULT 0,\n    supersedes_id       INTEGER,\n    linked_reversal_id  INTEGER,\n    idempotency_key     TEXT UNIQUE,\n    legacy_trades_id       INTEGER,\n    legacy_cash_ledger_id  INTEGER,\n    CHECK (event_type IN (\n        'ACCOUNT_OPENED',\n        'BUY_DECISION', 'BROKER_BUY_FILLED', 'SELL_DECISION', 'BROKER_SELL_FILLED',\n        'STOP_HIT_DETECTED', 'CASH_DEBIT_POSTED', 'CASH_CREDIT_POSTED',\n        'MANUAL_CORRECTION', 'RECONCILIATION_EXCEPTION',\n        'REVERSAL', 'VALUATION_MARK_RECORDED', 'IDEMPOTENT_DUPLICATE_REJECTED'\n    )),\n    FOREIGN KEY (lot_id) REFERENCES position_lots(id),\n    FOREIGN KEY (evidence_id) REFERENCES evidence_attachments(id),\n    FOREIGN KEY (supersedes_id) REFERENCES portfolio_event_journal(id),\n    FOREIGN KEY (linked_reversal_id) REFERENCES portfolio_event_journal(id),\n    FOREIGN KEY (legacy_trades_id) REFERENCES trades(id),\n    FOREIGN KEY (legacy_cash_ledger_id) REFERENCES cash_ledger(id)\n)",
    "portfolio_event_journal_indexes_before": [
      {
        "name": "idx_journal_event_type",
        "sql": "CREATE INDEX idx_journal_event_type ON portfolio_event_journal(event_type)"
      },
      {
        "name": "idx_journal_legacy_cash",
        "sql": "CREATE INDEX idx_journal_legacy_cash ON portfolio_event_journal(legacy_cash_ledger_id)"
      },
      {
        "name": "idx_journal_legacy_trades",
        "sql": "CREATE INDEX idx_journal_legacy_trades ON portfolio_event_journal(legacy_trades_id)"
      },
      {
        "name": "idx_journal_lot",
        "sql": "CREATE INDEX idx_journal_lot ON portfolio_event_journal(lot_id)"
      },
      {
        "name": "idx_journal_ticker_effective",
        "sql": "CREATE INDEX idx_journal_ticker_effective ON portfolio_event_journal(ticker, effective_at)"
      }
    ],
    "portfolio_event_journal_triggers_before": [],
    "intc_before_correction": {
      "trade": {
        "id": 16,
        "ticker": "INTC",
        "status": "CLOSED",
        "quantity": 7.70534157,
        "entry_price": 129.78,
        "stop_loss": 113.02,
        "target_price": 162.25,
        "risk_pct": 0.5,
        "exit_price": 106.73,
        "exit_at": "2026-07-08 16:50:17",
        "realized_pnl": -163.44999999999996,
        "realized_pnl_pct": -17.991986438588377,
        "broker_ref": "P780203310",
        "manual_stop_lock": 0,
        "updated_at": "2026-07-08 16:50:17"
      },
      "cash_rows_like_intc": [
        {
          "id": 6,
          "ts": "2026-06-25 14:26:24",
          "amount": -1002.0992289546,
          "reason": "Broker fill INTC P780203310: 7.70534157 sh @ 129.78 plus fees 2.1",
          "balance_after": 30047.51
        }
      ],
      "latest_cash": {
        "id": 23,
        "ts": "2026-07-08 16:37:36",
        "amount": -2000.000056,
        "reason": "Broker fill PENG PENG_ORDER_FILLED_SCREENSHOT_20260708: 26.42008 sh @ 75.7 plus fees 0.0",
        "balance_after": 27303.28
      },
      "manual_overrides": [],
      "events": [
        {
          "id": 85,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 17:10:22",
          "effective_at": "2026-07-07 17:10:22",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.12\", \"stop_loss\": \"113.02\", \"note\": \"Second (current, live) close, confirmed via P0K-5 next-cycle verification with a real live quote. No matching cash_ledger credit posted yet -- known lag pattern, not a new anomaly.\"}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close2_live"
        },
        {
          "id": 84,
          "event_type": "REVERSAL",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 21:04:41",
          "effective_at": "2026-07-07 21:04:41",
          "payload_json": "{\"ticker\": \"INTC\", \"note\": \"P0K3 production correction: reopened trade id 16 to OPEN per Prof's broker screenshot showing INTC still live at eToro/Wio; DB had prematurely closed it via stop-hit.\"}",
          "source": "backfill_p0k3_correction",
          "prof_approved": 1,
          "idempotency_key": "legacy_trade_16_p0k3_reversal"
        },
        {
          "id": 83,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 13:40:20",
          "effective_at": "2026-07-07 13:40:20",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.97\", \"stop_loss\": \"113.02\", \"note\": \"First close, later reverted by P0K3 manual correction. No matching cash_ledger credit found (P0K-1 anomaly).\"}",
          "source": "backfill_from_p0k3_backup",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close1_reverted"
        },
        {
          "id": 82,
          "event_type": "BROKER_BUY_FILLED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-06-25 14:08:30",
          "effective_at": "2026-06-25 14:08:30",
          "payload_json": "{\"ticker\": \"INTC\", \"quantity\": \"7.70534157\", \"entry_price\": \"129.78\", \"matched_cash_ledger_id\": 6}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_buy"
        }
      ]
    }
  },
  "post": {
    "manual_trade_overrides_created": true,
    "portfolio_event_journal_sql_after": "CREATE TABLE portfolio_event_journal (\n    id                  INTEGER PRIMARY KEY AUTOINCREMENT,\n    event_type          TEXT NOT NULL,\n    ticker              TEXT,\n    lot_id              INTEGER,\n    occurred_at         DATETIME NOT NULL,\n    recorded_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,\n    effective_at        DATETIME NOT NULL,\n    payload_json        TEXT NOT NULL,\n    source              TEXT NOT NULL,\n    evidence_id         INTEGER,\n    prof_approved       INTEGER NOT NULL DEFAULT 0,\n    supersedes_id       INTEGER,\n    linked_reversal_id  INTEGER,\n    idempotency_key     TEXT UNIQUE,\n    legacy_trades_id       INTEGER,\n    legacy_cash_ledger_id  INTEGER,\n    CHECK (event_type IN (\n        'ACCOUNT_OPENED',\n        'BUY_DECISION', 'BROKER_BUY_FILLED', 'SELL_DECISION', 'BROKER_SELL_FILLED',\n        'STOP_HIT_DETECTED', 'CASH_DEBIT_POSTED', 'CASH_CREDIT_POSTED',\n        'MANUAL_CORRECTION', 'RECONCILIATION_EXCEPTION',\n        'REVERSAL', 'VALUATION_MARK_RECORDED', 'IDEMPOTENT_DUPLICATE_REJECTED', 'BROKER_SELL_SUBMITTED', 'PROFESSOR_HOLD_OVERRIDE_ACTIVE', 'PROFESSOR_HOLD_OVERRIDE_DEACTIVATED'\n    )),\n    FOREIGN KEY (lot_id) REFERENCES position_lots(id),\n    FOREIGN KEY (evidence_id) REFERENCES evidence_attachments(id),\n    FOREIGN KEY (supersedes_id) REFERENCES portfolio_event_journal(id),\n    FOREIGN KEY (linked_reversal_id) REFERENCES portfolio_event_journal(id),\n    FOREIGN KEY (legacy_trades_id) REFERENCES trades(id),\n    FOREIGN KEY (legacy_cash_ledger_id) REFERENCES cash_ledger(id)\n)",
    "event_journal_constraint_result": "WIDENED_PASS",
    "portfolio_event_journal_row_count": 85,
    "integrity_after_migration": {
      "integrity_check": [
        "ok"
      ],
      "foreign_key_check": []
    },
    "prod_shas_after_copy": {
      "atlas_db.py": "cd7825fd319239ae36982b1cfdd7a5e8a0684252a4ba008e72a28be442873b11",
      "atlas_portfolio.py": "e31f4b56d7dbec2dfe4d5f91e707abf5934233b34c3bf058ce9c12a9f82ff37c",
      "atlas_intraday.py": "c1e9087083630a0bac198dc9aeff6939373977c38c01047139c2c93728259600",
      "atlas_report_blocks.py": "b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a",
      "atlas_report_authority.py": "cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b",
      "atlas_eod_positions.py": "12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1"
    },
    "compile": {
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    "compile_after_pycache_clear": {
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    "import": {
      "returncode": 0,
      "stdout": "IMPORT_OK\n",
      "stderr": ""
    },
    "intc_after_correction": {
      "trade": {
        "id": 16,
        "ticker": "INTC",
        "status": "OPEN",
        "quantity": 7.70534157,
        "entry_price": 129.78,
        "stop_loss": 113.02,
        "target_price": 162.25,
        "risk_pct": 0.5,
        "exit_price": null,
        "exit_at": null,
        "realized_pnl": null,
        "realized_pnl_pct": null,
        "broker_ref": "P780203310",
        "manual_stop_lock": 0,
        "updated_at": "2026-07-08 17:53:30"
      },
      "cash_rows_like_intc": [
        {
          "id": 6,
          "ts": "2026-06-25 14:26:24",
          "amount": -1002.0992289546,
          "reason": "Broker fill INTC P780203310: 7.70534157 sh @ 129.78 plus fees 2.1",
          "balance_after": 30047.51
        }
      ],
      "latest_cash": {
        "id": 23,
        "ts": "2026-07-08 16:37:36",
        "amount": -2000.000056,
        "reason": "Broker fill PENG PENG_ORDER_FILLED_SCREENSHOT_20260708: 26.42008 sh @ 75.7 plus fees 0.0",
        "balance_after": 27303.28
      },
      "manual_overrides": [
        {
          "id": 1,
          "trade_id": 16,
          "ticker": "INTC",
          "override_type": "PROFESSOR_HOLD_OVERRIDE",
          "status": "ACTIVE",
          "reason": "Professor explicitly instructed: keep INTC / move to holdings despite stop breach",
          "created_at": "2026-07-08 17:53:30",
          "created_by": "Prof",
          "deactivated_at": null,
          "deactivated_reason": null,
          "source_message": "I\u2019m keeping INTC. Move it to holdings."
        }
      ],
      "events": [
        {
          "id": 86,
          "event_type": "PROFESSOR_HOLD_OVERRIDE_ACTIVE",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-08 17:53:30",
          "effective_at": "2026-07-08 17:53:30",
          "payload_json": "{\"trade_id\":16,\"override_id\":1,\"override_type\":\"PROFESSOR_HOLD_OVERRIDE\",\"state\":\"OPEN + STOP_BREACHED + PROFESSOR_HOLD_OVERRIDE_ACTIVE\",\"system_wanted\":\"SELL\",\"professor_override\":\"HOLD\",\"broker_sell_submitted\":false}",
          "source": "professor_telegram_instruction",
          "prof_approved": 1,
          "idempotency_key": "PROF_HOLD_OVERRIDE_INTC_16_20260708_PROD"
        },
        {
          "id": 85,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 17:10:22",
          "effective_at": "2026-07-07 17:10:22",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.12\", \"stop_loss\": \"113.02\", \"note\": \"Second (current, live) close, confirmed via P0K-5 next-cycle verification with a real live quote. No matching cash_ledger credit posted yet -- known lag pattern, not a new anomaly.\"}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close2_live"
        },
        {
          "id": 84,
          "event_type": "REVERSAL",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 21:04:41",
          "effective_at": "2026-07-07 21:04:41",
          "payload_json": "{\"ticker\": \"INTC\", \"note\": \"P0K3 production correction: reopened trade id 16 to OPEN per Prof's broker screenshot showing INTC still live at eToro/Wio; DB had prematurely closed it via stop-hit.\"}",
          "source": "backfill_p0k3_correction",
          "prof_approved": 1,
          "idempotency_key": "legacy_trade_16_p0k3_reversal"
        },
        {
          "id": 83,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 13:40:20",
          "effective_at": "2026-07-07 13:40:20",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.97\", \"stop_loss\": \"113.02\", \"note\": \"First close, later reverted by P0K3 manual correction. No matching cash_ledger credit found (P0K-1 anomaly).\"}",
          "source": "backfill_from_p0k3_backup",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close1_reverted"
        },
        {
          "id": 82,
          "event_type": "BROKER_BUY_FILLED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-06-25 14:08:30",
          "effective_at": "2026-06-25 14:08:30",
          "payload_json": "{\"ticker\": \"INTC\", \"quantity\": \"7.70534157\", \"entry_price\": \"129.78\", \"matched_cash_ledger_id\": 6}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_buy"
        }
      ]
    },
    "intc_preserved_field_changes": {},
    "readonly_verification": {
      "exit_eval_1": {
        "ticker": "INTC",
        "action": "HOLD",
        "qty": 7,
        "entry": 129.78,
        "reason": "Professor hold override active; stop breached; last 106.73 <= stop 113.02",
        "last": 106.73,
        "stop": 113.02,
        "target": 162.25,
        "gain_R": -1.38,
        "regime_ok": true,
        "manual_override": true,
        "stop_breached": true,
        "system_wanted": "SELL",
        "risk": "HIGH",
        "broker_sell_submitted": false,
        "earnings_context": {},
        "earnings_warning": null,
        "fda_calendar": {},
        "fda_warning": null
      },
      "exit_eval_2": {
        "ticker": "INTC",
        "action": "HOLD",
        "qty": 7,
        "entry": 129.78,
        "reason": "Professor hold override active; stop breached; last 106.73 <= stop 113.02",
        "last": 106.73,
        "stop": 113.02,
        "target": 162.25,
        "gain_R": -1.38,
        "regime_ok": true,
        "manual_override": true,
        "stop_breached": true,
        "system_wanted": "SELL",
        "risk": "HIGH",
        "broker_sell_submitted": false,
        "earnings_context": {},
        "earnings_warning": null,
        "fda_calendar": {},
        "fda_warning": null
      },
      "pending_tickers": [],
      "holding_rows": [
        {
          "ticker": "INTC",
          "action": "BUY",
          "price": 129.78,
          "quantity": 7.70534157,
          "timestamp": "2026-06-25 14:08:30",
          "stop_loss": 113.02,
          "risk_pct": 0.5,
          "target_price": 162.25,
          "manual_stop_lock": 0,
          "entry_price": 129.78,
          "current_price": 106.73,
          "current_price_source": "[PROVIDER]",
          "price_authority": {
            "ticker": "INTC",
            "display_price": 106.73,
            "valuation_price": 106.73,
            "source_class": "PROVIDER",
            "source_label": "[PROVIDER]",
            "provider": "intraday_cycle",
            "timestamp": null,
            "age_seconds": null,
            "is_valuation_valid": true,
            "reason": "provider_price_valid"
          },
          "manual_override": true,
          "stop_breached": true,
          "system_wanted": "SELL",
          "risk": "HIGH",
          "broker_sell_submitted": false
        }
      ],
      "holding_text": "\n\u2501\u2501\u2501 \ud83d\udcbc HOLDING (5) \u2501\u2501\u2501\n\n1. \ud83d\udd34 INTC (Intel)\n   \ud83d\udcb5 Entry [DB] $129.78\n   \ud83d\udc40 Now [PROVIDER] $106.73\n   \ud83d\udea6 Stop [DB]/[TFE] $113.02\n   \ud83c\udfaf Target [DB]/[TFE] $162.25\n   [RENDER-CALC] (\u221218% \u00b7 \u2212$178 \u00b7 ~$822)\n   \u26a0\ufe0f MANUAL OVERRIDE \u2014 STOP BREACHED \u2014 HIGH RISK\n   System wanted: SELL\n   Professor override: HOLD\n   Broker sell placed: NO\n   Broker confirmation pending: NO\n\n2. \ud83d\udfe2 SYNA (Synaptics)\n   \ud83d\udcb5 Entry [DB] $126.44\n   \ud83d\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $126.44)\n   \ud83d\udea6 Stop [DB]/[TFE] $113.35\n   \ud83c\udfaf Target [DB]/[TFE] $156.61\n   [RENDER-CALC] valuation unavailable \u2014 excluded from totals (provider_and_cache_missing)\n\n3. \ud83d\udfe2 BAC (Bank of America)\n   \ud83d\udcb5 Entry [DB] $57.10\n   \ud83d\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $57.10)\n   \ud83d\udea6 Stop [DB]/[TFE] $57.11\n   \ud83c\udfaf Target [DB]/[TFE] $60.62\n   [RENDER-CALC] valuation unavailable \u2014 excluded from totals (provider_and_cache_missing)\n\n4. \ud83d\udfe2 ABNB (Airbnb)\n   \ud83d\udcb5 Entry [DB] $143.03\n   \ud83d\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $143.03)\n   \ud83d\udea6 Stop [DB]/[TFE] $135.96\n   \ud83c\udfaf Target [DB]/[TFE] $157.17\n   [RENDER-CALC] valuation unavailable \u2014 excluded from totals (provider_and_cache_missing)\n\n5. \ud83d\udfe2 PENG (Penguin Solutions)\n   \ud83d\udcb5 Entry [DB] $75.70\n   \ud83d\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $75.70)\n   \ud83d\udea6 Stop [DB]/[TFE] $62.04\n   \ud83c\udfaf Target [DB]/[TFE] $100.01\n   [RENDER-CALC] valuation unavailable \u2014 excluded from totals (provider_and_cache_missing)\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\u26a0\ufe0f Valuation PARTIAL [RENDER-CALC]: excluded SYNA, BAC, ABNB, PENG \u2014 price unavailable/stale\n\ud83d\udcbc Valued Invested [RENDER-CALC]: $1,000\n\ud83d\udcca Current Value [RENDER-CALC]:  $822\n\ud83d\udcc8 Blended ROI [RENDER-CALC]:    \u221217.8% (\u2212$178)\n"
    },
    "final_intc_state": {
      "trade": {
        "id": 16,
        "ticker": "INTC",
        "status": "OPEN",
        "quantity": 7.70534157,
        "entry_price": 129.78,
        "stop_loss": 113.02,
        "target_price": 162.25,
        "risk_pct": 0.5,
        "exit_price": null,
        "exit_at": null,
        "realized_pnl": null,
        "realized_pnl_pct": null,
        "broker_ref": "P780203310",
        "manual_stop_lock": 0,
        "updated_at": "2026-07-08 17:53:30"
      },
      "cash_rows_like_intc": [
        {
          "id": 6,
          "ts": "2026-06-25 14:26:24",
          "amount": -1002.0992289546,
          "reason": "Broker fill INTC P780203310: 7.70534157 sh @ 129.78 plus fees 2.1",
          "balance_after": 30047.51
        }
      ],
      "latest_cash": {
        "id": 23,
        "ts": "2026-07-08 16:37:36",
        "amount": -2000.000056,
        "reason": "Broker fill PENG PENG_ORDER_FILLED_SCREENSHOT_20260708: 26.42008 sh @ 75.7 plus fees 0.0",
        "balance_after": 27303.28
      },
      "manual_overrides": [
        {
          "id": 1,
          "trade_id": 16,
          "ticker": "INTC",
          "override_type": "PROFESSOR_HOLD_OVERRIDE",
          "status": "ACTIVE",
          "reason": "Professor explicitly instructed: keep INTC / move to holdings despite stop breach",
          "created_at": "2026-07-08 17:53:30",
          "created_by": "Prof",
          "deactivated_at": null,
          "deactivated_reason": null,
          "source_message": "I\u2019m keeping INTC. Move it to holdings."
        }
      ],
      "events": [
        {
          "id": 86,
          "event_type": "PROFESSOR_HOLD_OVERRIDE_ACTIVE",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-08 17:53:30",
          "effective_at": "2026-07-08 17:53:30",
          "payload_json": "{\"trade_id\":16,\"override_id\":1,\"override_type\":\"PROFESSOR_HOLD_OVERRIDE\",\"state\":\"OPEN + STOP_BREACHED + PROFESSOR_HOLD_OVERRIDE_ACTIVE\",\"system_wanted\":\"SELL\",\"professor_override\":\"HOLD\",\"broker_sell_submitted\":false}",
          "source": "professor_telegram_instruction",
          "prof_approved": 1,
          "idempotency_key": "PROF_HOLD_OVERRIDE_INTC_16_20260708_PROD"
        },
        {
          "id": 85,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 17:10:22",
          "effective_at": "2026-07-07 17:10:22",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.12\", \"stop_loss\": \"113.02\", \"note\": \"Second (current, live) close, confirmed via P0K-5 next-cycle verification with a real live quote. No matching cash_ledger credit posted yet -- known lag pattern, not a new anomaly.\"}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close2_live"
        },
        {
          "id": 84,
          "event_type": "REVERSAL",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 21:04:41",
          "effective_at": "2026-07-07 21:04:41",
          "payload_json": "{\"ticker\": \"INTC\", \"note\": \"P0K3 production correction: reopened trade id 16 to OPEN per Prof's broker screenshot showing INTC still live at eToro/Wio; DB had prematurely closed it via stop-hit.\"}",
          "source": "backfill_p0k3_correction",
          "prof_approved": 1,
          "idempotency_key": "legacy_trade_16_p0k3_reversal"
        },
        {
          "id": 83,
          "event_type": "STOP_HIT_DETECTED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-07-07 13:40:20",
          "effective_at": "2026-07-07 13:40:20",
          "payload_json": "{\"ticker\": \"INTC\", \"exit_price\": \"112.97\", \"stop_loss\": \"113.02\", \"note\": \"First close, later reverted by P0K3 manual correction. No matching cash_ledger credit found (P0K-1 anomaly).\"}",
          "source": "backfill_from_p0k3_backup",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_close1_reverted"
        },
        {
          "id": 82,
          "event_type": "BROKER_BUY_FILLED",
          "ticker": "INTC",
          "legacy_trades_id": 16,
          "occurred_at": "2026-06-25 14:08:30",
          "effective_at": "2026-06-25 14:08:30",
          "payload_json": "{\"ticker\": \"INTC\", \"quantity\": \"7.70534157\", \"entry_price\": \"129.78\", \"matched_cash_ledger_id\": 6}",
          "source": "backfill_legacy_trades",
          "prof_approved": 0,
          "idempotency_key": "legacy_trade_16_buy"
        }
      ]
    }
  },
  "smoke": {
    "script": "/tmp/prof_override_prod_smoke.py",
    "db": "/tmp/prof_override_prod_smoke.db",
    "returncode": 0,
    "stdout": "{\n  \"test_stop_breached_no_override\": true,\n  \"test_stop_breached_override_active\": true,\n  \"test_override_survives_two_cycles\": true,\n  \"test_report_manual_override\": true,\n  \"test_broker_submitted_pending\": true,\n  \"test_broker_filled_not_pending\": true,\n  \"test_override_inactive_stop_breached\": true,\n  \"pending_tickers_sample\": [\n    \"TSTSUB\"\n  ],\n  \"override_table_created\": true,\n  \"intc_like_reopened\": true,\n  \"report_excerpt\": \"\\n\\u2501\\u2501\\u2501 \\ud83d\\udcbc HOLDING (1) \\u2501\\u2501\\u2501\\n\\n1. \\ud83d\\udd34 INTC (Intel)\\n   \\ud83d\\udcb5 Entry [DB] $129.78\\n   \\ud83d\\udc40 Now [PROVIDER] $106.73\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $113.02\\n   \\ud83c\\udfaf Target [DB]/[TFE] $162.25\\n   [RENDER-CALC] (\\u221218% \\u00b7 \\u2212$178 \\u00b7 ~$822)\\n   \\u26a0\\ufe0f MANUAL OVERRIDE \\u2014 STOP BREACHED \\u2014 HIGH RISK\\n   System wanted: SELL\\n   Professor override: HOLD\\n   Broker sell placed: NO\\n   Broker confirmation pending: NO\\n\\n\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\n\\ud83d\\udcbc Total Invested [RENDER-CALC]: $1,000\\n\\ud83d\\udcca Current Value [RENDER-CALC]:  $822\\n\\ud83d\\udcc8 Blended ROI [RENDER-CALC]:    \\u221217.8% (\\u2212$178)\\n\",\n  \"res_override\": {\n    \"ticker\": \"INTC\",\n    \"action\": \"HOLD\",\n    \"qty\": 7,\n    \"entry\": 129.78,\n    \"reason\": \"Professor hold override active; stop breached; last 106.73 <= stop 113.02\",\n    \"last\": 106.73,\n    \"stop\": 113.02,\n    \"target\": 162.25,\n    \"gain_R\": -1.38,\n    \"regime_ok\": true,\n    \"manual_override\": true,\n    \"stop_breached\": true,\n    \"system_wanted\": \"SELL\",\n    \"risk\": \"HIGH\",\n    \"broker_sell_submitted\": false,\n    \"earnings_context\": {},\n    \"earnings_warning\": null,\n    \"fda_calendar\": {},\n    \"fda_warning\": null\n  },\n  \"res_no_override\": {\n    \"ticker\": \"ZZZT\",\n    \"action\": \"SELL\",\n    \"reason\": \"Persisted stop hit; last 80.00 <= stop 90.00\",\n    \"price\": 80.0,\n    \"qty\": 1,\n    \"entry\": 100.0,\n    \"stop\": 90.0,\n    \"target\": 120.0,\n    \"regime_ok\": true,\n    \"macro_alert\": null\n  },\n  \"res_inactive\": {\n    \"ticker\": \"INTC\",\n    \"action\": \"SELL\",\n    \"reason\": \"Persisted stop hit; last 106.73 <= stop 113.02\",\n    \"price\": 106.73,\n    \"qty\": 7,\n    \"entry\": 129.78,\n    \"stop\": 113.02,\n    \"target\": 162.25,\n    \"regime_ok\": true,\n    \"macro_alert\": null\n  },\n  \"intc_row\": {\n    \"id\": 16,\n    \"ticker\": \"INTC\",\n    \"status\": \"OPEN\",\n    \"quantity\": 7.70534157,\n    \"entry_price\": 129.78,\n    \"exit_price\": null,\n    \"realized_pnl\": null,\n    \"stop_loss\": 113.02,\n    \"target_price\": 162.25,\n    \"broker_ref\": \"P780203310\"\n  }\n}\n",
    "stderr": "",
    "parsed": {
      "test_stop_breached_no_override": true,
      "test_stop_breached_override_active": true,
      "test_override_survives_two_cycles": true,
      "test_report_manual_override": true,
      "test_broker_submitted_pending": true,
      "test_broker_filled_not_pending": true,
      "test_override_inactive_stop_breached": true,
      "pending_tickers_sample": [
        "TSTSUB"
      ],
      "override_table_created": true,
      "intc_like_reopened": true,
      "report_excerpt": "\n\u2501\u2501\u2501 \ud83d\udcbc HOLDING (1) \u2501\u2501\u2501\n\n1. \ud83d\udd34 INTC (Intel)\n   \ud83d\udcb5 Entry [DB] $129.78\n   \ud83d\udc40 Now [PROVIDER] $106.73\n   \ud83d\udea6 Stop [DB]/[TFE] $113.02\n   \ud83c\udfaf Target [DB]/[TFE] $162.25\n   [RENDER-CALC] (\u221218% \u00b7 \u2212$178 \u00b7 ~$822)\n   \u26a0\ufe0f MANUAL OVERRIDE \u2014 STOP BREACHED \u2014 HIGH RISK\n   System wanted: SELL\n   Professor override: HOLD\n   Broker sell placed: NO\n   Broker confirmation pending: NO\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\ud83d\udcbc Total Invested [RENDER-CALC]: $1,000\n\ud83d\udcca Current Value [RENDER-CALC]:  $822\n\ud83d\udcc8 Blended ROI [RENDER-CALC]:    \u221217.8% (\u2212$178)\n",
      "res_override": {
        "ticker": "INTC",
        "action": "HOLD",
        "qty": 7,
        "entry": 129.78,
        "reason": "Professor hold override active; stop breached; last 106.73 <= stop 113.02",
        "last": 106.73,
        "stop": 113.02,
        "target": 162.25,
        "gain_R": -1.38,
        "regime_ok": true,
        "manual_override": true,
        "stop_breached": true,
        "system_wanted": "SELL",
        "risk": "HIGH",
        "broker_sell_submitted": false,
        "earnings_context": {},
        "earnings_warning": null,
        "fda_calendar": {},
        "fda_warning": null
      },
      "res_no_override": {
        "ticker": "ZZZT",
        "action": "SELL",
        "reason": "Persisted stop hit; last 80.00 <= stop 90.00",
        "price": 80.0,
        "qty": 1,
        "entry": 100.0,
        "stop": 90.0,
        "target": 120.0,
        "regime_ok": true,
        "macro_alert": null
      },
      "res_inactive": {
        "ticker": "INTC",
        "action": "SELL",
        "reason": "Persisted stop hit; last 106.73 <= stop 113.02",
        "price": 106.73,
        "qty": 7,
        "entry": 129.78,
        "stop": 113.02,
        "target": 162.25,
        "regime_ok": true,
        "macro_alert": null
      },
      "intc_row": {
        "id": 16,
        "ticker": "INTC",
        "status": "OPEN",
        "quantity": 7.70534157,
        "entry_price": 129.78,
        "exit_price": null,
        "realized_pnl": null,
        "stop_loss": 113.02,
        "target_price": 162.25,
        "broker_ref": "P780203310"
      }
    }
  },
  "rollback_performed": false,
  "errors": [],
  "commands": [
    {
      "cmd": "ps -axo pid,ppid,stat,etime,command | egrep 'atlas_(intraday|portfolio|daily|manage|macro|eod|pre_market|post_market)|pre_market_report|post_market_report' | grep -v egrep || true",
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "cmd": "lsof /Users/yasser/scripts/atlas.db || true",
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "cmd": "python3 -m py_compile /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_portfolio.py /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/atlas_report_blocks.py /Users/yasser/scripts/atlas_report_authority.py /Users/yasser/scripts/atlas_eod_positions.py",
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "cmd": "find /Users/yasser/scripts -type d -name '__pycache__' -prune -exec rm -rf {} +",
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "cmd": "python3 -m py_compile /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_portfolio.py /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/atlas_report_blocks.py /Users/yasser/scripts/atlas_report_authority.py /Users/yasser/scripts/atlas_eod_positions.py",
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "cmd": "python3 - <<'PY'\nimport sys\nsys.path.insert(0, '/Users/yasser/scripts')\nimport atlas_db, atlas_portfolio, atlas_intraday, atlas_report_blocks, atlas_report_authority, atlas_eod_positions\nprint('IMPORT_OK')\nPY",
      "returncode": 0,
      "stdout": "IMPORT_OK\n",
      "stderr": ""
    },
    {
      "cmd": "python3 /tmp/prof_override_prod_smoke.py",
      "returncode": 0,
      "stdout": "{\n  \"test_stop_breached_no_override\": true,\n  \"test_stop_breached_override_active\": true,\n  \"test_override_survives_two_cycles\": true,\n  \"test_report_manual_override\": true,\n  \"test_broker_submitted_pending\": true,\n  \"test_broker_filled_not_pending\": true,\n  \"test_override_inactive_stop_breached\": true,\n  \"pending_tickers_sample\": [\n    \"TSTSUB\"\n  ],\n  \"override_table_created\": true,\n  \"intc_like_reopened\": true,\n  \"report_excerpt\": \"\\n\\u2501\\u2501\\u2501 \\ud83d\\udcbc HOLDING (1) \\u2501\\u2501\\u2501\\n\\n1. \\ud83d\\udd34 INTC (Intel)\\n   \\ud83d\\udcb5 Entry [DB] $129.78\\n   \\ud83d\\udc40 Now [PROVIDER] $106.73\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $113.02\\n   \\ud83c\\udfaf Target [DB]/[TFE] $162.25\\n   [RENDER-CALC] (\\u221218% \\u00b7 \\u2212$178 \\u00b7 ~$822)\\n   \\u26a0\\ufe0f MANUAL OVERRIDE \\u2014 STOP BREACHED \\u2014 HIGH RISK\\n   System wanted: SELL\\n   Professor override: HOLD\\n   Broker sell placed: NO\\n   Broker confirmation pending: NO\\n\\n\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\n\\ud83d\\udcbc Total Invested [RENDER-CALC]: $1,000\\n\\ud83d\\udcca Current Value [RENDER-CALC]:  $822\\n\\ud83d\\udcc8 Blended ROI [RENDER-CALC]:    \\u221217.8% (\\u2212$178)\\n\",\n  \"res_override\": {\n    \"ticker\": \"INTC\",\n    \"action\": \"HOLD\",\n    \"qty\": 7,\n    \"entry\": 129.78,\n    \"reason\": \"Professor hold override active; stop breached; last 106.73 <= stop 113.02\",\n    \"last\": 106.73,\n    \"stop\": 113.02,\n    \"target\": 162.25,\n    \"gain_R\": -1.38,\n    \"regime_ok\": true,\n    \"manual_override\": true,\n    \"stop_breached\": true,\n    \"system_wanted\": \"SELL\",\n    \"risk\": \"HIGH\",\n    \"broker_sell_submitted\": false,\n    \"earnings_context\": {},\n    \"earnings_warning\": null,\n    \"fda_calendar\": {},\n    \"fda_warning\": null\n  },\n  \"res_no_override\": {\n    \"ticker\": \"ZZZT\",\n    \"action\": \"SELL\",\n    \"reason\": \"Persisted stop hit; last 80.00 <= stop 90.00\",\n    \"price\": 80.0,\n    \"qty\": 1,\n    \"entry\": 100.0,\n    \"stop\": 90.0,\n    \"target\": 120.0,\n    \"regime_ok\": true,\n    \"macro_alert\": null\n  },\n  \"res_inactive\": {\n    \"ticker\": \"INTC\",\n    \"action\": \"SELL\",\n    \"reason\": \"Persisted stop hit; last 106.73 <= stop 113.02\",\n    \"price\": 106.73,\n    \"qty\": 7,\n    \"entry\": 129.78,\n    \"stop\": 113.02,\n    \"target\": 162.25,\n    \"regime_ok\": true,\n    \"macro_alert\": null\n  },\n  \"intc_row\": {\n    \"id\": 16,\n    \"ticker\": \"INTC\",\n    \"status\": \"OPEN\",\n    \"quantity\": 7.70534157,\n    \"entry_price\": 129.78,\n    \"exit_price\": null,\n    \"realized_pnl\": null,\n    \"stop_loss\": 113.02,\n    \"target_price\": 162.25,\n    \"broker_ref\": \"P780203310\"\n  }\n}\n",
      "stderr": ""
    },
    {
      "cmd": "python3 - <<'PY'\n\nimport os, sys, json\nsys.path.insert(0,'/Users/yasser/scripts')\nimport atlas_db, atlas_portfolio as port\nport._last_price=lambda ticker: 106.73 if ticker=='INTC' else 80.0\nbars=[{'c':100.0,'h':101.0,'l':99.0,'t':1710000000000+i*86400000,'v':1000000} for i in range(90)]\nport.get_massive_aggs=lambda ticker, days=90: bars\nport.calculate_atr=lambda aggs: 2.0\nport.check_regime=lambda: (True,'risk-on verify')\nport.check_earnings_context=lambda ticker: {}\nport.check_fda_calendar=lambda ticker, holding=True: {}\nintc=dict(atlas_db.get_trade(16)); intc['ticker']='INTC'\nres1=port.evaluate_exit(intc, dry_run=True, regime=(True,'risk-on verify'))\nres2=port.evaluate_exit(intc, dry_run=True, regime=(True,'risk-on verify'))\npending=atlas_db.get_pending_broker_confirmation_trades()\npending_tickers=[r['ticker'] for r in pending]\nimport atlas_intraday\nsummary={'exit_results':[res1]}\nrows=atlas_intraday._authority_open_position_rows(summary)\nhold_lines=atlas_intraday._holding_lines(summary)\nout={'exit_eval_1':res1,'exit_eval_2':res2,'pending_tickers':pending_tickers,'holding_rows':[r for r in rows if str(r.get('ticker')).upper()=='INTC'],'holding_text':'\\n'.join(hold_lines)}\nprint(json.dumps(out, indent=2, default=str))\n\nPY",
      "returncode": 0,
      "stdout": "{\n  \"exit_eval_1\": {\n    \"ticker\": \"INTC\",\n    \"action\": \"HOLD\",\n    \"qty\": 7,\n    \"entry\": 129.78,\n    \"reason\": \"Professor hold override active; stop breached; last 106.73 <= stop 113.02\",\n    \"last\": 106.73,\n    \"stop\": 113.02,\n    \"target\": 162.25,\n    \"gain_R\": -1.38,\n    \"regime_ok\": true,\n    \"manual_override\": true,\n    \"stop_breached\": true,\n    \"system_wanted\": \"SELL\",\n    \"risk\": \"HIGH\",\n    \"broker_sell_submitted\": false,\n    \"earnings_context\": {},\n    \"earnings_warning\": null,\n    \"fda_calendar\": {},\n    \"fda_warning\": null\n  },\n  \"exit_eval_2\": {\n    \"ticker\": \"INTC\",\n    \"action\": \"HOLD\",\n    \"qty\": 7,\n    \"entry\": 129.78,\n    \"reason\": \"Professor hold override active; stop breached; last 106.73 <= stop 113.02\",\n    \"last\": 106.73,\n    \"stop\": 113.02,\n    \"target\": 162.25,\n    \"gain_R\": -1.38,\n    \"regime_ok\": true,\n    \"manual_override\": true,\n    \"stop_breached\": true,\n    \"system_wanted\": \"SELL\",\n    \"risk\": \"HIGH\",\n    \"broker_sell_submitted\": false,\n    \"earnings_context\": {},\n    \"earnings_warning\": null,\n    \"fda_calendar\": {},\n    \"fda_warning\": null\n  },\n  \"pending_tickers\": [],\n  \"holding_rows\": [\n    {\n      \"ticker\": \"INTC\",\n      \"action\": \"BUY\",\n      \"price\": 129.78,\n      \"quantity\": 7.70534157,\n      \"timestamp\": \"2026-06-25 14:08:30\",\n      \"stop_loss\": 113.02,\n      \"risk_pct\": 0.5,\n      \"target_price\": 162.25,\n      \"manual_stop_lock\": 0,\n      \"entry_price\": 129.78,\n      \"current_price\": 106.73,\n      \"current_price_source\": \"[PROVIDER]\",\n      \"price_authority\": {\n        \"ticker\": \"INTC\",\n        \"display_price\": 106.73,\n        \"valuation_price\": 106.73,\n        \"source_class\": \"PROVIDER\",\n        \"source_label\": \"[PROVIDER]\",\n        \"provider\": \"intraday_cycle\",\n        \"timestamp\": null,\n        \"age_seconds\": null,\n        \"is_valuation_valid\": true,\n        \"reason\": \"provider_price_valid\"\n      },\n      \"manual_override\": true,\n      \"stop_breached\": true,\n      \"system_wanted\": \"SELL\",\n      \"risk\": \"HIGH\",\n      \"broker_sell_submitted\": false\n    }\n  ],\n  \"holding_text\": \"\\n\\u2501\\u2501\\u2501 \\ud83d\\udcbc HOLDING (5) \\u2501\\u2501\\u2501\\n\\n1. \\ud83d\\udd34 INTC (Intel)\\n   \\ud83d\\udcb5 Entry [DB] $129.78\\n   \\ud83d\\udc40 Now [PROVIDER] $106.73\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $113.02\\n   \\ud83c\\udfaf Target [DB]/[TFE] $162.25\\n   [RENDER-CALC] (\\u221218% \\u00b7 \\u2212$178 \\u00b7 ~$822)\\n   \\u26a0\\ufe0f MANUAL OVERRIDE \\u2014 STOP BREACHED \\u2014 HIGH RISK\\n   System wanted: SELL\\n   Professor override: HOLD\\n   Broker sell placed: NO\\n   Broker confirmation pending: NO\\n\\n2. \\ud83d\\udfe2 SYNA (Synaptics)\\n   \\ud83d\\udcb5 Entry [DB] $126.44\\n   \\ud83d\\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $126.44)\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $113.35\\n   \\ud83c\\udfaf Target [DB]/[TFE] $156.61\\n   [RENDER-CALC] valuation unavailable \\u2014 excluded from totals (provider_and_cache_missing)\\n\\n3. \\ud83d\\udfe2 BAC (Bank of America)\\n   \\ud83d\\udcb5 Entry [DB] $57.10\\n   \\ud83d\\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $57.10)\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $57.11\\n   \\ud83c\\udfaf Target [DB]/[TFE] $60.62\\n   [RENDER-CALC] valuation unavailable \\u2014 excluded from totals (provider_and_cache_missing)\\n\\n4. \\ud83d\\udfe2 ABNB (Airbnb)\\n   \\ud83d\\udcb5 Entry [DB] $143.03\\n   \\ud83d\\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $143.03)\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $135.96\\n   \\ud83c\\udfaf Target [DB]/[TFE] $157.17\\n   [RENDER-CALC] valuation unavailable \\u2014 excluded from totals (provider_and_cache_missing)\\n\\n5. \\ud83d\\udfe2 PENG (Penguin Solutions)\\n   \\ud83d\\udcb5 Entry [DB] $75.70\\n   \\ud83d\\udc40 Now PRICE_UNAVAILABLE [FALLBACK]/reference only (entry $75.70)\\n   \\ud83d\\udea6 Stop [DB]/[TFE] $62.04\\n   \\ud83c\\udfaf Target [DB]/[TFE] $100.01\\n   [RENDER-CALC] valuation unavailable \\u2014 excluded from totals (provider_and_cache_missing)\\n\\n\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\n\\u26a0\\ufe0f Valuation PARTIAL [RENDER-CALC]: excluded SYNA, BAC, ABNB, PENG \\u2014 price unavailable/stale\\n\\ud83d\\udcbc Valued Invested [RENDER-CALC]: $1,000\\n\\ud83d\\udcca Current Value [RENDER-CALC]:  $822\\n\\ud83d\\udcc8 Blended ROI [RENDER-CALC]:    \\u221217.8% (\\u2212$178)\\n\"\n}\n",
      "stderr": ""
    }
  ],
  "timestamp_end": "2026-07-08T21:53:34"
}
```

production changes: durable Professor hold override lifecycle + INTC correction only