#!/bin/sh
set -eu
export TZ=America/New_York
evidence=''
for f in "/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/snapshots/"snapshot_*.json; do evidence="$f"; done
test -n "$evidence"
exec /usr/bin/python3 /Users/yasser/scripts/atlas_holdings_reunderwrite_runner.py \
  --db /Users/yasser/scripts/atlas.db --evidence "$evidence" \
  --out "/Users/yasser/atlas_inbox/holdings_reunderwrite/latest/holdings_reunderwrite_packet_v2.json" \
  --sidecar "/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/db/holdings_reunderwrite_v2.sqlite" "$@"
