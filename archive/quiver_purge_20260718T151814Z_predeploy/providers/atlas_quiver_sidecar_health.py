#!/usr/bin/env python3
"""Health wrapper for Atlas Quiver observation-only sidecar."""
from __future__ import annotations
import json, sys
from atlas_quiver_sidecar import ROOT_DEFAULT, ATLAS_DB_DEFAULT, root_paths, health

def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT_DEFAULT
    db = str(root_paths(root)['db'])
    result = health(db, ATLAS_DB_DEFAULT, root)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') == 'PASS' else 1
if __name__ == '__main__':
    raise SystemExit(main())
