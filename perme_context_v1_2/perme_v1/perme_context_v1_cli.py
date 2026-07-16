#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from perme_context_v1.pipeline import run_pipeline

def main()->int:
    ap=argparse.ArgumentParser(description="Staged Perme Context V1; never Telegram, never production writes")
    ap.add_argument("--mode",choices=("mock","live"),required=True); ap.add_argument("--routine",default="auto")
    ap.add_argument("--outbox",type=Path,required=True,help="must be a /tmp path")
    ap.add_argument("--replay",type=Path,help="raw evidence bundle fixture; bypass provider and DB access")
    ns=ap.parse_args(); raw=json.loads(ns.replay.read_text(),parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))) if ns.replay else None
    print(json.dumps(run_pipeline(ns.mode,ns.routine,ns.outbox,raw_bundle=raw),sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
