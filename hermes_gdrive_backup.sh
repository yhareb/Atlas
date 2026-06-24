#!/bin/bash
set -uo pipefail

HERMES_DIR="/Users/yasser/.hermes"
BACKUP_ROOT="/Users/yasser/backups/hermes_gdrive"
LOG_FILE="/Users/yasser/scripts/hermes_gdrive_backup.log"
RCLONE="/opt/homebrew/bin/rclone"
REMOTE_DIR="gdrive:AtlasBackups/hermes_daily"
TS="$(/bin/date '+%Y-%m-%d_%H%M')"
ARCHIVE_NAME="hermes_backup_${TS}.tar.gz"
ARCHIVE_PATH="${BACKUP_ROOT}/${ARCHIVE_NAME}"
TMP_LOG="${BACKUP_ROOT}/last_run.tmp.log"

mkdir -p "$BACKUP_ROOT"
touch "$LOG_FILE"
: > "$TMP_LOG"

log() {
  local msg="$1"
  printf '%s %s\n' "$(/bin/date '+%Y-%m-%d %H:%M:%S %z')" "$msg" | tee -a "$LOG_FILE" "$TMP_LOG"
}

send_telegram() {
  local message="$1"
  TELEGRAM_MESSAGE="$message" /usr/bin/python3 - <<'PY'
import json, os, urllib.parse, urllib.request
from pathlib import Path

# Load Telegram config without printing secrets. Prefer atlas TELEGRAM_CHAT_ID when available.
env_paths = [
    Path('/Users/yasser/.hermes/profiles/atlas/.env'),
    Path('/Users/yasser/.hermes/profiles/atlasops/.env'),
    Path('/Users/yasser/.hermes/.env'),
]
for path in env_paths:
    if not path.exists():
        continue
    try:
        for line in path.read_text(errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception:
        pass

token = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN')
chat = os.environ.get('TELEGRAM_CHAT_ID') or os.environ.get('TELEGRAM_ALLOWED_USERS') or os.environ.get('TELEGRAM_HOME_CHANNEL')
message = os.environ.get('TELEGRAM_MESSAGE', '')
if not token or not chat:
    print('telegram skipped: TELEGRAM_BOT_TOKEN or chat id unset')
    raise SystemExit(0)
url = f'https://api.telegram.org/bot{token}/sendMessage'
payload = urllib.parse.urlencode({'chat_id': chat, 'text': message}).encode()
try:
    with urllib.request.urlopen(url, data=payload, timeout=25) as response:
        body = response.read(5000)
    data = json.loads(body.decode('utf-8', errors='replace'))
    if not data.get('ok'):
        print('telegram rejected message')
        raise SystemExit(1)
    print('telegram sent')
except Exception as exc:
    print(f'telegram failed: {type(exc).__name__}: {exc}')
    raise SystemExit(1)
PY
}

fail() {
  local exit_code="$1"
  local step="$2"
  log "FAILED step=${step} exit_code=${exit_code}"
  local tail_text
  tail_text="$(/usr/bin/tail -20 "$TMP_LOG" 2>/dev/null)"
  send_telegram "❌ Hermes GDrive backup FAILED
Step: ${step}
Exit code: ${exit_code}
Archive: ${ARCHIVE_NAME}
Log: ${LOG_FILE}

Last log lines:
${tail_text}" || true
  exit "$exit_code"
}

run_step() {
  local step="$1"
  shift
  log "START ${step}"
  "$@" >> "$LOG_FILE" 2>> "$TMP_LOG"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    fail "$rc" "$step"
  fi
  log "OK ${step}"
}

log "=== Hermes GDrive backup started ==="
log "Archive=${ARCHIVE_PATH}"
log "Remote=${REMOTE_DIR}/${ARCHIVE_NAME}"

if [ ! -d "$HERMES_DIR" ]; then
  fail 2 "check Hermes directory"
fi
if [ ! -x "$RCLONE" ]; then
  fail 3 "check rclone"
fi

run_step "create Google Drive folder" "$RCLONE" mkdir "$REMOTE_DIR"
run_step "create tar.gz archive" /usr/bin/tar -czf "$ARCHIVE_PATH" -C /Users/yasser .hermes

if [ ! -s "$ARCHIVE_PATH" ]; then
  fail 4 "verify local archive non-empty"
fi

LOCAL_SIZE="$(/usr/bin/stat -f '%z' "$ARCHIVE_PATH")"
log "Local archive size=${LOCAL_SIZE} bytes"

run_step "upload archive to Google Drive" "$RCLONE" copy "$ARCHIVE_PATH" "$REMOTE_DIR" --retries 3 --low-level-retries 10

REMOTE_SIZE="$($RCLONE lsjson "${REMOTE_DIR}/${ARCHIVE_NAME}" 2>>"$TMP_LOG" | /usr/bin/python3 -c 'import json,sys; data=json.load(sys.stdin); print(data[0].get("Size", "")) if data else print("")')"
if [ -z "$REMOTE_SIZE" ]; then
  fail 5 "verify remote archive exists"
fi
log "Remote archive size=${REMOTE_SIZE} bytes"

if [ "$LOCAL_SIZE" != "$REMOTE_SIZE" ]; then
  fail 6 "verify remote size matches local size"
fi

log "SUCCESS archive uploaded and size verified"
send_telegram "✅ Hermes GDrive backup completed
Archive: ${ARCHIVE_NAME}
Size: ${LOCAL_SIZE} bytes
Remote: ${REMOTE_DIR}/${ARCHIVE_NAME}
Log: ${LOG_FILE}" || true
log "=== Hermes GDrive backup finished ==="
