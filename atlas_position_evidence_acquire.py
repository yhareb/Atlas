#!/usr/bin/env python3
"""Bounded Massive acquisition from a query-only Atlas DB into an immutable snapshot."""
import argparse, datetime as dt, hashlib, json, os, sqlite3, tempfile, urllib.parse, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA="atlas-position-evidence-snapshot-v2"
BUCKETS=("broker_confirmed_completed","anomalous_disputed","filled_pullbacks","signal_only_non_fills","current_open","shadow_policy_observations")
TRADE_COLS="id,ticker,status,quantity,entry_price,entry_at,exit_price,exit_at,entry_fees,exit_fees,realized_pnl,realized_pnl_pct,parent_id,notes,updated_at,stop_loss,risk_pct,target_price,broker_ref,manual_stop_lock,current_price,last_price,last_price_at"
PULLBACK_COLS="id,ticker,status,score,signal,signal_json,armed_at,expires_at,ema10,trigger_price,reference_price,pct_over_ema,filled_at,expired_at,updated_at"
SIGNAL_COLS="id,timestamp,ticker,signal,score,rvol,entry_price,stop_loss,max_loss_per_share,atr,trend_stack,relative_strength,volume,catalyst,warnings"
def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def digest(x): return hashlib.sha256(canon(x).encode()).hexdigest()
def file_sha(p):
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def utcnow(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
def query(c,s,a=()): return [dict(r) for r in c.execute(s,a)]
def nth_weekday(y,m,w,n):
 d=dt.date(y,m,1)
 return d+dt.timedelta(days=(w-d.weekday())%7+7*(n-1))
def last_weekday(y,m,w):
 d=dt.date(y,m+1,1)-dt.timedelta(days=1) if m<12 else dt.date(y,12,31)
 return d-dt.timedelta(days=(d.weekday()-w)%7)
def observed(d):
 return d-dt.timedelta(days=1) if d.weekday()==5 else d+dt.timedelta(days=1) if d.weekday()==6 else d
def easter(y):
 a=y%19;b=y//100;c=y%100;d=b//4;e=b%4;f=(b+8)//25;g=(b-f+1)//3;h=(19*a+b-d-g+15)%30;i=c//4;k=c%4;l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
 return dt.date(y,(h+l-7*m+114)//31,(h+l-7*m+114)%31+1)
def nyse_holidays(y):
 hs={observed(dt.date(y,1,1)),nth_weekday(y,1,0,3),nth_weekday(y,2,0,3),easter(y)-dt.timedelta(days=2),last_weekday(y,5,0),observed(dt.date(y,7,4)),nth_weekday(y,9,0,1),nth_weekday(y,11,3,4),observed(dt.date(y,12,25))}
 if y>=2022: hs.add(observed(dt.date(y,6,19)))
 # New Year's observed can fall in prior calendar year.
 hs.add(observed(dt.date(y+1,1,1)))
 return hs
def is_session(d): return d.weekday()<5 and d not in nyse_holidays(d.year) and d not in nyse_holidays(d.year-1)

def fetch_massive(symbol,template,timeout,api_key,from_date,to_date):
 base=template.format(symbol=urllib.parse.quote(symbol,safe=""),from_date=from_date,to_date=to_date)
 sep="&" if "?" in base else "?"; url=base+sep+urllib.parse.urlencode({"adjusted":"true","sort":"asc","limit":"50000","apiKey":api_key})
 req=urllib.request.Request(url,headers={"User-Agent":"AtlasEvidenceBake/2.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=timeout) as r:
  if getattr(r,"status",200)!=200: raise RuntimeError(f"Massive HTTP {r.status}")
  raw=r.read(4_000_001)
 if len(raw)>4_000_000: raise RuntimeError("Massive response too large")
 obj=json.loads(raw); rows=obj.get("results") or []
 bars=[]
 for x in rows:
  if x.get("c") is None: continue
  bars.append({"session_date":dt.datetime.fromtimestamp(x["t"]/1000,dt.timezone.utc).date().isoformat(),"provider_timestamp":dt.datetime.fromtimestamp(x["t"]/1000,dt.timezone.utc).isoformat().replace("+00:00","Z"),"open":x.get("o"),"high":x.get("h"),"low":x.get("l"),"close":x.get("c"),"volume":x.get("v"),"vwap":x.get("vw"),"transactions":x.get("n")})
 if not bars: raise RuntimeError("Massive returned no adjusted daily aggregates")
 return {"provider":"massive","dataset":"adjusted_daily_aggregates","adjusted":True,"provider_request_id":obj.get("request_id"),"provider_status":obj.get("status"),"bars":bars}

def classify(trades,pullbacks,signals,session_date):
 anomaly=[];completed=[];opens=[]
 for r in trades:
  text=(r.get("notes") or "").lower(); status=r.get("status")
  disputed=(r.get("ticker","").upper()=="TSM" or any(x in text for x in ("wrong target","unauthorized","reversal","disputed","anomal")))
  if disputed: anomaly.append(r)
  elif status=="CLOSED" and (r.get("broker_ref") or any(x in text for x in ("broker sell","broker fill confirmed","broker screenshot","trade story"))): completed.append(r)
  if status=="OPEN": opens.append(r)
 # Eligible entry candidates are BUY-family production signals from this trading session,
 # with an explicitly parseable score >=2/4. Keep only latest ticker/day, bounded to 250.
 dedup={}
 for r in signals:
  text=str(r.get("signal") or "").upper();score=str(r.get("score") or "");ts=str(r.get("timestamp") or "")
  try: points=int(score.split("/",1)[0])
  except (ValueError,TypeError): points=-1
  if ts[:10]==session_date and "BUY" in text and points>=2:
   x=dict(r);x.update({"is_fill":False,"evidence_class":"signal_only","eligibility_rule":"session BUY-family and score >=2/4; latest ticker/day; max 250","score_points":points,"updated_at":r.get("timestamp")})
   dedup[str(r["ticker"]).upper()]=x
 signal_nonfills=sorted(dedup.values(),key=lambda x:(str(x.get("timestamp")),int(x["id"])),reverse=True)[:250]
 filled=[r for r in pullbacks if r.get("status")=="FILLED"]
 policy=[]
 for r in trades:
  text=(r.get("notes") or "").lower()
  if any(x in text for x in ("advisory","target governance","professor","override","stop loss added","stop-loss update")): policy.append(r)
 return {"broker_confirmed_completed":completed,"anomalous_disputed":anomaly,"filled_pullbacks":filled,"signal_only_non_fills":signal_nonfills,"current_open":opens,"shadow_policy_observations":policy}

def acquire(db_path,snapshot_dir,provider_template,timeout,asof=None,require_final=True,api_key_env="MASSIVE_API_KEY"):
 now=dt.datetime.fromisoformat(asof.replace("Z","+00:00")) if asof else utcnow();now=now.astimezone(dt.timezone.utc).replace(microsecond=0);et=now.astimezone(ZoneInfo("America/New_York"))
 if not is_session(et.date()) or (et.hour,et.minute)<(16,40): return {"status":"SKIP_GATE","reason":"not an NYSE session at/after 16:40 ET","et":et.isoformat()}
 key=os.environ.get(api_key_env)
 if not key: return {"status":"ERROR_PROVIDER_AUTH","reason":f"required environment variable {api_key_env} is unset"}
 source_before=file_sha(db_path);uri="file:"+urllib.parse.quote(str(Path(db_path).resolve()),safe="/")+"?mode=ro"
 c=sqlite3.connect(uri,uri=True);c.row_factory=sqlite3.Row;c.execute("PRAGMA query_only=ON")
 trades=query(c,"SELECT "+TRADE_COLS+" FROM trades ORDER BY id");pullbacks=query(c,"SELECT "+PULLBACK_COLS+" FROM pending_pullbacks ORDER BY id");signals=query(c,"SELECT "+SIGNAL_COLS+" FROM signals WHERE substr(timestamp,1,10)=? ORDER BY timestamp,id",(et.date().isoformat(),));c.close()
 buckets=classify(trades,pullbacks,signals,et.date().isoformat());symbols=sorted({str(r["ticker"]).upper() for rows in buckets.values() for r in rows})
 start=(et.date()-dt.timedelta(days=180)).isoformat();end=et.date().isoformat();provider={};errors={}
 for s in symbols:
  try: provider[s]=fetch_massive(s,provider_template,timeout,key,start,end)
  except Exception as e: errors[s]=f"{type(e).__name__}: {e}"
 expected=et.date().isoformat();required_final=sorted({str(r["ticker"]).upper() for r in buckets["current_open"]});final={s:{"last_bar_et_session_date":p["bars"][-1]["session_date"],"available":p["bars"][-1]["session_date"]==expected,"required":s in required_final} for s,p in provider.items()}
 required_errors={s:e for s,e in errors.items() if s in required_final}
 if require_final and (required_errors or any(s not in final or not final[s]["available"] for s in required_final)): return {"status":"SKIP_FINAL_BARS","expected_et_session":expected,"required_current_open_symbols":required_final,"symbol_count":len(symbols),"final":final,"errors":errors,"source_db_unchanged":source_before==file_sha(db_path)}
 source_after=file_sha(db_path)
 body={"schema":SCHEMA,"captured_at":now.isoformat().replace("+00:00","Z"),"expected_et_session":expected,"source":{"db_path":str(Path(db_path).resolve()),"sqlite_mode":"ro+query_only","db_sha256_before":source_before,"db_sha256_after":source_after,"db_unchanged":source_before==source_after,"provider":"massive","provider_dataset":"adjusted_daily_aggregates","adjusted":True,"api_key_env_name":api_key_env,"provider_timeout_seconds":timeout,"final_bar_policy":"strict for current OPEN; historical/delisted evidence explicitly labeled but does not block"},"buckets":buckets,"provider":provider,"provider_errors":errors,"final_bar_checks":final}
 body["content_sha256"]=digest(body);outdir=Path(snapshot_dir);outdir.mkdir(parents=True,exist_ok=True);dest=outdir/(now.strftime("snapshot_%Y%m%dT%H%M%SZ_")+body["content_sha256"][:16]+".json");data=(json.dumps(body,indent=2,sort_keys=True)+"\n").encode();fd,tmp=tempfile.mkstemp(prefix=".snapshot.",dir=outdir)
 try:
  os.write(fd,data);os.fsync(fd);os.close(fd);os.link(tmp,dest);os.unlink(tmp);os.chmod(dest,0o440)
 except Exception:
  try: os.close(fd)
  except OSError: pass
  try: os.unlink(tmp)
  except OSError: pass
  raise
 return {"status":"ACQUIRED","snapshot":str(dest),"content_sha256":body["content_sha256"],"bucket_counts":{k:len(v) for k,v in buckets.items()},"provider":"massive","source_db_sha256_before":source_before,"source_db_sha256_after":source_after,"source_db_unchanged":source_before==source_after,"errors":errors}
def main():
 p=argparse.ArgumentParser();p.add_argument("--db",default=os.environ.get("ATLAS_DB","/Users/yasser/scripts/atlas.db"));p.add_argument("--snapshot-dir",default=os.environ.get("ATLAS_EVIDENCE_SNAPSHOTS","/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/snapshots"));p.add_argument("--provider-template",default="https://api.massive.com/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}");p.add_argument("--api-key-env",default="MASSIVE_API_KEY");p.add_argument("--timeout",type=float,default=8);p.add_argument("--asof");p.add_argument("--allow-incomplete-final",action="store_true");a=p.parse_args();print(json.dumps(acquire(a.db,a.snapshot_dir,a.provider_template,a.timeout,a.asof,not a.allow_incomplete_final,a.api_key_env),sort_keys=True))
if __name__=="__main__":main()
