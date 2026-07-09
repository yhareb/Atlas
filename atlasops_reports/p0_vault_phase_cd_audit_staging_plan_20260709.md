# P0 Vault Purge Phase C/D Audit + Staging Plan

Generated: 2026-07-09

## Status

`PHASE_CD_STATUS = AUDIT_AND_PLAN_ONLY`

`approval_required = YES`

No cleanup was executed. No production patch, no DB write, no Telegram send, no broker action, no Fat Engine scoring change, no Quiver/FDA changes.

## Phase A/B context verified

| check | result |
|---|---|
| `com.atlas.vaultsync` launchd label | unloaded (`launchctl print` exit `113`) |
| `vault_sync.py` process | absent |
| `vault_client.py` process | absent |
| active top-level non-Vault Python files with Vault refs | `0` |
| Hermes atlasops cron Vault jobs | `0` |

Audit artifact:

```text
/tmp/p0_vault_phase_cd_audit.json
```

## Remaining Vault references grouped

### Active runtime

| reference | classification | action |
|---|---|---|
| `/Users/yasser/scripts/vault_client.py` | inactive residue; no longer imported by active Atlas runtime | Phase D archive |
| `/Users/yasser/scripts/vault_sync.py` | inactive residue; launchd unloaded; no active process | Phase D archive |

External active import scan result:

```json
{"active_top_level_non_vault_py_vault_hits": 0, "hits": []}
```

### Passive config

| path | env names present | action |
|---|---|---|
| `/Users/yasser/.hermes/profiles/atlas/.env` | `VAULT_URL`, `VAULT_SYNC_TOKEN` | Phase C remove these two lines by key name only |
| `/Users/yasser/.hermes/profiles/atlasops/.env` | none | no action |
| `/Users/yasser/scripts/.env` | file absent | no action |
| archived disabled plist | contains old Vault env names | leave as rollback artifact unless Prof separately approves credential scrub/destruction |

No env values were printed or copied.

### Logs/runtime residue

| path | exists | action |
|---|---:|---|
| `/Users/yasser/scripts/vault_sync.log` | YES | Phase D archive, do not delete first |
| `/Users/yasser/scripts/vault_sync.err.log` | YES | Phase D archive, do not delete first |
| `/tmp/vault_sync_cursor.txt` | YES | optional Phase D archive/remove from `/tmp` after approval |

Current log sizes at audit time:

| log | size |
|---|---:|
| `vault_sync.log` | 1,242,419 bytes |
| `vault_sync.err.log` | 1,507,426 bytes |

### Archive/staging/docs references

| group | classification | action |
|---|---|---|
| `/Users/yasser/scripts/archive/**` | historical archive | leave alone |
| `/Users/yasser/scripts/backups_prof_override_*` | old backup directories | leave alone unless separate cleanup approved |
| `/Users/yasser/scripts/staging/**` | stale staging residue | not runtime; leave unless separate staging cleanup approved |
| `/Users/yasser/.hermes/profiles/atlasops/skills/**` | documentation/skills | leave alone per instruction |
| `/Users/yasser/scripts/atlasops_reports/**` | historical reports | leave alone per instruction |

## Exact files to archive in Phase D

Required:

```text
/Users/yasser/scripts/vault_client.py
/Users/yasser/scripts/vault_sync.py
/Users/yasser/scripts/vault_sync.log
/Users/yasser/scripts/vault_sync.err.log
```

Optional if present:

```text
/tmp/vault_sync_cursor.txt
```

Target archive directory pattern:

```text
/Users/yasser/scripts/archive/<UTC>_p0_vault_purge_phase_cd/
```

## Exact env/config names to remove in Phase C

From `/Users/yasser/.hermes/profiles/atlas/.env` only:

```text
VAULT_URL
VAULT_SYNC_TOKEN
```

Do **not** remove or edit Telegram-related env/config. Do **not** print env values. Do **not** touch AtlasOps profile env because no Vault keys were found there.

## Staging commands — NOT executed

### Preflight verification

```bash
# Verify scheduler/runtime remains off
launchctl print gui/$(id -u)/com.atlas.vaultsync && exit 1 || true
pgrep -fl 'vault_sync\.py|vault_client\.py' && exit 1 || true

# Verify active code no longer imports/references Vault outside the two residue scripts
python3 - <<'PY'
from pathlib import Path
import re, sys
S=Path('/Users/yasser/scripts')
exclude={'vault_client.py','vault_sync.py','atlas_engine.py','atlas_portfolio.py'}
pat=re.compile(r'vault|VAULT_URL|VAULT_SYNC_TOKEN|VAULT_PUSH|VAULT_SYNC_|vault_client|vault_sync', re.I)
hits=[]
for p in S.glob('*.py'):
    if p.name in exclude:
        continue
    for i,line in enumerate(p.read_text(errors='replace').splitlines(),1):
        if pat.search(line):
            hits.append((str(p),i,line.strip()))
print(hits)
raise SystemExit(1 if hits else 0)
PY
```

### Phase C env-name removal plan

Use a non-disclosing key-only edit. This removes only lines whose key starts with the two Vault names; it does not print values.

```bash
TAG="$(date -u '+%Y%m%dT%H%M%SZ')_p0_vault_purge_phase_cd"
ARCHIVE="/Users/yasser/scripts/archive/${TAG}"
mkdir -p "$ARCHIVE"
ENV_FILE="/Users/yasser/.hermes/profiles/atlas/.env"

cp "$ENV_FILE" "$ARCHIVE/atlas_profile.env.pre_vault_purge.bak"
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/yasser/.hermes/profiles/atlas/.env')
remove={'VAULT_URL','VAULT_SYNC_TOKEN'}
lines=p.read_text(errors='ignore').splitlines()
kept=[]; removed=[]
for line in lines:
    key=line.split('=',1)[0].strip() if '=' in line else None
    if key in remove:
        removed.append(key)
        continue
    kept.append(line)
p.write_text('\n'.join(kept)+'\n')
print({'removed_keys': sorted(set(removed))})
PY

# Verify by key name only
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/yasser/.hermes/profiles/atlas/.env')
keys=[]
for line in p.read_text(errors='ignore').splitlines():
    if '=' in line and line.split('=',1)[0].strip().startswith('VAULT_'):
        keys.append(line.split('=',1)[0].strip())
print({'remaining_vault_keys': sorted(set(keys))})
raise SystemExit(1 if keys else 0)
PY
```

### Phase D archive plan

```bash
TAG="$(date -u '+%Y%m%dT%H%M%SZ')_p0_vault_purge_phase_cd"
ARCHIVE="/Users/yasser/scripts/archive/${TAG}"
mkdir -p "$ARCHIVE"

# Abort if anything is active
if launchctl print gui/$(id -u)/com.atlas.vaultsync >/dev/null 2>&1; then
  echo "ABORT: com.atlas.vaultsync still loaded"; exit 1
fi
if pgrep -fl 'vault_sync\.py|vault_client\.py' >/dev/null; then
  echo "ABORT: Vault process still running"; pgrep -fl 'vault_sync\.py|vault_client\.py'; exit 1
fi

# Archive files; do not delete first
for f in \
  /Users/yasser/scripts/vault_client.py \
  /Users/yasser/scripts/vault_sync.py \
  /Users/yasser/scripts/vault_sync.log \
  /Users/yasser/scripts/vault_sync.err.log
 do
  if [ -e "$f" ]; then
    mv "$f" "$ARCHIVE/$(basename "$f").disabled"
  fi
 done

if [ -e /tmp/vault_sync_cursor.txt ]; then
  mv /tmp/vault_sync_cursor.txt "$ARCHIVE/vault_sync_cursor.txt.disabled"
fi
```

### Git/source-control plan if approved

`git ls-files` currently tracks:

```text
vault_client.py
vault_sync.py
```

After Phase D archive/move, record top-level deletion in Git:

```bash
cd /Users/yasser/scripts
git status --short
git rm vault_client.py vault_sync.py
git status --short
```

Do not add archived `.disabled` files/logs to Git. They should remain local archive artifacts.

## Verification commands after approved cleanup

```bash
# Runtime remains off
launchctl print gui/$(id -u)/com.atlas.vaultsync && exit 1 || true
pgrep -fl 'vault_sync\.py|vault_client\.py' && exit 1 || true

# Top-level residue gone
test ! -e /Users/yasser/scripts/vault_client.py
test ! -e /Users/yasser/scripts/vault_sync.py
test ! -e /Users/yasser/scripts/vault_sync.log
test ! -e /Users/yasser/scripts/vault_sync.err.log

# Optional cursor gone from /tmp if archived
test ! -e /tmp/vault_sync_cursor.txt

# Active code has no Vault refs
python3 - <<'PY'
from pathlib import Path
import re, sys
S=Path('/Users/yasser/scripts')
exclude={'atlas_engine.py','atlas_portfolio.py'}
pat=re.compile(r'vault|VAULT_URL|VAULT_SYNC_TOKEN|VAULT_PUSH|VAULT_SYNC_|vault_client|vault_sync', re.I)
hits=[]
for p in S.glob('*.py'):
    if p.name in exclude:
        continue
    for i,line in enumerate(p.read_text(errors='replace').splitlines(),1):
        if pat.search(line):
            hits.append((str(p),i,line.strip()))
print(hits)
raise SystemExit(1 if hits else 0)
PY

# Env names removed; prints key names only
python3 - <<'PY'
from pathlib import Path
for p in [Path('/Users/yasser/.hermes/profiles/atlas/.env'), Path('/Users/yasser/.hermes/profiles/atlasops/.env')]:
    keys=[]
    if p.exists():
        for line in p.read_text(errors='ignore').splitlines():
            if '=' in line and line.split('=',1)[0].strip().startswith('VAULT_'):
                keys.append(line.split('=',1)[0].strip())
    print(str(p), sorted(set(keys)))
    if keys: raise SystemExit(1)
PY

# Compile key Atlas files still clean
python3 -m py_compile \
  /Users/yasser/scripts/atlas_db.py \
  /Users/yasser/scripts/atlas_manage.py \
  /Users/yasser/scripts/atlas_intraday.py \
  /Users/yasser/scripts/tests/test_scan_timing.py
```

## Rollback commands

If Phase C env cleanup must be reverted:

```bash
cp "$ARCHIVE/atlas_profile.env.pre_vault_purge.bak" /Users/yasser/.hermes/profiles/atlas/.env
```

If Phase D archive must be reverted:

```bash
for f in vault_client.py vault_sync.py vault_sync.log vault_sync.err.log; do
  if [ -e "$ARCHIVE/${f}.disabled" ]; then
    mv "$ARCHIVE/${f}.disabled" "/Users/yasser/scripts/${f}"
  fi
done
if [ -e "$ARCHIVE/vault_sync_cursor.txt.disabled" ]; then
  mv "$ARCHIVE/vault_sync_cursor.txt.disabled" /tmp/vault_sync_cursor.txt
fi
```

If source-control deletion was staged and must be reverted before commit:

```bash
cd /Users/yasser/scripts
git restore --staged vault_client.py vault_sync.py || true
git restore vault_client.py vault_sync.py || true
```

Note: restoring scripts does not re-enable Vault runtime. To restore scheduler too, restore the archived plist from the Phase A/B archive and run `launchctl bootstrap`; that should only happen if Professor explicitly wants Vault back.

## Risks / cautions

| risk | mitigation |
|---|---|
| accidentally touching Telegram config while editing env | key-only script removes only `VAULT_URL` / `VAULT_SYNC_TOKEN`; no env values printed |
| breaking rollback by deleting scripts/logs | use `mv` into timestamped archive, not delete |
| hidden active import | preflight active-code static scan before moving scripts |
| Git tracks removed scripts | planned `git rm vault_client.py vault_sync.py` after archive, with archived files ignored/local |
| archived disabled plist still contains old Vault config | leave as rollback artifact unless Prof separately approves credential scrub |

## Final recommendation

Proceed with Phase C/D only after explicit approval:

1. Remove `VAULT_URL` / `VAULT_SYNC_TOKEN` by key name from Atlas profile env.
2. Archive `vault_client.py`, `vault_sync.py`, `vault_sync.log`, `vault_sync.err.log`, and optional cursor file.
3. Record Git deletion of top-level Vault scripts.
4. Leave historical docs/skills/reports/archives untouched.

`approval_required = YES`
