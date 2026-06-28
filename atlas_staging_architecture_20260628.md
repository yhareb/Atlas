# Atlas Staging Environment Architecture — Current State

Generated for Prof. by AtlasOps on 2026-06-28.

This file answers the five requested staging architecture questions using actual commands, paths, and observed outputs. Secrets are intentionally not included.

---

# 1. Staging DB path and sync model

## Staging DB path

```text
/tmp/atlas_staging.db
```

## Production DB path

```text
/Users/yasser/scripts/atlas.db
```

## Sync model

The staging DB is **not continuously synced**. It is refreshed by copying production DB into `/tmp/atlas_staging.db` before Gate 2 / Gate 3 / staging validation runs.

Exact sync command:

```bash
cp /Users/yasser/scripts/atlas.db /tmp/atlas_staging.db
```

Safer timestamped form with backup:

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
cp -p /Users/yasser/scripts/atlas.db /Users/yasser/scripts/atlas.db.bak_staging_${STAMP}
cp -p /Users/yasser/scripts/atlas.db /tmp/atlas_staging.db
```

## Current observed DB state

Command run:

```bash
python3 - <<'PY'
import os, sqlite3, time
paths=['/Users/yasser/scripts/atlas.db','/tmp/atlas_staging.db']
for p in paths:
    print('###',p)
    st=os.stat(p)
    print('size=',st.st_size)
    print('mtime_local=',time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(st.st_mtime)))
    con=sqlite3.connect(p); cur=con.cursor()
    for table in ['signals','trades','positions','pending_pullbacks','handoff','cash_ledger','ema_retry_candidates']:
        try:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            print(f'{table}=', cur.fetchone()[0])
        except Exception as e:
            print(f'{table}=ERR:{e}')
    con.close()
PY
```

Observed output:

```text
### /Users/yasser/scripts/atlas.db
size= 2904064
mtime_local= 2026-06-27 00:15:24 +04
signals= 6377
trades= 10
positions= 0
pending_pullbacks= 26
handoff= 7
cash_ledger= 7
ema_retry_candidates= 0
### /tmp/atlas_staging.db
size= 2904064
mtime_local= 2026-06-27 17:01:55 +04
signals= 6377
trades= 10
positions= 0
pending_pullbacks= 26
handoff= 7
cash_ledger= 7
ema_retry_candidates= 0
```

Current counts match production, but the sync is still manual. Any Gate 3 cycle may write to the staging DB, so refresh `/tmp/atlas_staging.db` from production before each clean validation set.

---

# 2. How staging cycles work

## Staging profile

Hermes profile:

```text
atlas-staging
```

Profile path:

```text
/Users/yasser/.hermes/profiles/atlas-staging
```

Observed profile command:

```bash
hermes profile show atlas-staging
```

Observed output:

```text
Profile: atlas-staging
Path:    /Users/yasser/.hermes/profiles/atlas-staging
Model:   gpt-5.5 (openai-api)
Gateway: stopped
Skills:  73
.env:    exists
SOUL.md: exists
```

Profile descriptor:

```text
/Users/yasser/.hermes/profiles/atlas-staging/profile.yaml
```

Contents:

```yaml
description: Atlas staging profile for dry-run scan/report verification against /tmp/atlas_staging.db
  with Docker terminal backend when Docker is available.
description_auto: false
```

## Staging cycle runner

Runner path:

```text
/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py
```

Runner help command:

```bash
python3 /Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py --help
```

Observed output:

```text
usage: run_atlas_manage_staging.py [-h] [--max-seconds MAX_SECONDS]
                                   [--cycles CYCLES]

Atlas staging dry-run scan runner

optional arguments:
  -h, --help            show this help message and exit
  --max-seconds MAX_SECONDS
  --cycles CYCLES
```

## Standard Gate 3 staging cycle command

```bash
cp /Users/yasser/scripts/atlas.db /tmp/atlas_staging.db
ATLAS_SCRIPTS_DIR=/tmp/atlas_phaseN_staging_scripts \
ATLAS_STAGING_DB=/tmp/atlas_staging.db \
ATLAS_DB=/tmp/atlas_staging.db \
/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py --cycles 3 --max-seconds 480
```

If no staged script workspace is being tested, use production scripts read-only by default:

```bash
cp /Users/yasser/scripts/atlas.db /tmp/atlas_staging.db
ATLAS_STAGING_DB=/tmp/atlas_staging.db \
ATLAS_DB=/tmp/atlas_staging.db \
/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py --cycles 3 --max-seconds 480
```

## What the runner does internally

Path:

```text
/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py
```

Relevant code:

```python
SCRIPTS_DIR = Path(os.environ.get("ATLAS_SCRIPTS_DIR", "/Users/yasser/scripts"))
STAGING_DB = Path(os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB") or "/tmp/atlas_staging.db")
```

```python
sys.path.insert(0, str(OVERRIDES))
sys.path.insert(1, str(SCRIPTS_DIR))
os.environ["ATLAS_DISABLE_TELEGRAM"] = "1"
os.environ["ATLAS_MOCK_TELEGRAM"] = "1"
os.environ["ATLAS_STAGING_DB"] = str(STAGING_DB)
os.environ["ATLAS_DB"] = str(STAGING_DB)
```

```python
import atlas_db
import atlas_account as acct

atlas_db.DB_PATH = str(STAGING_DB)
atlas_db._vault = None
atlas_db._atlas_log_db_event = None
acct.DB_PATH = str(STAGING_DB)

import atlas_manage

atlas_manage._atlas_log_signal = None
```

```python
scan_args = SimpleNamespace(tickers=[], file=None, live=False, exits_only=False, json=False)
summary = atlas_manage.run(scan_args)
```

## Output destination

The runner writes to stdout/stderr. There is no fixed output directory unless the operator redirects it.

Operational pattern:

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
ATLAS_SCRIPTS_DIR=/tmp/atlas_phaseN_staging_scripts \
ATLAS_STAGING_DB=/tmp/atlas_staging.db \
ATLAS_DB=/tmp/atlas_staging.db \
/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py --cycles 3 --max-seconds 480 \
  > /tmp/atlas_phaseN_gate3_staging_cycles_${STAMP}.log \
  2> /tmp/atlas_phaseN_gate3_staging_cycles_${STAMP}.err
```

Recent observed output files:

```text
/tmp/atlas_phase7_gate3_staging_cycles_20260627_020306.log
/tmp/atlas_phase6_gate3_staging_cycles_20260627_013814.log
/tmp/atlas_phase11_gate3_cycle1.out
/tmp/atlas_phase11_gate3_cycle2.out
/tmp/atlas_phase11_gate3_cycle3.out
```

Recent successful full `atlas_manage` Gate 3 result from `/tmp/atlas_phase7_gate3_staging_cycles_20260627_020306.log`:

```text
STAGING_ALL_RESULTS_JSON=[{"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6465, "trades": 10}, "counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "cycle": 1, "elapsed_seconds": 369.048, "result": "DO NOTHING", "scanned_count": 75, "under_limit": true}, {"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6553, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6465, "trades": 10}, "cycle": 2, "elapsed_seconds": 182.691, "result": "DO NOTHING", "scanned_count": 73, "under_limit": true}, {"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6641, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6553, "trades": 10}, "cycle": 3, "elapsed_seconds": 214.537, "result": "DO NOTHING", "scanned_count": 73, "under_limit": true}]
[STAGING] PASS
```

Important: Gate 3 changes the staging DB counts. In the observed result, `signals` increased from `6377` to `6641` and `pending_pullbacks` increased from `26` to `28` inside `/tmp/atlas_staging.db`. That is expected staging mutation, not production mutation, but it means `/tmp/atlas_staging.db` must be refreshed before a new clean gate set.

---

# 3. Docker / Colima / Gate 3 status

## Docker / Colima installed?

Observed command:

```bash
command -v docker || true
command -v colima || true
docker --version 2>&1 || true
colima version 2>&1 || true
colima status 2>&1 || true
docker info --format '{{json .ServerVersion}} {{json .OperatingSystem}}' 2>&1 || true
```

Observed output:

```text
## Docker/Colima commands

## Docker version
/bin/bash: line 17: docker: command not found

## Colima version/status
/bin/bash: line 19: colima: command not found
/bin/bash: line 20: colima: command not found

## Docker info server availability
/bin/bash: line 22: docker: command not found
```

## Docker config exists but is not operational on this host

Dockerfile exists:

```text
/Users/yasser/.hermes/profiles/atlas-staging/Dockerfile
```

Docker Compose file exists:

```text
/Users/yasser/.hermes/profiles/atlas-staging/docker-compose.yml
```

Dockerfile contents:

```dockerfile
# Atlas staging container manifest
# Uses production scripts read-only and writes only to /tmp/atlas_staging.db.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ATLAS_DB=/tmp/atlas_staging.db \
    ATLAS_STAGING_DB=/tmp/atlas_staging.db \
    ATLAS_DISABLE_TELEGRAM=1 \
    ATLAS_MOCK_TELEGRAM=1 \
    PYTHONPATH=/atlas-staging/overrides:/Users/yasser/scripts

WORKDIR /workspace

# Runtime mounts expected:
#   /Users/yasser/scripts:/Users/yasser/scripts:ro
#   /tmp:/tmp
#   /Users/yasser/.hermes/profiles/atlas-staging:/atlas-staging:ro
CMD ["python3", "/atlas-staging/bin/run_atlas_manage_staging.py", "--cycles", "1"]
```

Compose contents:

```yaml
services:
  atlas-staging:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      ATLAS_DB: /tmp/atlas_staging.db
      ATLAS_STAGING_DB: /tmp/atlas_staging.db
      ATLAS_DISABLE_TELEGRAM: "1"
      ATLAS_MOCK_TELEGRAM: "1"
      PYTHONPATH: /atlas-staging/overrides:/Users/yasser/scripts
    volumes:
      - /Users/yasser/scripts:/Users/yasser/scripts:ro
      - /tmp:/tmp
      - /Users/yasser/.hermes/profiles/atlas-staging:/atlas-staging:ro
    working_dir: /workspace
    command: ["python3", "/atlas-staging/bin/run_atlas_manage_staging.py", "--cycles", "1"]
```

## Gate 3 status

Current status:

```text
Docker/Colima Gate 3: NOT operational on this host because docker and colima commands are missing.
Local/manual Gate 3 runner: operational; it runs against /tmp/atlas_staging.db with Telegram/Vault disabled.
```

So the true current staging mode is:

```text
manual/local Python staging cycles against /tmp/atlas_staging.db
```

not:

```text
Docker/Colima-isolated Gate 3
```

---

# 4. Exact sequence of commands for a full staging run from backup to final sign-off

Use this exact structure. Replace `phaseN` and `changed_file.py` with the specific work order path(s). Do not apply production until Prof. signs off.

## 4.1 Set variables

```bash
PHASE=phaseN
STAMP=$(date +%Y%m%d_%H%M%S)
PROD=/Users/yasser/scripts
STAGE=/tmp/atlas_${PHASE}_staging_scripts
STAGING_DB=/tmp/atlas_staging.db
PROFILE=/Users/yasser/.hermes/profiles/atlas-staging
RUNNER=/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py
GATE2=/Users/yasser/scripts/tests/test_scan_timing.py
```

## 4.2 Backup production DB and create clean staging DB

```bash
cp -p "$PROD/atlas.db" "$PROD/atlas.db.bak_${PHASE}_${STAMP}"
cp -p "$PROD/atlas.db" "$STAGING_DB"
```

## 4.3 Create staging script workspace

```bash
rm -rf "$STAGE"
mkdir -p "$STAGE"
rsync -a --delete "$PROD"/ "$STAGE"/
```

If `rsync` is unavailable, use:

```bash
rm -rf "$STAGE"
cp -R "$PROD" "$STAGE"
```

## 4.4 Apply/edit only the staged files

Example:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('/tmp/atlas_phaseN_staging_scripts/changed_file.py')
s = p.read_text()
s = s.replace('OLD_TEXT', 'NEW_TEXT')
p.write_text(s)
PY
```

No production file is edited in this step.

## 4.5 Gate 1 compile changed staged files

Example:

```bash
python3 -m py_compile "$STAGE/changed_file.py"
```

For multiple staged Python files:

```bash
python3 -m py_compile \
  "$STAGE/atlas_intraday.py" \
  "$STAGE/atlas_manage.py" \
  "$STAGE/atlas_preopen_check.py"
```

## 4.6 Gate 1 deterministic dry-run / behavior check

For a direct script dry-run:

```bash
ATLAS_DB="$STAGING_DB" \
ATLAS_STAGING_DB="$STAGING_DB" \
ATLAS_DISABLE_TELEGRAM=1 \
ATLAS_MOCK_TELEGRAM=1 \
PYTHONPATH="$STAGE:$PROFILE/overrides" \
python3 "$STAGE/changed_file.py" --dry-run \
  > /tmp/atlas_${PHASE}_gate1_${STAMP}.out \
  2> /tmp/atlas_${PHASE}_gate1_${STAMP}.err
```

For module/report function probes, use the same env variables and write output to `/tmp/atlas_${PHASE}_gate1_${STAMP}.out`.

## 4.7 Gate 2 timing harness

Command:

```bash
cp -p "$PROD/atlas.db" "$STAGING_DB"
"$GATE2" --db "$STAGING_DB" --max-seconds 480 \
  > /tmp/atlas_${PHASE}_gate2_${STAMP}.out \
  2> /tmp/atlas_${PHASE}_gate2_${STAMP}.err
```

Known current harness path:

```text
/Users/yasser/scripts/tests/test_scan_timing.py
```

The harness copies the provided DB to an isolated temp DB and mocks Telegram. Relevant code:

```python
parser.add_argument("--db", default="", help="Optional staging DB to copy from; defaults to production DB")
source_db = Path(args.db).expanduser() if args.db else PROD_DB
shutil.copy2(source_db, temp_db)
```

```python
os.environ["ATLAS_DISABLE_TELEGRAM"] = "1"
os.environ["ATLAS_MOCK_TELEGRAM"] = "1"
```

```python
atlas_db.DB_PATH = str(temp_db)
atlas_db._vault = None
atlas_db._atlas_log_db_event = None
acct.DB_PATH = str(temp_db)
```

Pass proof pattern from recent run:

```text
GATE2_RESULT_JSON={"candidate_count": 97, "elapsed_seconds": 367.205, "isolated_db": "/var/folders/nz/48nykj7s0tl__8dfhq6dd0vm0000gn/T/atlas_scan_timing_6hc1isg_/atlas_timing.db", "max_seconds": 480.0, "result": "DO NOTHING", "scanned_count": 75, "source_counts_after": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "source_counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "source_counts_unchanged": true, "temp_counts_after": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "temp_counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "under_limit": true}
[GATE2] elapsed_seconds=367.205
[GATE2] PASS
```

## 4.8 Gate 3 local/manual staging cycles

Command:

```bash
cp -p "$PROD/atlas.db" "$STAGING_DB"
ATLAS_SCRIPTS_DIR="$STAGE" \
ATLAS_STAGING_DB="$STAGING_DB" \
ATLAS_DB="$STAGING_DB" \
"$RUNNER" --cycles 3 --max-seconds 480 \
  > /tmp/atlas_${PHASE}_gate3_${STAMP}.out \
  2> /tmp/atlas_${PHASE}_gate3_${STAMP}.err
```

Pass proof pattern:

```bash
grep 'STAGING_ALL_RESULTS_JSON\|\[STAGING\] PASS' /tmp/atlas_${PHASE}_gate3_${STAMP}.out
```

Recent observed pass:

```text
STAGING_ALL_RESULTS_JSON=[{"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6465, "trades": 10}, "counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "cycle": 1, "elapsed_seconds": 369.048, "result": "DO NOTHING", "scanned_count": 75, "under_limit": true}, {"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6553, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6465, "trades": 10}, "cycle": 2, "elapsed_seconds": 182.691, "result": "DO NOTHING", "scanned_count": 73, "under_limit": true}, {"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6641, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6553, "trades": 10}, "cycle": 3, "elapsed_seconds": 214.537, "result": "DO NOTHING", "scanned_count": 73, "under_limit": true}]
[STAGING] PASS
```

## 4.9 Verify production DB unchanged during staging

Command:

```bash
python3 - <<'PY'
import sqlite3, json
for db in ['/Users/yasser/scripts/atlas.db', '/tmp/atlas_staging.db']:
    con=sqlite3.connect(db); cur=con.cursor()
    out={}
    for table in ['signals','trades','positions','pending_pullbacks','handoff','cash_ledger','ema_retry_candidates']:
        try:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            out[table]=cur.fetchone()[0]
        except Exception as e:
            out[table]=f'ERR:{e}'
    con.close()
    print(db, json.dumps(out, sort_keys=True))
PY
```

Expected interpretation:

```text
/Users/yasser/scripts/atlas.db must stay unchanged during staging.
/tmp/atlas_staging.db may change during Gate 3.
```

## 4.10 Prepare sign-off packet for Prof.

Use one Markdown file if evidence is long:

```bash
SIGNOFF=/Users/yasser/scripts/atlas_${PHASE}_staging_signoff_${STAMP}.md
cat > "$SIGNOFF" <<'MD'
# Atlas staging sign-off packet

## Files staged

## Backups

## Gate 1 compile

## Gate 1 dry-run output

## Gate 2 timing result

## Gate 3 staging cycles

## Production DB unchanged proof

## Known limitations / blockers

## Request
Awaiting Prof. approval before production apply.
MD
```

## 4.11 Production apply only after Prof. approval

Backup exact production files:

```bash
cp -p "$PROD/changed_file.py" "$PROD/changed_file.py.bak_${PHASE}_${STAMP}"
```

Copy staged file into production:

```bash
cp -p "$STAGE/changed_file.py" "$PROD/changed_file.py"
```

Compile production file:

```bash
python3 -m py_compile "$PROD/changed_file.py"
```

Optional launchd verification if a plist/schedule was changed:

```bash
plutil -lint /Users/yasser/Library/LaunchAgents/com.atlas.somejob.plist
launchctl print gui/$(id -u)/com.atlas.somejob
```

Final production proof command depends on the changed component. For reports, use dry-run/no-send where supported; for live send, only after explicit approval.

---

# 5. Known gaps / limitations in current staging setup

## Gap 1 — Docker/Colima are not installed

Actual observed output:

```text
/bin/bash: line 17: docker: command not found
/bin/bash: line 19: colima: command not found
/bin/bash: line 20: colima: command not found
/bin/bash: line 22: docker: command not found
```

Impact:

```text
/Users/yasser/.hermes/profiles/atlas-staging/config.yaml says terminal.backend=docker, and Dockerfile/docker-compose exist, but Docker/Colima cannot actually run on this host right now.
```

Current workaround:

```bash
ATLAS_STAGING_DB=/tmp/atlas_staging.db \
ATLAS_DB=/tmp/atlas_staging.db \
/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py --cycles 3 --max-seconds 480
```

## Gap 2 — `/tmp/atlas_staging.db` is manually refreshed, not continuously synced

Required command before each clean validation:

```bash
cp -p /Users/yasser/scripts/atlas.db /tmp/atlas_staging.db
```

## Gap 3 — Gate 3 mutates the staging DB

Observed Gate 3 result:

```text
cycle 1: signals 6377 -> 6465, pending_pullbacks 26 -> 28
cycle 2: signals 6465 -> 6553, pending_pullbacks 28 -> 28
cycle 3: signals 6553 -> 6641, pending_pullbacks 28 -> 28
```

Impact:

```text
Gate 3 is isolated from production, but not no-write against /tmp/atlas_staging.db. Refresh the staging DB after Gate 3 if another clean test is needed.
```

## Gap 4 — Gate 2 is no-write, Gate 3 is not no-write

Gate 2 suppresses mutations in the timing harness:

```python
for name in (
    "log_signal", "update_handoff", "open_trade", "close_trade",
    "upsert_pending_pullback", "expire_pending_pullback", "mark_pending_pullback_filled",
    "delete_pending_pullback", "confirm_trade_fill", "void_pending_fill_trade",
):
    if hasattr(atlas_db, name):
        setattr(atlas_db, name, _noop)
```

Gate 3 does not suppress DB writes the same way; it only points writes to `/tmp/atlas_staging.db` and disables Vault/Telegram/audit pushes.

## Gap 5 — Docker profile config and host reality are inconsistent

Config excerpt from `/Users/yasser/.hermes/profiles/atlas-staging/config.yaml`:

```yaml
terminal:
  backend: docker
  cwd: /workspace
  docker_image: python:3.11-slim
  docker_env:
    ATLAS_DB: /tmp/atlas_staging.db
    ATLAS_STAGING_DB: /tmp/atlas_staging.db
    ATLAS_DISABLE_TELEGRAM: '1'
    ATLAS_MOCK_TELEGRAM: '1'
    PYTHONPATH: /atlas-staging/overrides:/Users/yasser/scripts
  docker_volumes:
  - /Users/yasser/scripts:/Users/yasser/scripts:ro
  - /tmp:/tmp
  - /Users/yasser/.hermes/profiles/atlas-staging:/atlas-staging:ro
```

Host reality:

```text
docker: command not found
colima: command not found
```

## Gap 6 — No live Telegram in staging by design

Staging disables Telegram:

```bash
ATLAS_DISABLE_TELEGRAM=1
ATLAS_MOCK_TELEGRAM=1
```

The staging profile `.env` sets:

```text
ATLAS_DISABLE_TELEGRAM=1
ATLAS_MOCK_TELEGRAM=1
TELEGRAM_CHAT_ID=mock-staging-no-send
```

Impact:

```text
Staging can prove rendered text and mock-send paths, but not actual Telegram delivery. Live Telegram verification is production-only unless Prof. explicitly asks for a live staged send.
```

## Gap 7 — External API/network behavior is still live unless separately mocked

The runner disables Telegram, Vault, and Atlas audit pushes, but it still imports production scripts and may use live market-data APIs if the code path calls them. That is why Gate 2/Gate 3 timings vary and why outputs can depend on provider latency.

## Gap 8 — Staged scripts are copied from production; protected alpha files remain protected unless Prof. authorizes alpha work

Default staging workflow copies `/Users/yasser/scripts` into `/tmp/atlas_phaseN_staging_scripts`, but AtlasOps still must not inspect/alter protected alpha files unless a Prof override applies.

Protected files:

```text
/Users/yasser/scripts/atlas_engine.py
/Users/yasser/scripts/atlas_portfolio.py
```

Current standing override allows Prof-issued Atlas trading-system work orders, but source exposure should remain non-disclosing.

---

# Current one-line operational truth

```text
Atlas staging currently uses /tmp/atlas_staging.db plus the atlas-staging profile runner at /Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py. Docker/Colima are not installed, so Gate 3 is local/manual, not containerized. The staging DB is refreshed by manual cp from /Users/yasser/scripts/atlas.db and is mutated by Gate 3 cycles, while production DB remains untouched if commands are followed.
```
