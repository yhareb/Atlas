#!/bin/sh
set -eu
STAGE=/Users/yasser/scripts/perme_context_v1_2
export PYTHONDONTWRITEBYTECODE=1
export ATLAS_DISABLE_TELEGRAM=1
# Existing production sender remains the only send boundary; this wrapper never sends.
exec /Users/yasser/.hermes/hermes-agent/venv/bin/python "$STAGE/perme_v1/perme_context_v1_cli.py" "$@"
