#!/usr/bin/env python3
"""Secret-free append-only LLM invocation observations."""
import datetime as dt, json, os
from pathlib import Path
DEFAULT_LEDGER=Path('/Users/yasser/scripts/config/llm_invocations.jsonl')
def ledger_path(): return Path(os.environ.get('ATLAS_LLM_INVOCATION_LEDGER') or DEFAULT_LEDGER)
def record(boundary,caller,purpose_class):
 p=ledger_path(); p.parent.mkdir(parents=True,exist_ok=True)
 row={'ts':dt.datetime.now(dt.timezone.utc).isoformat(),'boundary':str(boundary),'caller':str(caller),'purpose_class':str(purpose_class),'cycle_id':os.environ.get('ATLAS_CYCLE_ID')}
 flags=os.O_WRONLY|os.O_CREAT|os.O_APPEND
 fd=os.open(p,flags,0o600)
 try:
  os.write(fd,(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode());os.fsync(fd)
 finally:os.close(fd)
 return row
