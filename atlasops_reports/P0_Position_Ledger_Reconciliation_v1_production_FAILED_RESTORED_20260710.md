# Position Ledger Reconciliation v1 — Production Execution Evidence

## Final status

- **STATUS = FAIL — FULL DB RESTORED**
- **production touched = YES temporarily; final production DB restored byte-for-byte**
- Position Management reconciliation probe: **NOT RUN** because mandatory balancing gate failed.
- No restart, Telegram send, schedule/config change, strategy change, canonical trade edit, or cash edit was retained.

## Pre-repair state

- Production DB: `/Users/yasser/scripts/atlas.db`
- SHA256: `00eded2791541d71de2e1e1fed50e21e7fdf5b30fb5e778c239a650fece93c8d`
- Integrity: `ok`
- Foreign-key violations: `0`
- Exact preimages: all nine guards passed (RL trade/lot/cash, PENG trade/no-lot/cash, LASR trade/lot, zero repair keys).
- Full counts: `{"account": 1, "broker_position_display_snapshots": 0, "broker_reconciliation": 0, "cash_ledger": 25, "ema_retry_candidates": 0, "evidence_attachments": 1, "handoff": 16, "invariant_checks": 89, "ledger_postings": 54, "manual_trade_overrides": 1, "pending_pullbacks": 54, "portfolio_event_journal": 92, "position_lots": 68, "report_snapshots": 121, "signals": 36129, "trades": 105, "valuation_marks": 74}`
- Full exact subject rows are preserved in `/tmp/p0_position_ledger_reconciliation_v1_prod_20260710T204055Z/output/execution.json` and the pre-audit artifact; secrets were not accessed.

## Backup

- Path: `/Users/yasser/scripts/archive/atlas_20260710T204234Z_position_ledger_reconciliation_v1_predeploy.bak.db`
- SHA256: `00eded2791541d71de2e1e1fed50e21e7fdf5b30fb5e778c239a650fece93c8d`
- Matches immediate pre-repair production SHA: `True`
- Backup integrity: `ok`
- Backup FK violations: `0`

## Authorized runner and copied-DB rehearsal

- Runner: `/tmp/p0_position_ledger_reconciliation_v1_prod_20260710T204055Z/src/reconcile_position_lots.py`
- Runner SHA256: `c02bef544602e49e7032d6ac5474906a3beb8c47b9b2c3eb89fc6245b8fe1128`
- Change from staged logic: only the production-path refusal was relaxed; SQL/preimages/event keys/posting values/subjects were unchanged.
- `py_compile`: PASS
- Fresh copied-production-DB first run produced expected deltas: position_lots +1, events +3, postings +5; trades/cash/broker/valuation unchanged.
- Copied-DB second run was byte-identical: SHA `6cae6992b25551536912c41e8f386106ec27823989660b9e519cf20236404921` before and after rerun.

## Production attempt and mandatory failure

The guarded production transaction committed the exact expected row-count changes, then immediate verification detected a mandatory posting-balance defect:

- Actual count deltas: `{"account": 0, "broker_position_display_snapshots": 0, "broker_reconciliation": 0, "cash_ledger": 0, "ema_retry_candidates": 0, "evidence_attachments": 0, "handoff": 0, "invariant_checks": 0, "ledger_postings": 5, "manual_trade_overrides": 0, "pending_pullbacks": 0, "portfolio_event_journal": 3, "position_lots": 1, "report_snapshots": 0, "signals": 0, "trades": 0, "valuation_marks": 0}`
- Expected row/table deltas: exact match — PASS
- New event posting balances: `[{"event_id": 93, "total": 0}, {"event_id": 94, "total": 0}]`
- Gate `new_posting_sets_balance_zero`: **FAIL**

Root cause: the staged RL three-posting values are internally inconsistent. They were:

- CASH `+287899`
- POSITION:RL `-300000`
- REALIZED_PNL `+12101`

Their sum is `+24202`, not zero. The correct sign implied by the required realized P&L `-12101` would be negative, but changing that staged posting value was outside this execution authorization. I therefore did not improvise a production repair.

All other immediate checks passed before rollback: exact deltas, unrelated logical rows unchanged, trades unchanged, cash unchanged, deterministic keys once, five postings, RL/PENG/LASR row shapes, PENG zero sell events, broker/display/valuation counts unchanged, integrity and FK checks.

## Rollback and final production state

Rollback was performed from the full verified DB backup after a fresh idle gate.

- Restored production SHA256: `00eded2791541d71de2e1e1fed50e21e7fdf5b30fb5e778c239a650fece93c8d`
- Backup SHA256: `00eded2791541d71de2e1e1fed50e21e7fdf5b30fb5e778c239a650fece93c8d`
- Byte-identical: **YES**
- Integrity: `ok`
- FK violations: `0`
- Final repair-key count: `0`
- Final RL lot 64: `OPEN`
- Final PENG trade 111 lot count: `0`
- Final LASR lot 68 stop: `59.82`
- Final table counts equal the pre-repair counts.

## Expected versus actual retained deltas

Because rollback restored the complete DB file, final retained deltas are zero for every table. No canonical trades or cash rows changed, and none of the staged ledger repair rows remain.

## Idempotency and Position Management probe

- Production second-run idempotency: **NOT RUN**; the first-run balancing gate failed and required immediate rollback.
- Read-only Position Management reconciliation probe: **NOT RUN**; the repair was not safely retained.

## Required next action

Stage a corrected RL posting sign/value, rerun copied-DB balance and byte-identical idempotency proof, then obtain a new explicit production authorization. The current package must not be re-executed unchanged.
