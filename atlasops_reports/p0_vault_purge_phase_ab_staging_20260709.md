# P0 Vault Purge Phase A/B — Staging Package

Generated: 2026-07-09

## Status

`STAGING_STATUS = PASS`

`approval_required = YES`

No production files were modified. No production DB writes were made. No Telegram sends, broker actions, Fat Engine scoring changes, Quiver changes, or FDA changes were performed.

## Staging root

```text
/tmp/p0_vault_purge_phase_ab/
```

## Staged files

| file | staged path | staged SHA256 |
|---|---|---|
| `atlas_db.py` | `/tmp/p0_vault_purge_phase_ab/src/atlas_db.py` | `bdbd00e99f1cbd56a6d583735f0a488e9fffc2775489ae32b575f1211d4182b0` |
| `atlas_manage.py` | `/tmp/p0_vault_purge_phase_ab/src/atlas_manage.py` | `840e9a9084267764c8f6380693d79b57b74dd20f81dc6f47fd3d42e412fbf558` |
| `atlas_intraday.py` | `/tmp/p0_vault_purge_phase_ab/src/atlas_intraday.py` | `06f8d0666c0e71523b6741c6a62ffbcf2d9aebc56f1ad8b5dc36c906516c5a41` |
| `tests/test_scan_timing.py` | `/tmp/p0_vault_purge_phase_ab/src/tests/test_scan_timing.py` | `3983e40cec23da42dcc5843029a9b118ae0145ddda5c35cd9208b18b3cfa8b02` |

## Phase A package — NOT executed

Staged disable/archive script:

```text
/tmp/p0_vault_purge_phase_ab/phase_a/phase_a_disable_vaultsync_NOT_EXECUTED.sh
```

Planned behavior after approval:

1. Abort if `vault_sync.py` is running.
2. Backup `/Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist` into a timestamped archive dir.
3. `launchctl bootout gui/$(id -u) /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist`
4. Move the plist to archive with `.disabled` suffix.
5. Verify launchd label no longer loads.
6. Verify `vault_sync.py` process remains absent.
7. Print rollback bootstrap command.

Current read-only Phase A baseline from verification:

| check | result |
|---|---|
| `com.atlas.vaultsync` loaded | YES |
| launchd state | not running at probe time |
| runs | 3136 |
| last exit code | 0 |
| `vault_sync.py` process | absent |
| Vault logs | still present; stop-advancing check is post-disable only |

Rollback command included in staged Phase A script:

```bash
cp <archive>/com.atlas.vaultsync.plist.bak /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist && \
launchctl bootstrap gui/$(id -u) /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist
```

## Phase B staged code changes

### `atlas_db.py`

Diff: `/tmp/p0_vault_purge_phase_ab/output/atlas_db.py.diff`

Summary:

- Removed `vault_client` import block.
- Removed `_safe_push()` helper.
- Removed Vault push after `log_signal()`.
- Removed Vault push after `open_trade()`.
- Removed Vault push after `confirm_trade_fill()`.
- Removed Vault push after `close_trade()`.
- Removed Vault push after `close_trade_broker_confirmed()`.
- Removed Vault push after `update_trade_stop()`.
- Removed Vault push after `set_manual_stop_lock()`.
- Removed Vault push after `update_handoff()`.
- Removed Vault-only wording/comments from active runtime file.

Diff stats: `+2 / -44`.

### `atlas_manage.py`

Diff: `/tmp/p0_vault_purge_phase_ab/output/atlas_manage.py.diff`

Summary:

- Removed docstring statement that DB ledger pushes to Vault.
- Changed dry-run line from “skipping handoff persistence and vault sync” to “skipping handoff persistence”.
- Removed Vault mention from handoff persistence comment.

Diff stats: `+3 / -3`.

### `atlas_intraday.py`

Diff: `/tmp/p0_vault_purge_phase_ab/output/atlas_intraday.py.diff`

Summary:

- Changed ACTION summary print from “See Vault.” to “Review report.”

Diff stats: `+1 / -1`.

### `tests/test_scan_timing.py`

Diff: `/tmp/p0_vault_purge_phase_ab/output/tests_test_scan_timing.py.diff`

Summary:

- Removed obsolete `atlas_db._vault = None` test hook.

Diff stats: `+0 / -1`.

## Verification outputs

Full verification JSON:

```text
/tmp/p0_vault_purge_phase_ab/output/verification.json
```

Key outputs:

| verification | result |
|---|---|
| `py_compile` staged files | PASS |
| static scan staged active runtime files for Vault refs | PASS — `0` hits |
| staged `atlas_intraday.py` contains `See Vault` | NO |
| staged `atlas_intraday.py` contains replacement `Review report.` | YES |
| staged `atlas_manage.py` contains `vault sync` wording | NO |
| copied-DB dry-run probe status | PASS |
| copied-DB dry-run emitted `vault_client` / `vault_sync` lines | `0` |
| copied DB counts unchanged | YES |
| production DB SHA unchanged | YES |
| production DB counts unchanged | YES |

Compile command:

```bash
python3 -m py_compile \
  /tmp/p0_vault_purge_phase_ab/src/atlas_db.py \
  /tmp/p0_vault_purge_phase_ab/src/atlas_manage.py \
  /tmp/p0_vault_purge_phase_ab/src/atlas_intraday.py \
  /tmp/p0_vault_purge_phase_ab/src/tests/test_scan_timing.py
```

Compile exit: `0`.

Static scan result:

```json
{"static_vault_ref_count": 0, "hits": []}
```

Copied-DB dry-run probe:

- Copied DB: `/tmp/p0_vault_purge_phase_ab/db/atlas_validation.db`
- Staged imports verified:
  - `atlas_db_file = /tmp/p0_vault_purge_phase_ab/src/atlas_db.py`
  - `atlas_manage_file = /tmp/p0_vault_purge_phase_ab/src/atlas_manage.py`
- Probe mode: dry-run, exits-only, no Telegram, no broker, no live writes.
- Result: `DO NOTHING`.
- Vault lines: `[]`.

Production DB proof:

| field | before | after |
|---|---|---|
| SHA256 | `fe22931f405dc67e3997d089d0fefb8b74975e73ceb13d9f0568e91d70af702b` | `fe22931f405dc67e3997d089d0fefb8b74975e73ceb13d9f0568e91d70af702b` |
| `signals` | 31845 | 31845 |
| `trades` | 90 | 90 |
| `pending_pullbacks` | 53 | 53 |
| `handoff` | 15 | 15 |
| `cash_ledger` | 25 | 25 |
| `portfolio_event_journal` | 90 | 90 |
| `report_snapshots` | 63 | 63 |

## Deployment plan — NOT executed

Staged deployment script:

```text
/tmp/p0_vault_purge_phase_ab/phase_b_deploy_NOT_EXECUTED.sh
```

Required order after explicit approval:

1. Execute Phase A scheduler disable/archive first.
2. Verify `com.atlas.vaultsync` unloaded and `vault_sync.py` absent.
3. Run live-process safety gates before code copy:
   - `pgrep -f 'atlas_intraday\.py'`
   - `launchctl print gui/$(id -u)/com.atlas.intraday`
4. Backup production files to timestamped archive.
5. Copy staged files to production.
6. Clear targeted pycache for deployed files only:
   - `/Users/yasser/scripts/__pycache__/atlas_db.cpython-*.pyc`
   - `/Users/yasser/scripts/__pycache__/atlas_manage.cpython-*.pyc`
   - `/Users/yasser/scripts/__pycache__/atlas_intraday.cpython-*.pyc`
   - matching macOS system Python cache paths under `/Users/yasser/Library/Caches/com.apple.python/Users/yasser/scripts/`
7. Compile production files.
8. SHA-verify deployed files match staged SHAs.
9. Copied-DB smoke test against production imports.
10. Confirm no Vault lines in smoke output.
11. Confirm production DB SHA/counts unchanged.

## Rollback plan

If Phase A only was applied:

```bash
cp <archive>/com.atlas.vaultsync.plist.bak /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist && \
launchctl bootstrap gui/$(id -u) /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist
```

If Phase B code was deployed:

1. Copy backups from the timestamped archive back to:
   - `/Users/yasser/scripts/atlas_db.py`
   - `/Users/yasser/scripts/atlas_manage.py`
   - `/Users/yasser/scripts/atlas_intraday.py`
   - `/Users/yasser/scripts/tests/test_scan_timing.py`
2. Clear targeted pycache for restored files.
3. Compile restored files.
4. Verify restored production SHAs match backup SHAs.
5. Bootstrap Vault plist only if Professor explicitly wants Vault restored.

## Not included by design

- Did not archive `vault_client.py` or `vault_sync.py` yet.
- Did not remove env vars.
- Did not remove Git-tracked Vault scripts.
- Did not clean logs.
- Did not clean optional `/tmp/vault_sync_cursor.txt`.
- Did not touch historical docs/skills/reports.

## Final staging verdict

`ready_for_production_review = YES`

`approval_required = YES`
