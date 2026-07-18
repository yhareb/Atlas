#!/bin/sh
set -eu
export TZ=America/New_York
: "${ATLAS_MACRO_CONTEXT_V1_PATH:?MISSING_ENV: ATLAS_MACRO_CONTEXT_V1_PATH}"
evidence=''
for f in "/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/snapshots/"snapshot_*.json; do evidence="$f"; done
test -n "$evidence"
exec /usr/bin/python3 /Users/yasser/scripts/atlas_holdings_reunderwrite_runner.py \
  --db /Users/yasser/scripts/atlas.db --evidence "$evidence" \
  --macro-context "$ATLAS_MACRO_CONTEXT_V1_PATH" \
  --out "/Users/yasser/atlas_inbox/holdings_reunderwrite/latest/holdings_reunderwrite_packet_v2.json" \
  --sidecar "/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/db/holdings_reunderwrite_v2.sqlite" "$@"
