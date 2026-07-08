# PROFESSOR_OVERRIDE_DEPLOY_PLAN — Read-Only Production Deployment Plan

Generated: 2026-07-08 21:41 ET
Scope: deployment plan only. No production patch, no production DB write, no broker action, no cash movement.

## Status

PROFESSOR_OVERRIDE_DEPLOY_PLAN_STATUS: READ_ONLY_DEPLOYMENT_PLAN_COMPLETE

## Executive Summary

- Production baseline SHAs and staged SHAs were verified from live files; target production files were not patched.
- Staged implementation exists under `/tmp/prof_override_stage/src/` and copied DB exists at `/tmp/prof_override_stage/atlas_stage.db`.
- Production DB currently has no `manual_trade_overrides` table and its `portfolio_event_journal.event_type` CHECK constraint does not accept the staged lifecycle event types.
- Deployment must include a DB backup, safe migration/rebuild for `manual_trade_overrides` and event-journal compatibility, then a separate approved INTC correction.
- INTC production correction must reopen trade id `16`, clear only provisional local exit/realized fields, preserve risk/price fields, add an active Professor hold override, and add no cash ledger entry.
- Production changes: NONE.

## Target Files

```text
/Users/yasser/scripts/atlas_db.py
/Users/yasser/scripts/atlas_portfolio.py
/Users/yasser/scripts/atlas_intraday.py
/Users/yasser/scripts/atlas_report_blocks.py
/Users/yasser/scripts/atlas_report_authority.py
/Users/yasser/scripts/atlas_eod_positions.py
```

## Production Baseline SHAs

Recorded read-only from production files:

```text
dee59dea71a427871ef61a74c735641b9bb297df4f2292868c1598f0b986ba7b  /Users/yasser/scripts/atlas_db.py
9779397a9fba9e66683699e9b8b508f9c08fa1cf6b70b183efe75e097705897d  /Users/yasser/scripts/atlas_portfolio.py
a3dde41d6de982624424c953dd5eabf1cc433e6ce3396f00c40f59e4e53414d5  /Users/yasser/scripts/atlas_intraday.py
fa0289e8db99ff2cafb8097951570b6b884110ad06aac64c26496338501b6714  /Users/yasser/scripts/atlas_report_blocks.py
cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b  /Users/yasser/scripts/atlas_report_authority.py
12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1  /Users/yasser/scripts/atlas_eod_positions.py
```

Production file evidence:

```json
{
  "atlas_db.py": {"size": 61599, "mtime": "2026-07-08T03:33:13"},
  "atlas_portfolio.py": {"size": 91869, "mtime": "2026-07-08T03:33:13"},
  "atlas_intraday.py": {"size": 109950, "mtime": "2026-07-08T20:22:46"},
  "atlas_report_blocks.py": {"size": 14905, "mtime": "2026-07-08T20:22:46"},
  "atlas_report_authority.py": {"size": 14134, "mtime": "2026-07-08T20:22:46"},
  "atlas_eod_positions.py": {"size": 11459, "mtime": "2026-07-08T20:22:46"}
}
```

## Staged SHAs

Verified from staged source and matching staged report values:

```text
cd7825fd319239ae36982b1cfdd7a5e8a0684252a4ba008e72a28be442873b11  /tmp/prof_override_stage/src/atlas_db.py
e31f4b56d7dbec2dfe4d5f91e707abf5934233b34c3bf058ce9c12a9f82ff37c  /tmp/prof_override_stage/src/atlas_portfolio.py
c1e9087083630a0bac198dc9aeff6939373977c38c01047139c2c93728259600  /tmp/prof_override_stage/src/atlas_intraday.py
b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a  /tmp/prof_override_stage/src/atlas_report_blocks.py
cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b  /tmp/prof_override_stage/src/atlas_report_authority.py
12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1  /tmp/prof_override_stage/src/atlas_eod_positions.py
```

Staged source evidence:

```json
{
  "atlas_db.py": {"size": 68594, "mtime": "2026-07-08T21:31:11"},
  "atlas_portfolio.py": {"size": 93220, "mtime": "2026-07-08T21:31:11"},
  "atlas_intraday.py": {"size": 110840, "mtime": "2026-07-08T21:34:35"},
  "atlas_report_blocks.py": {"size": 15797, "mtime": "2026-07-08T21:31:33"},
  "atlas_report_authority.py": {"size": 14134, "mtime": "2026-07-08T20:22:46"},
  "atlas_eod_positions.py": {"size": 11459, "mtime": "2026-07-08T20:22:46"}
}
```

## Staged Report Used

```text
/Users/yasser/scripts/professor_override_stage_report_20260708.md
```

Relevant staged report status values:

```yaml
PROFESSOR_OVERRIDE_STAGE_STATUS: STAGED_ONLY_COMPLETE
copied_DB_path: /tmp/prof_override_stage/atlas_stage.db
compile_result: PASS
override_table_created_in_copied_DB: YES
engine_override_behavior: PASS
report_override_behavior: PASS
broker_pending_requires_sell_submitted: YES
INTC_like_reopened_in_copied_DB: YES
no_production_DB_write: YES
no_production_file_change: YES
no_broker_action: YES
no_cash_movement: YES
ready_for_production_deployment_plan: YES
production changes: NONE
```

## Current Production DB Evidence — Read Only

Production DB path:

```text
/Users/yasser/scripts/atlas.db
```

Existing production tables include:

```text
account
broker_reconciliation
cash_ledger
ema_retry_candidates
evidence_attachments
handoff
invariant_checks
ledger_postings
pending_pullbacks
portfolio_event_journal
position_lots
report_snapshots
signals
sqlite_sequence
trades
valuation_marks
```

Production DB does **not** currently include:

```text
manual_trade_overrides
```

Production `portfolio_event_journal` CHECK constraint currently allows only:

```text
ACCOUNT_OPENED
BUY_DECISION
BROKER_BUY_FILLED
SELL_DECISION
BROKER_SELL_FILLED
STOP_HIT_DETECTED
CASH_DEBIT_POSTED
CASH_CREDIT_POSTED
MANUAL_CORRECTION
RECONCILIATION_EXCEPTION
REVERSAL
VALUATION_MARK_RECORDED
IDEMPOTENT_DUPLICATE_REJECTED
```

Production CHECK constraint currently does **not** allow staged lifecycle event types:

```text
BROKER_SELL_SUBMITTED
PROFESSOR_HOLD_OVERRIDE_ACTIVE
PROFESSOR_HOLD_OVERRIDE_DEACTIVATED
```

Current production INTC row read-only:

```json
{
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
  "broker_ref": "P780203310"
}
```

Current production INTC notes contain human-readable override text, but this is **not** valid trading authority per Prof rule and per fix design.

## DB Migration Plan

DB_migration_plan:

1. **Idle-window gate before DB work**
   - Confirm no active `atlas_intraday.py`, pre-market, post-market, or portfolio process is writing the DB.
   - Confirm no broker automation or Telegram alert run is in progress.
   - If a process is active, stop and wait; do not migrate during an active report/write cycle.

2. **Backup production DB first**
   - Create timestamped backup:

```bash
cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/atlas.db.bak_prof_override_deploy_YYYYMMDD_HHMMSS
```

3. **Run SQLite integrity check before migration**

```bash
sqlite3 /Users/yasser/scripts/atlas.db 'PRAGMA integrity_check;'
```

Expected:

```text
ok
```

4. **Create durable override table**

Use the staged storage model:

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
    source_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_manual_trade_overrides_active
ON manual_trade_overrides(trade_id, ticker, override_type, status);
```

5. **Lifecycle values**
   - Active override row:
     - `override_type='PROFESSOR_HOLD_OVERRIDE'`
     - `status='ACTIVE'`
     - `deactivated_at IS NULL`
   - Inactive/deactivated row:
     - `status='INACTIVE'`
     - `deactivated_at=CURRENT_TIMESTAMP`
     - `deactivated_reason='<reason>'`

6. **Authority rule**
   - `manual_trade_overrides` is the machine-readable source of authority for manual hold overrides.
   - `trades.notes` remains non-authoritative human context only.
   - No parsing of notes as trading authority.

## Event Journal Constraint Plan

event_journal_constraint_plan:

Preferred safe path: **migrate/rebuild the `portfolio_event_journal` CHECK constraint explicitly** before writing any staged lifecycle event types.

Reason:
- Staged helper logic can write/read these lifecycle events:
  - `BROKER_SELL_SUBMITTED`
  - `PROFESSOR_HOLD_OVERRIDE_ACTIVE`
  - `PROFESSOR_HOLD_OVERRIDE_DEACTIVATED`
- Production CHECK constraint currently rejects those event types.
- SQLite cannot alter a CHECK constraint in place; it requires table rebuild.

Safe rebuild plan:

1. Backup DB first.
2. Begin exclusive transaction.
3. Create `portfolio_event_journal_new` with the same columns, FKs, and CHECK list, widened to include:

```text
BROKER_SELL_SUBMITTED
PROFESSOR_HOLD_OVERRIDE_ACTIVE
PROFESSOR_HOLD_OVERRIDE_DEACTIVATED
```

4. Copy all existing rows:

```sql
INSERT INTO portfolio_event_journal_new (
    id, event_type, ticker, lot_id, occurred_at, recorded_at, effective_at,
    payload_json, source, evidence_id, prof_approved, supersedes_id,
    linked_reversal_id, idempotency_key, legacy_trades_id, legacy_cash_ledger_id
)
SELECT
    id, event_type, ticker, lot_id, occurred_at, recorded_at, effective_at,
    payload_json, source, evidence_id, prof_approved, supersedes_id,
    linked_reversal_id, idempotency_key, legacy_trades_id, legacy_cash_ledger_id
FROM portfolio_event_journal;
```

5. Validate copied row count equals original row count.
6. Drop old table.
7. Rename new table to `portfolio_event_journal`.
8. Recreate any indexes/triggers discovered on the original table.
9. Run:

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

10. Commit only if all checks pass.
11. If any check fails, rollback and restore DB backup.

Fallback if Prof rejects event-journal CHECK migration:
- Store override state only in `manual_trade_overrides`.
- Do **not** write `PROFESSOR_HOLD_OVERRIDE_ACTIVE` / `DEACTIVATED` to `portfolio_event_journal`.
- Do **not** use `BROKER_SELL_SUBMITTED` in the current constrained event journal.
- Add a separate lifecycle table for broker sell submission, or defer broker-submitted event writes until a separate approved schema migration.
- This fallback is less aligned with staged code because staged pending-broker smoke used `BROKER_SELL_SUBMITTED`; it would require adjusting code scope before deploy.

Recommended deployment decision:
- Use the preferred safe rebuild plan so staged broker-pending logic can rely on `BROKER_SELL_SUBMITTED` and the override lifecycle can have an auditable journal trail.

## Production INTC DB Correction Plan

INTC_DB_correction_plan:

Prerequisite: explicit Prof approval before write.

1. Backup DB first:

```bash
cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/atlas.db.bak_intc_prof_override_fix_YYYYMMDD_HHMMSS
```

2. Verify broker reality manually/provided by Prof before DB write:
   - Broker still has INTC open.
   - No actual broker sell was submitted.
   - No broker sell fill/cash credit exists.

3. Reopen trade id `16` only if broker still open:

```sql
UPDATE trades
SET status='OPEN',
    exit_price=NULL,
    exit_at=NULL,
    realized_pnl=NULL,
    realized_pnl_pct=NULL,
    updated_at=CURRENT_TIMESTAMP
WHERE id=16
  AND ticker='INTC';
```

4. Preserve unchanged:

```text
quantity = 7.70534157
entry_price = 129.78
stop_loss = 113.02
target_price = 162.25
risk_pct = 0.5
broker_ref = P780203310
manual_stop_lock = unchanged
notes = unchanged except optional non-authoritative audit note if approved
```

5. Add active durable override:

```sql
INSERT INTO manual_trade_overrides (
    trade_id,
    ticker,
    override_type,
    status,
    reason,
    created_by,
    source_message
) VALUES (
    16,
    'INTC',
    'PROFESSOR_HOLD_OVERRIDE',
    'ACTIVE',
    'Professor explicitly instructed: keep INTC / move to holdings despite stop breach',
    'Prof',
    'I’m keeping INTC. Move it to holdings.'
);
```

6. Optional audit event only after CHECK migration is confirmed:

```sql
INSERT INTO portfolio_event_journal (
    event_type,
    ticker,
    occurred_at,
    effective_at,
    payload_json,
    source,
    prof_approved,
    legacy_trades_id,
    idempotency_key
) VALUES (
    'PROFESSOR_HOLD_OVERRIDE_ACTIVE',
    'INTC',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP,
    '{"trade_id":16,"override_type":"PROFESSOR_HOLD_OVERRIDE","state":"OPEN + STOP_BREACHED + PROFESSOR_HOLD_OVERRIDE_ACTIVE","system_wanted":"SELL","professor_override":"HOLD","broker_sell_submitted":false}',
    'professor_telegram_instruction',
    1,
    16,
    'PROF_HOLD_OVERRIDE_INTC_16_YYYYMMDD'
);
```

7. No cash ledger write.
8. No broker action.
9. No stop/target/risk/strategy change.

DB_write_required_to_correct_state: YES.

approval_required_before_write: YES.

## Code Patch Scope

code_patch_scope:

1. `/Users/yasser/scripts/atlas_db.py`
   - Add `manual_trade_overrides` schema helper.
   - Add:
     - `has_active_manual_hold_override(trade_id=None, ticker=None)`
     - `get_active_manual_hold_overrides()`
     - `create_manual_hold_override(...)`
     - `deactivate_manual_hold_override(...)`
   - Update pending broker confirmation helper so pending requires `BROKER_SELL_SUBMITTED` and excludes active override positions.
   - Keep DB path production-safe; do not hardcode staging DB.

2. `/Users/yasser/scripts/atlas_portfolio.py`
   - In exit/stop logic, check active Professor hold override before closing/selling.
   - Stop breached + active override returns HOLD/ALERT flags:
     - `manual_override=True`
     - `stop_breached=True`
     - `system_wanted='SELL'`
     - `risk='HIGH'`
     - `broker_sell_submitted=False`
   - Do not call `close_trade()` in the override branch.
   - Do not suppress the risk warning.

3. `/Users/yasser/scripts/atlas_intraday.py`
   - Carry override flags from exit evaluation/DB lookup into holding rows.
   - Exclude active override tickers from SELL NOW.
   - Ensure active override tickers remain in HOLDING.
   - Exclude active override tickers from pending broker confirmation unless broker sell submitted exists.

4. `/Users/yasser/scripts/atlas_report_blocks.py`
   - Render holding block line:
     - `MANUAL OVERRIDE — STOP BREACHED — HIGH RISK`
     - `System wanted: SELL`
     - `Professor override: HOLD`
     - `Broker sell placed: NO`
     - `Broker confirmation pending: NO`

5. `/Users/yasser/scripts/atlas_report_authority.py`
   - No material staged patch was needed; still include in compile/deploy safety set because report authority may import DB/pending helper behavior.

6. `/Users/yasser/scripts/atlas_eod_positions.py`
   - No material staged patch was needed; include in compile/deploy safety set. Patch only if EOD has a separate holdings renderer not covered by shared blocks.

## Report Behavior After Fix

report_behavior_after_fix:

For INTC or any future Prof-approved manual hold override:

```text
HOLDING — MANUAL OVERRIDE
INTC
Live price: <provider price>
Entry: 129.78
Stop: 113.02 breached
Target: 162.25
System wanted: SELL
Professor override: HOLD
Risk: HIGH
Broker sell placed: NO unless actual broker sell submission exists
Broker confirmation pending: NO unless actual broker sell submission exists
```

Expected state rules:

```text
STOP HIT = risk event
SELL NOW = actionable engine state
BROKER CONFIRMATION PENDING = actual broker sell submitted, no fill/cash confirmation yet
PROFESSOR HOLD OVERRIDE = suppress SELL NOW, preserve visible risk warning, keep position in HOLDING
```

## Idle-Window Deployment Plan

1. Wait for a quiet market/report window.
2. Confirm no active Atlas report/engine process:

```bash
ps -axo pid,ppid,stat,etime,command | egrep 'atlas_(intraday|portfolio|daily|manage|macro|eod|pre_market|post_market)|pre_market_report|post_market_report' | grep -v egrep
```

3. Confirm no DB lock:

```bash
lsof /Users/yasser/scripts/atlas.db
```

4. If DB is open by an active Atlas cycle, defer deployment.
5. Disable/kick only if separately approved. Plan does not require disabling launchd if deployed during a guaranteed idle window, but safer deployment should pause the intraday launchd job temporarily only with approval.

## Backup Plan

Before production deployment:

```bash
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p /Users/yasser/scripts/backups_prof_override_$TS
cp /Users/yasser/scripts/atlas.db /Users/yasser/scripts/atlas.db.bak_prof_override_deploy_$TS
cp /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/backups_prof_override_$TS/atlas_db.py
cp /Users/yasser/scripts/atlas_portfolio.py /Users/yasser/scripts/backups_prof_override_$TS/atlas_portfolio.py
cp /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/backups_prof_override_$TS/atlas_intraday.py
cp /Users/yasser/scripts/atlas_report_blocks.py /Users/yasser/scripts/backups_prof_override_$TS/atlas_report_blocks.py
cp /Users/yasser/scripts/atlas_report_authority.py /Users/yasser/scripts/backups_prof_override_$TS/atlas_report_authority.py
cp /Users/yasser/scripts/atlas_eod_positions.py /Users/yasser/scripts/backups_prof_override_$TS/atlas_eod_positions.py
```

Record SHA256 of every backup and every post-patch file.

## Compile / Import Plan

After code patch, before any production DB correction:

```bash
python3 -m py_compile \
  /Users/yasser/scripts/atlas_db.py \
  /Users/yasser/scripts/atlas_portfolio.py \
  /Users/yasser/scripts/atlas_intraday.py \
  /Users/yasser/scripts/atlas_report_blocks.py \
  /Users/yasser/scripts/atlas_report_authority.py \
  /Users/yasser/scripts/atlas_eod_positions.py
```

Import smoke with production imports only, no live trading:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, '/Users/yasser/scripts')
import atlas_db, atlas_portfolio, atlas_intraday, atlas_report_blocks, atlas_report_authority, atlas_eod_positions
print('IMPORT_OK')
PY
```

Expected:

```text
IMPORT_OK
```

## Copied-DB Smoke Test Plan Before Production DB Write

smoke_test_plan:

1. Copy production DB after code patch but before production DB correction:

```bash
cp /Users/yasser/scripts/atlas.db /tmp/prof_override_preprod_smoke.db
```

2. Run smoke using copied DB only:

```bash
ATLAS_DB=/tmp/prof_override_preprod_smoke.db python3 /tmp/prof_override_stage/smoke_manual_override.py
```

If no reusable smoke script exists, run a short copied-DB Python fixture that verifies:

- stop breached + no override -> SELL NOW
- stop breached + override active -> HOLDING MANUAL OVERRIDE, no SELL NOW
- override active survives two cycles
- broker sell submitted + no fill -> broker confirmation pending
- broker fill + cash credit -> CLOSED confirmed, no pending
- override inactive + stop breached -> SELL NOW

3. Confirm copied DB only changed:

```bash
sqlite3 /tmp/prof_override_preprod_smoke.db "SELECT name FROM sqlite_master WHERE type='table' AND name='manual_trade_overrides';"
sqlite3 /Users/yasser/scripts/atlas.db "SELECT name FROM sqlite_master WHERE type='table' AND name='manual_trade_overrides';"
```

Expected before production DB migration:

```text
copied DB: manual_trade_overrides
production DB: <empty>
```

4. Only after smoke PASS and Prof approval, proceed with production DB migration/correction.

## Post-Deploy Read-Only Live Verification Plan

After approved deployment and approved DB correction:

1. Verify INTC status OPEN:

```sql
SELECT id,ticker,status,quantity,entry_price,stop_loss,target_price,risk_pct,exit_price,exit_at,realized_pnl,realized_pnl_pct,broker_ref
FROM trades
WHERE id=16;
```

Expected:

```text
status=OPEN
exit_price=NULL
exit_at=NULL
realized_pnl=NULL
realized_pnl_pct=NULL
```

2. Verify active override exists:

```sql
SELECT id,trade_id,ticker,override_type,status,created_at,created_by,deactivated_at
FROM manual_trade_overrides
WHERE trade_id=16 AND ticker='INTC'
ORDER BY id DESC LIMIT 5;
```

Expected:

```text
override_type=PROFESSOR_HOLD_OVERRIDE
status=ACTIVE
deactivated_at=NULL
```

3. Verify SELL NOW suppresses INTC in dry-run/read-only report generation.
4. Verify HOLDING shows INTC manual override / stop breached / high risk.
5. Verify broker pending excludes INTC unless `BROKER_SELL_SUBMITTED` exists and no fill/cash credit exists.
6. Verify cash unchanged:
   - latest `cash_ledger.balance_after` equals pre-correction value.
   - no new INTC cash credit row.
7. Verify no broker action occurred.
8. Verify no stops/targets/risk/strategy changed.

## Rollback Plan

rollback_plan:

1. Stop/avoid active report cycle during rollback window.
2. Restore files from timestamped backup:

```bash
cp /Users/yasser/scripts/backups_prof_override_$TS/atlas_db.py /Users/yasser/scripts/atlas_db.py
cp /Users/yasser/scripts/backups_prof_override_$TS/atlas_portfolio.py /Users/yasser/scripts/atlas_portfolio.py
cp /Users/yasser/scripts/backups_prof_override_$TS/atlas_intraday.py /Users/yasser/scripts/atlas_intraday.py
cp /Users/yasser/scripts/backups_prof_override_$TS/atlas_report_blocks.py /Users/yasser/scripts/atlas_report_blocks.py
cp /Users/yasser/scripts/backups_prof_override_$TS/atlas_report_authority.py /Users/yasser/scripts/atlas_report_authority.py
cp /Users/yasser/scripts/backups_prof_override_$TS/atlas_eod_positions.py /Users/yasser/scripts/atlas_eod_positions.py
```

3. Restore DB from backup if DB migration/correction was applied:

```bash
cp /Users/yasser/scripts/atlas.db.bak_prof_override_deploy_$TS /Users/yasser/scripts/atlas.db
```

4. Clear Python cache:

```bash
find /Users/yasser/scripts -type d -name '__pycache__' -prune -exec rm -rf {} +
```

5. Compile restored files:

```bash
python3 -m py_compile \
  /Users/yasser/scripts/atlas_db.py \
  /Users/yasser/scripts/atlas_portfolio.py \
  /Users/yasser/scripts/atlas_intraday.py \
  /Users/yasser/scripts/atlas_report_blocks.py \
  /Users/yasser/scripts/atlas_report_authority.py \
  /Users/yasser/scripts/atlas_eod_positions.py
```

6. Run DB checks:

```bash
sqlite3 /Users/yasser/scripts/atlas.db 'PRAGMA integrity_check;'
```

7. Verify restored SHAs match backup SHAs.
8. Verify latest report dry-run starts without import/schema errors.

## Risks

risks:

- Schema migration risk: rebuilding `portfolio_event_journal` CHECK constraint must preserve every row, FK, index, and trigger.
- Lifecycle authority risk: exit logic touches stop/sell behavior, so smoke tests must prove no override -> normal SELL remains intact.
- Broker-pending semantics risk: if production lacks reliable broker sell-submitted events, pending broker confirmation must not be inferred from `trades.status='CLOSED'` alone.
- Timing risk: deployment during an active intraday/pre-market/post-market cycle can race with DB/report writes.
- INTC correction risk: if broker reality is not manually confirmed open immediately before correction, reopening could misrepresent a real broker close.
- Report consistency risk: intraday and EOD may have separate render paths; both must be verified after deploy.

## Required Return Fields

```yaml
PROFESSOR_OVERRIDE_DEPLOY_PLAN_STATUS: READ_ONLY_DEPLOYMENT_PLAN_COMPLETE
target_files:
  - /Users/yasser/scripts/atlas_db.py
  - /Users/yasser/scripts/atlas_portfolio.py
  - /Users/yasser/scripts/atlas_intraday.py
  - /Users/yasser/scripts/atlas_report_blocks.py
  - /Users/yasser/scripts/atlas_report_authority.py
  - /Users/yasser/scripts/atlas_eod_positions.py
production_baseline_shas:
  atlas_db.py: dee59dea71a427871ef61a74c735641b9bb297df4f2292868c1598f0b986ba7b
  atlas_portfolio.py: 9779397a9fba9e66683699e9b8b508f9c08fa1cf6b70b183efe75e097705897d
  atlas_intraday.py: a3dde41d6de982624424c953dd5eabf1cc433e6ce3396f00c40f59e4e53414d5
  atlas_report_blocks.py: fa0289e8db99ff2cafb8097951570b6b884110ad06aac64c26496338501b6714
  atlas_report_authority.py: cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b
  atlas_eod_positions.py: 12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1
staged_shas:
  atlas_db.py: cd7825fd319239ae36982b1cfdd7a5e8a0684252a4ba008e72a28be442873b11
  atlas_portfolio.py: e31f4b56d7dbec2dfe4d5f91e707abf5934233b34c3bf058ce9c12a9f82ff37c
  atlas_intraday.py: c1e9087083630a0bac198dc9aeff6939373977c38c01047139c2c93728259600
  atlas_report_blocks.py: b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a
  atlas_report_authority.py: cdcd5b33c7e94b25c10fb08f0b3d27d97c9292491a360b7f7e0609fdda4aef3b
  atlas_eod_positions.py: 12507ce29a2b541636827bef526996c347dd06d5cb93d6c70ee2dd5178eaa8a1
DB_migration_plan: create manual_trade_overrides; rebuild portfolio_event_journal CHECK only after backup/integrity checks; verify FK/integrity before commit
event_journal_constraint_plan: safely widen CHECK for BROKER_SELL_SUBMITTED, PROFESSOR_HOLD_OVERRIDE_ACTIVE, PROFESSOR_HOLD_OVERRIDE_DEACTIVATED; fallback is override-table-only plus separate broker lifecycle storage
INTC_DB_correction_plan: backup DB; if broker still open, set trades.id=16 OPEN, clear provisional exit/realized fields, preserve qty/entry/stop/target/risk/broker_ref, insert active manual override, no cash ledger entry
smoke_test_plan: copied-DB only tests for no override SELL, active override HOLDING/no SELL, two-cycle survival, submitted pending, filled closed, inactive override SELL
rollback_plan: restore backed-up files and DB, clear pycache, compile, integrity check, verify SHAs/report dry-run
risks: schema rebuild, lifecycle authority, broker-pending semantics, timing, broker reality confirmation, report consistency
approval_required: YES
attached_markdown_filename: /Users/yasser/scripts/professor_override_deploy_plan_20260708.md
production changes: NONE
```

production changes: NONE
