#!/usr/bin/env python3
"""Locked/gated acquisition+bake+retention orchestration; no sends or production writes."""
import argparse, datetime as dt, fcntl, json, os, shutil, signal, sqlite3, subprocess, sys
from pathlib import Path
from zoneinfo import ZoneInfo
BUSY_LABELS=("com.atlas.intraday","com.atlas.eod.positions","com.atlas.macro.postmarket","com.atlas.hermesgdrivebackup")
BUSY_PROCESS_NAMES=("atlas_manage.py","market_scout")
def trading_gate(now):
 from atlas_position_evidence_acquire import is_session
 et=now.astimezone(ZoneInfo("America/New_York"));return is_session(et.date()) and (et.hour,et.minute)>=(16,40),et
def running(labels):
 active=[]
 try:
  text=subprocess.run(["/bin/launchctl","list"],capture_output=True,text=True,timeout=5,check=False).stdout
  for line in text.splitlines():
   p=line.split("\t")
   if len(p)>=3 and p[2] in labels and p[0]!="-":active.append("label:"+p[2])
 except Exception:pass
 try:
  text=subprocess.run(["/bin/ps","-axo","pid=,command="],capture_output=True,text=True,timeout=5,check=False).stdout
  me=os.getpid()
  for line in text.splitlines():
   bits=line.strip().split(None,1)
   if len(bits)==2 and int(bits[0])!=me and any(n in bits[1] for n in BUSY_PROCESS_NAMES):active.append("process:"+bits[0]+":"+next(n for n in BUSY_PROCESS_NAMES if n in bits[1]))
 except Exception:pass
 return sorted(set(active))
def backup_shadow(src,backup_dir,now):
 src=Path(src);out=Path(backup_dir);out.mkdir(parents=True,exist_ok=True);dest=out/("evidence_"+now.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".sqlite")
 s=sqlite3.connect(f"file:{src.resolve()}?mode=ro",uri=True);d=sqlite3.connect(dest)
 try:s.backup(d);d.execute("PRAGMA quick_check").fetchone();d.close();s.close();os.chmod(dest,0o400)
 except Exception:
  d.close();s.close();dest.unlink(missing_ok=True);raise
 return str(dest)
def cleanup(directory,days,now,patterns):
 cutoff=now.timestamp()-days*86400;removed=[]
 for pat in patterns:
  for p in Path(directory).glob(pat):
   if p.is_file() and p.stat().st_mtime<cutoff:p.unlink();removed.append(str(p))
 return removed
def run(args):
 now=dt.datetime.fromisoformat(args.asof.replace("Z","+00:00")) if args.asof else dt.datetime.now(dt.timezone.utc);ok,et=trading_gate(now)
 if not ok:return {"status":"SKIP_GATE","et":et.isoformat()}
 busy=running(BUSY_LABELS) if not args.skip_idle_check else []
 if busy:return {"status":"SKIP_BUSY","active":busy}
 lock=Path(args.lock);lock.parent.mkdir(parents=True,exist_ok=True);fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:os.close(fd);return {"status":"SKIP_LOCKED"}
 try:
  acq=[sys.executable,args.acquire,"--db",args.db,"--snapshot-dir",args.snapshot_dir,"--timeout",str(args.provider_timeout),"--api-key-env",args.api_key_env]
  if args.asof:acq += ["--asof",args.asof]
  if args.provider_template:acq += ["--provider-template",args.provider_template]
  if args.allow_incomplete_final:acq += ["--allow-incomplete-final"]
  a=subprocess.run(acq,capture_output=True,text=True,timeout=args.acquire_timeout,check=False)
  if a.returncode:return {"status":"ERROR_ACQUIRE","returncode":a.returncode,"stderr":a.stderr[-1000:]}
  ar=json.loads(a.stdout.strip().splitlines()[-1])
  if ar.get("status")!="ACQUIRED":return ar
  b=subprocess.run([sys.executable,args.bake,"--snapshot",ar["snapshot"],"--shadow-db",args.shadow_db],capture_output=True,text=True,timeout=args.bake_timeout,check=False)
  if b.returncode:return {"status":"ERROR_BAKE","returncode":b.returncode,"stderr":b.stderr[-1000:]}
  br=json.loads(b.stdout.strip().splitlines()[-1]);backup=backup_shadow(args.shadow_db,args.backup_dir,now);removed={"backups":cleanup(args.backup_dir,args.backup_retention_days,now,("evidence_*.sqlite",)),"snapshots":cleanup(args.snapshot_dir,args.snapshot_retention_days,now,("snapshot_*.json",))}
  return {"status":"COMPLETE","acquire":ar,"bake":br,"backup":backup,"retention_removed":removed}
 except subprocess.TimeoutExpired as e:return {"status":"TIMEOUT","phase":Path(e.cmd[1]).name if len(e.cmd)>1 else "unknown"}
 finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def main():
 p=argparse.ArgumentParser();base="/Users/yasser/Library/Application Support/Atlas/position_evidence_bake";p.add_argument("--acquire",default="/Users/yasser/scripts/atlas_position_evidence_acquire.py");p.add_argument("--bake",default="/Users/yasser/scripts/atlas_position_evidence_bake.py");p.add_argument("--db",default="/Users/yasser/scripts/atlas.db");p.add_argument("--snapshot-dir",default=base+"/snapshots");p.add_argument("--shadow-db",default=base+"/shadow/evidence.sqlite");p.add_argument("--backup-dir",default=base+"/backups");p.add_argument("--lock",default=base+"/run/orchestrator.lock");p.add_argument("--provider-template");p.add_argument("--api-key-env",default="MASSIVE_API_KEY");p.add_argument("--provider-timeout",type=float,default=8);p.add_argument("--acquire-timeout",type=float,default=180);p.add_argument("--bake-timeout",type=float,default=60);p.add_argument("--snapshot-retention-days",type=int,default=400);p.add_argument("--backup-retention-days",type=int,default=90);p.add_argument("--asof");p.add_argument("--allow-incomplete-final",action="store_true");p.add_argument("--skip-idle-check",action="store_true");a=p.parse_args();print(json.dumps(run(a),sort_keys=True))
if __name__=="__main__":main()
