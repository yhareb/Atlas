#!/bin/sh
set -eu
umask 077
BASE="/Users/yasser/Library/Application Support/AtlasCorporateActionsShadow"
PY="/Users/yasser/.hermes/hermes-agent/venv/bin/python"
APP="/Users/yasser/scripts/corporate_actions_shadow_observer"
DB="$BASE/shadow.sqlite3"
SESSION=$(/bin/date +%F)
"$PY" -I "$APP/corporate_actions_shadow_observer.py" --shadow-db "$DB" --production-db /Users/yasser/scripts/atlas.db --session-date "$SESSION" --mode scheduled --max-candidates 250 --timeout 4
"$PY" -I "$APP/corporate_actions_shadow_acceptance.py" --db "$DB" --production-db /Users/yasser/scripts/atlas.db --session-date "$SESSION"
