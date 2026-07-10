# P0 PENG Repair — Production Ledger Correction + Staged Advisory Gate

**STATUS = PASS**  
**Production code touched = NO**  
**deployment_ready = YES**

## Phase A — production ledger correction

### Broker/authority reconfirmation

- Professor's incident evidence states PENG remains held.
- Canonical trade 111 retained broker-backed entry provenance and broker reference.
- No PENG broker-sell cash credit existed.
- No `BROKER_SELL_FILLED` event existed.
- No broker reconciliation/sell evidence existed in Atlas for a sale.
- Therefore the only recorded close was Atlas's unauthorized auto-close; no cash reversal was required.

### Idle gate

The bounded idle watcher did not kill, unload, or alter any process/schedule. It waited until all gates were clear, then rechecked inside the same process immediately before backup and transaction:

- `atlas_intraday.py`: absent
- `atlas_manage.py`: absent
- `market_scout.py`: absent
- `com.atlas.intraday state=running`: false
- `/tmp/atlas_intraday.lock`: absent

### Immediately-before state

- DB: `/Users/yasser/scripts/atlas.db`
- SHA256: `cca3da7efab6913b6ec78f2194a6b816ecad76f370a2c564f3d24732f35f02bb`
- `PRAGMA integrity_check`: `ok`
- Cash: `$25,374.95`
- Trade 111: `PENG`, `CLOSED`, quantity `26.42008`, entry `$75.70`, exit `$75.42`, exit time `2026-07-10 13:40:12`, realized P&L `-$7.28`, stop `$75.71`, target `$100.01`, risk `0.5`, broker reference preserved.

Full table counts before:

```text
account=1
broker_position_display_snapshots=0
broker_reconciliation=0
cash_ledger=25
ema_retry_candidates=0
evidence_attachments=1
handoff=16
invariant_checks=89
ledger_postings=54
manual_trade_overrides=1
pending_pullbacks=54
portfolio_event_journal=90
position_lots=68
report_snapshots=88
signals=33766
trades=98
valuation_marks=74
```

### Backup

- Path: `/Users/yasser/scripts/archive/atlas.db_20260710T142605Z_p0_peng_unauthorized_close_reversal_predeploy.bak.db`
- Backup SHA256: `cca3da7efab6913b6ec78f2194a6b816ecad76f370a2c564f3d24732f35f02bb`
- Backup SHA equals pre-correction production SHA: **YES**
- Backup integrity: `ok`

### Applied correction

One `BEGIN IMMEDIATE` transaction revalidated the exact trade-111 preimage, then:

- set `status='OPEN'`
- cleared `exit_price`, `exit_at`, `exit_fees`, `realized_pnl`, `realized_pnl_pct`
- preserved quantity, entry fields, broker reference, stop, target, risk, manual-stop state, and cached-price fields
- changed no cash row
- appended provenance to notes while preserving the original unauthorized-close facts
- inserted one idempotent `REVERSAL` journal event, `prof_approved=1`, source `prof_authorized_p0_peng_repair`, linked to legacy trade 111

Idempotency key: `prof_authorized_reversal_trade_111_unauthorized_autoclose_20260710`.

### Post-correction verification

- DB SHA256: `02eeac1d95f68005bc679296cfbcc726e8519f44947d8bb7dd5b6e90ba43a6e9`
- Integrity: `ok`
- Trade 111: exactly one `OPEN` PENG row
- CLOSED residue for trade 111: zero
- Quantity: `26.42008`
- Entry: `$75.70`; stop: `$75.71`; target: `$100.01`; broker reference preserved
- Exit/P&L fields: `NULL`
- Cash before/after: `$25,374.95` / `$25,374.95`
- Fabricated `BROKER_SELL_FILLED` events: zero
- Professor-approved `REVERSAL` events: exactly one
- Original unauthorized close evidence preserved in notes and reversal payload: exit time `2026-07-10 13:40:12`, exit price `$75.42`

Full table counts after:

```text
account=1
broker_position_display_snapshots=0
broker_reconciliation=0
cash_ledger=25
ema_retry_candidates=0
evidence_attachments=1
handoff=16
invariant_checks=89
ledger_postings=54
manual_trade_overrides=1
pending_pullbacks=54
portfolio_event_journal=91
position_lots=68
report_snapshots=88
signals=33766
trades=98
valuation_marks=74
```

Only legitimate count delta: `portfolio_event_journal 90 → 91`.

## Phase B — staged code repair only

Workspace: `/tmp/p0_exit_advisory_gate_v1/`  
Copied DB: `/tmp/p0_exit_advisory_gate_v1/db/atlas_staging.db`

Production source and copied-source SHAs matched before editing. Production DB and production code remained untouched throughout staging.

### Staged files and SHAs

- `src/atlas_portfolio.py` — `8fed8d2985bb6ff4ac661dfa75f447f5d30b7325f335dede60232329a90b1444`
- `src/atlas_db.py` — `8ae022d2d0c0b8cbfe0320661cc48529b00aa33ab665a583f2d36bf5dbedf3f1`
- `src/atlas_profit_protection_advisory.py` — `9047413e43e2ce294e4d1b7f9c974df8fe42a20c44d281e1596be197066c967d` (**copied unchanged; not a deployment target**)
- `tests/test_exit_advisory_gate.py` — `71f4ab99b881cb5296beb8c08036332637aba1435eb6be5a2a387c3311a1defc`
- Test results: `/tmp/p0_exit_advisory_gate_v1/output/test_results.json` — `a4822b3466e4d2bf4855d8eea05c6021acd318562ac41f301c7ce84f300ef83c`

`atlas_intraday.py` required no change: it already renders `action=SELL` under SELL NOW. With the staged portfolio gate, the DB remains OPEN, so later cycles retain the position instead of silently losing it.

### Exact root-cause fix

1. `atlas_portfolio.evaluate_exit()` still computes the existing stop/target/time conditions and returns the same `action='SELL'`, reason, and price for report rendering, but no longer calls `atlas_db.close_trade()` merely because the scheduled manager is live.
2. SELL rows are explicitly marked `advisory_only=True` and `broker_confirmation_required=True`.
3. Exit quantity is preserved as exact decimal text (`"26.42008"`), not truncated with `int()`.
4. `atlas_db.close_trade()` now rejects any broker-backed OPEN position and directs it to `close_trade_broker_confirmed()`.
5. The retained legacy FIFO function uses `Decimal(str(...))` quantity arithmetic for non-broker legacy rows, eliminating fractional truncation.
6. `close_trade_broker_confirmed()` uses Decimal-safe exact quantity matching and settlement arithmetic, then closes and posts the matching cash credit through the existing authoritative path.
7. No strategy/scoring/BUY/AVOID/Too Hot/stop/target/routing logic was changed. AST body comparison proved all 61 other `atlas_portfolio.py` functions byte-identical to production.

## Mandatory staged tests

All executed against the isolated copied DB with staged module origin verified:

- `py_compile` all staged/touched Python and test files: **PASS**
- Stop hit: SELL advisory; exact `26.42008`; trade OPEN; cash/stop/target/status unchanged: **PASS**
- Target hit: same: **PASS**
- Time exit: same: **PASS**
- Repeated cycles: identical advisory; zero DB writes/duplicate writes: **PASS**
- Missing broker evidence: generic close rejected; DB byte SHA unchanged: **PASS**
- Confirmed broker sell: closes once, exact fractional quantity, one matching cash credit and `BROKER_SELL_FILLED` event, retry rejected: **PASS**
- Confirmed staged net credit fixture: `$2,013.30`: **PASS**
- Legacy fractional partial-close fixture: `26.42008 - 0.42008 = 26.0`, no truncation: **PASS**
- Profit Protection P0P2a: `advisory_only=True`; copied DB SHA unchanged: **PASS**
- Healthy-mode regression: 61 non-exit portfolio function bodies unchanged; no BUY/AVOID/scorer changes: **PASS**
- Telegram suppression/static proof: no Telegram send or route references in touched staged files: **PASS**
- Copied DB integrity: `ok`: **PASS**
- Production DB SHA during staged tests: `02eeac...a6e9` before and after: **PASS**
- Production source SHAs during staged tests unchanged: **PASS**

Production current source SHAs:

- `atlas_portfolio.py`: `e31f4b56d7dbec2dfe4d5f91e707abf5934233b34c3bf058ce9c12a9f82ff37c`
- `atlas_db.py`: `bdbd00e99f1cbd56a6d583735f0a488e9fffc2775489ae32b575f1211d4182b0`
- `atlas_intraday.py`: `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_profit_protection_advisory.py`: `9047413e43e2ce294e4d1b7f9c974df8fe42a20c44d281e1596be197066c967d`

## Rollback

Phase-A full rollback path:

```bash
# Only during a verified idle window; this restores the entire pre-correction DB.
cp /Users/yasser/scripts/archive/atlas.db_20260710T142605Z_p0_peng_unauthorized_close_reversal_predeploy.bak.db /Users/yasser/scripts/atlas.db
shasum -a 256 /Users/yasser/scripts/atlas.db
sqlite3 -readonly /Users/yasser/scripts/atlas.db 'PRAGMA integrity_check;'
```

Expected restored SHA: `cca3da7efab6913b6ec78f2194a6b816ecad76f370a2c564f3d24732f35f02bb`.

No code rollback is needed now because production code was not touched. If later deployment is approved, create fresh timestamped production backups of both target files immediately before copying, and restore both as one unit on any failed smoke gate.

## Final gate

**deployment_ready = YES**  
Staged deployment targets: `atlas_portfolio.py`, `atlas_db.py` only.  
Production code deployment was not performed and still requires explicit Professor approval.
