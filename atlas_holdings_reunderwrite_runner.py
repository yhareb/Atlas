#!/usr/bin/env python3
"""ET-aware staging runner; advisory sidecar only."""
import argparse,datetime as dt,fcntl,json,os,sqlite3,tempfile
from pathlib import Path
from zoneinfo import ZoneInfo
from atlas_holdings_reunderwrite import build_packet,stable_actions
ET=ZoneInfo('America/New_York')
# NYSE full-close exceptions; runner also requires authoritative evidence for the session.
HOLIDAYS={'2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-06-19','2026-07-03','2026-09-07','2026-11-26','2026-12-25'}
SCHEMA='CREATE TABLE IF NOT EXISTS runs(session TEXT NOT NULL,input_digest TEXT NOT NULL,packet_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(session,input_digest));'
def trading_day(d):return d.weekday()<5 and d.isoformat() not in HOLIDAYS
def due_session(now):
    now=now.astimezone(ET); d=now.date()
    if trading_day(d) and now.time()>=dt.time(16,15):return d.isoformat()
    d-=dt.timedelta(days=1)
    while not trading_day(d):d-=dt.timedelta(days=1)
    return d.isoformat()
def atomic(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);data=json.dumps(obj,sort_keys=True,indent=2)+'\n'; fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=p.name+'.')
    with os.fdopen(fd,'w') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
def run(db,evidence,out,sidecar,now,force_session=None):
    session=force_session or due_session(now); packet=build_packet(db,evidence,session)
    Path(sidecar).parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(sidecar);con.execute('PRAGMA foreign_keys=ON');con.execute(SCHEMA)
    before=con.total_changes;con.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?)',(session,packet['input_digest'],json.dumps(packet,sort_keys=True),now.astimezone(dt.timezone.utc).isoformat()));con.commit();inserted=con.total_changes-before
    atomic(out,packet);con.close()
    return {'status':'INSERTED' if inserted else 'IDEMPOTENT_NO_OP','session':session,'positions':len(packet['positions']),'input_digest':packet['input_digest'],'stable_actions':stable_actions(packet)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--evidence',required=True);p.add_argument('--out',required=True);p.add_argument('--sidecar',required=True);p.add_argument('--now');p.add_argument('--force-session');a=p.parse_args()
    now=dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(ET)
    print(json.dumps(run(a.db,a.evidence,a.out,a.sidecar,now,a.force_session),sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
