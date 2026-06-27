#!/bin/bash
set -euo pipefail
source /Users/yasser/.hermes/profiles/atlas/.env 2>/dev/null || true
export ATLAS_MACRO_PREMARKET_LAUNCHD_GATED=1
exec /usr/bin/python3 /Users/yasser/scripts/atlas_macro_premarket.py
