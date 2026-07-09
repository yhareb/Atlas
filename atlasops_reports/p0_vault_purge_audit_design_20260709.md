# P0 Vault Purge Audit / Design

Generated: 2026-07-09

## Scope held

- Read-only audit/design only.
- No production patch.
- No DB write.
- No Telegram send.
- No broker action.
- No Fat Engine scoring change.
- No Quiver/FDA changes.
- No secret/env values printed in this report.

## Executive verdict

`vault_status = ACTIVE_RUNTIME_PRESENT`

Vault is still participating in Atlas runtime in two ways:

1. **Scheduled bulk sync**: `com.atlas.vaultsync` launchd job is loaded and configured to run `vault_sync.py` every 300 seconds.
2. **Real-time DB write hook**: `atlas_db.py` imports `vault_client.py` and pushes after DB writes through `_safe_push()`.

`approval_required = YES`

No purge/disable action has been executed.

## Secret/env handling

Only env var names/status were checked. Values are intentionally omitted.

| name | current shell | config presence |
|---|---|---|
| `VAULT_URL` | MISSING | present in `com.atlas.vaultsync.plist`; present in Atlas profile env |
| `VAULT_SYNC_TOKEN` | MISSING | present in `com.atlas.vaultsync.plist`; present in Atlas profile env |
| `VAULT_PUSH` | not set in shell | optional code flag in `vault_client.py` |
| `VAULT_PUSH_LOG` | not set in shell | optional code flag in `vault_client.py` |
| `VAULT_SYNC_CURSOR` | not set in shell | optional `vault_sync.py` cursor env |
| `VAULT_SYNC_LOG` | not set in shell | optional `vault_sync.py` log env |

## Active scheduler/process state

| item | result |
|---|---|
| `com.atlas.vaultsync` plist | `/Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist` |
| launchd loaded | YES |
| launchd state | not running at probe time |
| launchd runs | 3135 |
| last exit code | 0 |
| direct `vault_sync.py` process | none found |
| direct `vault_client.py` process | none found |
| Hermes cron jobs | none |
| DB schema/table refs | none found |

Process note: a generic `pgrep vault` matches macOS `filevaultd`; it is unrelated to Atlas Vault.

## Files/jobs affected

| path/job | classification | role |
|---|---|---|
| `/Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist` | active runtime scheduler | direct 5-minute Vault sync job |
| `/Users/yasser/scripts/vault_sync.py` | active runtime / DB read sync path | reads `atlas.db` read-only and posts `signals`, `positions`, `handoff`, `trades` to Vault `/api/sync` |
| `/Users/yasser/scripts/vault_client.py` | active runtime / DB write-sync path | async real-time push client used by `atlas_db.py` |
| `/Users/yasser/scripts/atlas_db.py` | active runtime / DB write hook | imports `vault_client`; calls `_safe_push()` after signal/trade/handoff writes |
| `/Users/yasser/scripts/atlas_manage.py` | passive/report text + indirect hook | dry-run text says “vault sync”; live handoff persistence triggers `atlas_db.update_handoff()` hook |
| `/Users/yasser/scripts/atlas_intraday.py` | report text | prints “See Vault” on ACTION summary |
| `/Users/yasser/scripts/tests/test_scan_timing.py` | test guard | disables `atlas_db._vault = None` in copied-DB timing test |
| `/Users/yasser/scripts/vault_sync.log` | logs only | historical bulk-sync output |
| `/Users/yasser/scripts/vault_sync.err.log` | logs only | historical bulk-sync errors/timeouts |
| `/Users/yasser/scripts/atlas_intraday.log` | runtime evidence | recent `vault_client: pushed signal/handoff` lines |
| `/Users/yasser/scripts/atlas_intraday.err.log` | runtime evidence | recent `vault_client: pushed handoff/trades` lines |
| `/Users/yasser/scripts/atlas_daily.err.log` | runtime evidence | recent `vault_client: pushed signal` lines |
| `/Users/yasser/scripts/archive/vault_*` | dead code/backups | historical backups only |
| `~/.hermes/profiles/atlasops/skills/**` | documentation only | skill/reference docs mention old Vault workflows |
| `/Users/yasser/atlas_inbox/reports/**` | documentation only | historical reports mention Vault |
| Git tracked files | backup/source-control scope | `vault_client.py`, `vault_sync.py` are tracked |
| `hermes_gdrive_backup.sh` | no direct Vault ref | current backup list does not explicitly include `scripts/vault_*`; `.hermes` docs may still contain Vault references |

## Active Vault call graph

```text
launchd com.atlas.vaultsync
  -> /usr/bin/python3 /Users/yasser/scripts/vault_sync.py
     -> opens /Users/yasser/scripts/atlas.db read-only
     -> build_signals()
     -> build_positions()
     -> build_handoff()
     -> build_trades()
     -> post_payload(... /api/sync)
```

```text
atlas_db.py import time
  -> import vault_client as _vault
  -> _safe_push(fn_name, ...)

atlas_db.log_signal()
  -> INSERT signals
  -> _safe_push("push_signal", row)
  -> vault_client.push_signal()
  -> async queue worker
  -> POST /api/sync

atlas_db.open_trade()
  -> INSERT trades
  -> _safe_push("push_trades", rows)

atlas_db.confirm_trade_fill()
  -> UPDATE trades
  -> _safe_push("push_trades", rows)

atlas_db.close_trade()
  -> UPDATE trades
  -> _safe_push("push_trades", rows)

atlas_db.close_trade_broker_confirmed()
  -> UPDATE trades
  -> _safe_push("push_trades", rows)

atlas_db.update_trade_stop()
  -> UPDATE trades
  -> _safe_push("push_trades", rows)

atlas_db.set_manual_stop_lock()
  -> UPDATE trades
  -> _safe_push("push_trades", rows)

atlas_db.update_handoff()
  -> UPSERT handoff
  -> _safe_push("push_handoff", date, data)
```

## Log evidence

| log | finding |
|---|---|
| `vault_sync.err.log` | historical Vault timeout errors present |
| `atlas_intraday.log` | recent `vault_client: pushed signal` / `pushed handoff` entries present |
| `atlas_intraday.err.log` | recent `vault_client: pushed handoff/trades` entries present |
| `atlas_daily.err.log` | recent `vault_client: pushed signal` entries present |
| `vault_sync.log` | no literal `vault` lines because success format is generic OK/read/synced |

## Classification summary

| class | refs |
|---|---|
| active runtime | `com.atlas.vaultsync`, `vault_sync.py`, `vault_client.py`, `atlas_db.py` hooks |
| passive config | `VAULT_URL`, `VAULT_SYNC_TOKEN`, optional `VAULT_PUSH*` / `VAULT_SYNC*` env names |
| DB write/sync path | `atlas_db.py` `_safe_push()` after `signals`, `trades`, `handoff` writes; `vault_sync.py` reads DB and posts payload |
| dead code | archive backups under `/Users/yasser/scripts/archive/vault_*` |
| documentation only | skills/references/historical reports/RAG docs mentioning Vault |
| report text | `atlas_intraday.py` “See Vault”; `atlas_manage.py` dry-run “vault sync” wording |
| backup/source-control | Git tracks `vault_client.py` and `vault_sync.py`; current GDrive backup script does not explicitly list them |

## Safe purge plan

### Phase A — disable Vault runtime/schedulers

Objective: stop scheduled external sync before code purge.

Planned actions after approval:

```bash
# Verify no currently running vault sync
pgrep -fl 'vault_sync\.py' || true
launchctl print gui/$(id -u)/com.atlas.vaultsync

# Backup plist before disable/archive
mkdir -p /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS
cp /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist \
  /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/com.atlas.vaultsync.plist.bak

# Disable loaded scheduler
launchctl bootout gui/$(id -u) /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist

# Archive plist so it cannot reload on login
mv /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist \
  /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/com.atlas.vaultsync.plist.disabled
```

Verification:

- `launchctl print gui/$(id -u)/com.atlas.vaultsync` exits non-zero.
- `pgrep -fl 'vault_sync\.py'` empty.
- `vault_sync.log` and `vault_sync.err.log` stop advancing.

### Phase B — disable Vault sync calls in code

Objective: remove runtime participation from Atlas DB write paths.

Staging patch targets:

| file | intended change |
|---|---|
| `/tmp/p0_vault_purge/atlas_db.py` | remove `vault_client` import block, remove `_safe_push()` implementation/calls, replace Vault comments with neutral DB-audit comments only |
| `/tmp/p0_vault_purge/atlas_manage.py` | remove dry-run wording “vault sync” |
| `/tmp/p0_vault_purge/atlas_intraday.py` | remove “See Vault” ACTION summary text |
| `/tmp/p0_vault_purge/tests/test_scan_timing.py` | remove obsolete `atlas_db._vault = None` test hook if production code no longer has `_vault` |

Staging verification:

1. Copy current production files to `/tmp/p0_vault_purge/src/`.
2. Patch only the staging copies.
3. `python3 -m py_compile` all staged touched files.
4. Static scan: no `vault`, `vault_client`, `vault_sync`, `VAULT_URL`, or `VAULT_SYNC_TOKEN` in active staged runtime files except historical comments if deliberately retained — target should be zero active refs.
5. Run copied-DB dry-run with Vault disabled and side effects isolated:
   - production DB copied to `/tmp/p0_vault_purge/atlas_validation.db`
   - `ATLAS_DB=/tmp/p0_vault_purge/atlas_validation.db`
   - no Telegram send
   - no broker action
   - no production DB SHA change
6. Assert no `vault_client:` lines are emitted during staged dry-run.
7. Assert copied DB counts unchanged unless the tested command is expected to write to the copied DB; production counts/SHA must remain unchanged.

### Phase C — remove/ignore Vault env requirements

Objective: remove Vault env dependency without exposing values.

Planned after Phase A/B approval:

- Remove `VAULT_URL` and `VAULT_SYNC_TOKEN` entries from Atlas profile env/config only after explicit env-change approval.
- Do not print old values.
- Verify only by key-name presence: `PRESENT -> ABSENT`.
- Ensure no active launchd plist still carries Vault env names.

### Phase D — archive Vault scripts

Objective: keep rollback artifact but remove active runtime discoverability.

Planned after code no longer imports them:

```bash
mkdir -p /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS
cp /Users/yasser/scripts/vault_client.py /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/vault_client.py.bak
cp /Users/yasser/scripts/vault_sync.py   /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/vault_sync.py.bak
mv /Users/yasser/scripts/vault_client.py /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/vault_client.py.disabled
mv /Users/yasser/scripts/vault_sync.py   /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/vault_sync.py.disabled
```

Source-control follow-up:

- Remove from Git tracking in a code-only cleanup commit after deployment approval:
  - `vault_client.py`
  - `vault_sync.py`
- Do not delete local archive backups.

### Phase E — optional DB/log cleanup only after separate approval

Current audit found no Vault-specific DB tables/schema.

Optional later cleanup candidates:

| artifact | type | recommendation |
|---|---|---|
| `/tmp/vault_sync_cursor.txt` | runtime cursor file | delete only after scheduler/code disabled and approved |
| `vault_sync.log` | log | archive/compress, do not delete first pass |
| `vault_sync.err.log` | log | archive/compress, do not delete first pass |
| historical docs/skills | documentation | leave until separate docs cleanup; not runtime |
| external Vault dashboard data | outside Atlas DB | not touched from AtlasOps without separate explicit instruction |

## Risks

| risk | mitigation |
|---|---|
| breaking Atlas DB writes by touching `atlas_db.py` | stage in `/tmp`, compile, copied-DB dry-run, production SHA/count proof |
| hidden imports still referencing `vault_client.py` | static scan active runtime files before archiving scripts |
| launchd reload on login if plist remains | Phase A archives plist after `bootout` |
| accidental Telegram send in verification | no-send mocks / dry-run only / do not touch Telegram config |
| live intraday process racing deploy | use live-process gate before any production `cp` involving `atlas_db.py`/`atlas_intraday.py` |
| log/doc references causing false failure | classify docs/logs separately from active runtime; do not require historical archives to be scrubbed in first pass |
| rollback needed | backups of plist and scripts under timestamped archive; restore + `launchctl bootstrap` |

## Deployment/rollback outline

Deployment requires a separate approved execution round.

Rollback if Phase A only:

```bash
cp /Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/com.atlas.vaultsync.plist.bak \
   /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist
launchctl bootstrap gui/$(id -u) /Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist
```

Rollback if Phase B/D deployed:

- Restore backed-up production files from `/Users/yasser/scripts/archive/p0_vault_purge_YYYYMMDD_HHMMSS/`.
- Clear targeted pycache for each restored Python file.
- `python3 -m py_compile` restored files.
- Verify SHAs match backup baseline.
- Re-bootstrap launchd only if Professor explicitly wants Vault restored.

## Verification checklist for approved staging/deploy

- [ ] `approval_required = YES` acknowledged before production changes.
- [ ] Phase A: `com.atlas.vaultsync` unloaded and plist archived.
- [ ] Phase B staging: compile PASS.
- [ ] Phase B staging: active runtime static scan shows no Vault calls.
- [ ] Copied-DB dry-run emits no `vault_client:` lines.
- [ ] Production DB SHA/counts unchanged by staging verification.
- [ ] Reports render without “See Vault”.
- [ ] `vault_sync.log` / `vault_sync.err.log` stop advancing after scheduler disable.
- [ ] Rollback path verified by backup file existence and SHA.

## Final recommendation

Proceed with **Phase A + Phase B staging** first, not direct production deletion.

The safest next work order is:

`Stage P0 Vault purge Phase A/B package in /tmp only; do not deploy.`

`approval_required = YES`
