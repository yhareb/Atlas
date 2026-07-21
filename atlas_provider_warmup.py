#!/usr/bin/env python3
"""Best-effort, cache-only provider-discovery warm-up for the next Atlas cycle."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sys, tempfile, time
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
def canon(o): return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
def atomic(path,obj):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);raw=canon(obj)+b'\n';fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  try:os.unlink(tmp)
  except FileNotFoundError:pass
 return hashlib.sha256(raw).hexdigest()
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--cache',required=True);ap.add_argument('--receipt',required=True);ap.add_argument('--force',action='store_true');ap.add_argument('--scheduled-window',action='store_true');a=ap.parse_args(argv)
 now=dt.datetime.now(ET)
 if a.scheduled_window and not (now.weekday()<5 and now.hour==9 and 20<=now.minute<25): return 0
 os.environ['ATLAS_PROVIDER_WARMUP']='1';os.environ['ATLAS_DISCOVERY_CACHE_PATH']=a.cache;os.environ['ATLAS_DISCOVERY_CACHE_BYPASS']='1'
 started=time.monotonic();receipt={'schema':'atlas.provider_discovery_warmup.v1','started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'cache_path':a.cache,'best_effort':True}
 try:
  if os.environ.get('ATLAS_WARMUP_FORCE_FAILURE')=='1': raise RuntimeError('FORCED_STAGING_WARMUP_FAILURE')
  cache_path=Path(a.cache)
  if cache_path.is_file() and not a.force:
   cached=json.loads(cache_path.read_text()); generated=dt.datetime.fromisoformat(str(cached.get('generated_at')).replace('Z','+00:00'))
   if cached.get('schema')=='atlas.provider_discovery_cache.v1' and dt.datetime.now(dt.timezone.utc)<=generated+dt.timedelta(seconds=int(cached.get('ttl_seconds') or 0)):
    receipt.update(status='PASS',action='IDEMPOTENT_NO_OP',ticker_count=len(cached.get('tickers') or []),cache_file_sha256=hashlib.sha256(cache_path.read_bytes()).hexdigest(),content_sha256=cached.get('content_sha256'));raise StopIteration
  import market_scout
  market_scout._atlas_log_api_call=None
  tickers=market_scout.discover_tickers()
  payload={'schema':'atlas.provider_discovery_cache.v1','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'ttl_seconds':1800,'tickers':tickers,'buckets':market_scout.last_discovery_buckets()}
  payload['content_sha256']=hashlib.sha256(canon({k:v for k,v in payload.items() if k!='content_sha256'})).hexdigest();cache_sha=atomic(a.cache,payload)
  receipt.update(status='PASS',action='REFRESHED',ticker_count=len(tickers),cache_file_sha256=cache_sha,content_sha256=payload['content_sha256'])
 except StopIteration:
  pass
 except Exception as exc:
  receipt.update(status='FAIL',failure_name='PROVIDER_DISCOVERY_WARMUP_FAILED',exception_type=type(exc).__name__,reason=str(exc)[:500])
 finally:
  receipt['elapsed_seconds']=round(time.monotonic()-started,6);receipt['completed_at']=dt.datetime.now(dt.timezone.utc).isoformat();atomic(a.receipt,receipt)
 print(json.dumps(receipt,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
