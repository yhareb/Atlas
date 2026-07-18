#!/usr/bin/env python3
"""Atlas Quiver observation-only sidecar.

Production-release candidate. No trading authority, no Telegram, no broker action,
no Atlas DB writes. Writes only the dedicated Quiver sidecar root.
"""
from __future__ import annotations
import argparse, csv, datetime as dt, fcntl, hashlib, json, os, plistlib, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, ssl
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable
from zoneinfo import ZoneInfo

VERSION="quiver_observation_sidecar_release_v1_2026_07"
ROOT_DEFAULT="/Users/yasser/Library/Application Support/Atlas/quiver_shadow"
ATLAS_DB_DEFAULT="/Users/yasser/scripts/atlas.db"
ATLAS_ENV_DEFAULT="/Users/yasser/.hermes/profiles/atlas/.env"
KEY_NAME="QUIVER_API_KEY"
BASE="https://api.quiverquant.com/beta/live/"
ET=ZoneInfo("America/New_York")
ENABLED={"congress":"congresstrading","government_contracts":"govcontracts","lobbying":"lobbying","off_exchange":"offexchange"}
DISABLED={"government_contracts_all":"allgovcontracts","insider_trading":"insiders","patents":"patents","institutional_13f_changes":"sec13f"}
AVAIL_FIELDS=("ReportDate","last_modified","filing_date","filed_date","filingDate","filedDate","disclosure_date","disclosureDate","publication_date","publicationDate","published_date","publishedDate","upload_date","uploadDate","report_date","reportDate","date")
TX_FIELDS=("TransactionDate","transaction_date","transactionDate","trade_date","tradeDate","tx_date","effective_date","effectiveDate")
ID_FIELDS=("id","event_id","ReportID","filing_id","contract_id","Ticker","ticker","Description")
BUY_RE=re.compile(r"(?:🟢|🟡)?\s*BUY(?:\s*\((Small)\))?", re.I)
BUSY_LABELS=("com.atlas.intraday","com.atlas.eod.positions","com.atlas.position_evidence_bake","com.atlas.profit_protection_v2_apply","com.atlas.macro.postmarket","com.atlas.hermesgdrivebackup","com.atlas.api_audit")
BUSY_PROCESS_NAMES=("atlas_intraday.py","atlas_eod_positions.py","atlas_position_evidence_orchestrator.py","atlas_profit_protection_apply.py","atlas_manage.py","market_scout")


def sha_bytes(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def sha_file(path:str|Path)->str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
def canon(x:Any)->str: return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def now()->str: return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def parse_dt(v:Any)->dt.datetime|None:
    if not v: return None
    s=str(v).strip()
    for fmt in ("%Y-%m-%d","%m/%d/%Y","%Y/%m/%d"):
        try: return dt.datetime.strptime(s[:10],fmt).replace(tzinfo=dt.timezone.utc)
        except Exception: pass
    try:
        d=dt.datetime.fromisoformat(s.replace("Z","+00:00"))
        if d.tzinfo is None: d=d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception: return None

def safe_float(x):
    try:
        if x in (None,""): return None
        return float(x)
    except Exception: return None

def read_key(env_path:str=ATLAS_ENV_DEFAULT)->str:
    found=[]
    with open(env_path,'r',encoding='utf-8',errors='replace') as f:
        for raw in f:
            s=raw.strip()
            if not s or s.startswith('#'): continue
            if s.startswith('export '): s=s[7:].strip()
            if not s.startswith(KEY_NAME+'='): continue
            v=s.split('=',1)[1].strip()
            if len(v)>=2 and v[0]==v[-1] and v[0] in ('"',"'"): v=v[1:-1]
            if not v or '\x00' in v or '\n' in v or '\r' in v: raise RuntimeError(f'invalid {KEY_NAME}')
            found.append(v)
    if len(found)!=1: raise RuntimeError(f'expected exactly one {KEY_NAME}; found {len(found)}')
    return found[0]

def minimal_child_env(key:str, extra:dict[str,str]|None=None)->dict[str,str]:
    env={"HOME":str(Path.home()),"PATH":"/usr/bin:/bin:/usr/sbin:/sbin",KEY_NAME:key}
    for k,v in (extra or {}).items():
        if k.startswith('ATLAS_QUIVER_'): env[k]=v
    return env

def root_paths(root:str=ROOT_DEFAULT)->dict[str,Path]:
    r=Path(root)
    return {"root":r,"db":r/"db"/"quiver_sidecar.sqlite","cache":r/"cache","reports":r/"reports","logs":r/"logs","run":r/"run","backups":r/"backups"}

def ensure_dirs(root:str):
    for p in root_paths(root).values():
        if p.suffix: p.parent.mkdir(parents=True,exist_ok=True)
        else: p.mkdir(parents=True,exist_ok=True)

def con(path:str|Path, write=True)->sqlite3.Connection:
    c=sqlite3.connect(str(path) if write else f'file:{Path(path).resolve()}?mode=ro', uri=not write)
    c.execute('PRAGMA foreign_keys=ON')
    if not write: c.execute('PRAGMA query_only=ON')
    return c

def init_db(db_path:str|Path):
    Path(db_path).parent.mkdir(parents=True,exist_ok=True)
    c=con(db_path,True)
    c.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, run_type TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL, version TEXT NOT NULL, atlas_db_sha_before TEXT, atlas_db_sha_after TEXT, notes TEXT);
    CREATE TABLE IF NOT EXISTS baseline(baseline_id TEXT PRIMARY KEY, deployed_at TEXT NOT NULL, atlas_db_sha TEXT NOT NULL, max_signal_id INTEGER NOT NULL, mode TEXT NOT NULL CHECK(mode='FORWARD_ONLY'));
    CREATE TABLE IF NOT EXISTS endpoint_entitlements(run_id TEXT NOT NULL, dataset TEXT NOT NULL, endpoint_path TEXT NOT NULL, classification TEXT NOT NULL, http_status INTEGER, latency_ms REAL, field_names_json TEXT NOT NULL, wrapper_keys_json TEXT NOT NULL, record_count INTEGER, checked_at TEXT NOT NULL, PRIMARY KEY(run_id,dataset,endpoint_path), FOREIGN KEY(run_id) REFERENCES runs(run_id));
    CREATE TABLE IF NOT EXISTS api_requests(request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dataset TEXT NOT NULL, endpoint_path TEXT NOT NULL, query_json TEXT NOT NULL, requested_at TEXT NOT NULL, http_status INTEGER, latency_ms REAL, classification TEXT NOT NULL, response_sha256 TEXT, cache_path TEXT, schema_digest TEXT, FOREIGN KEY(run_id) REFERENCES runs(run_id));
    CREATE TABLE IF NOT EXISTS api_cache_manifest(cache_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, cache_path TEXT NOT NULL, content_sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, written_at TEXT NOT NULL, atomic_write INTEGER NOT NULL CHECK(atomic_write=1), FOREIGN KEY(request_id) REFERENCES api_requests(request_id));
    CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, signal_id INTEGER NOT NULL, ticker TEXT NOT NULL, signal_timestamp TEXT NOT NULL, raw_label TEXT NOT NULL, normalized_label TEXT NOT NULL, score TEXT, entry REAL, stop REAL, atr REAL, rvol REAL, trend TEXT, catalyst TEXT, warnings TEXT, capture_timestamp TEXT NOT NULL, canonical_source_db_sha TEXT NOT NULL, is_fill INTEGER NOT NULL CHECK(is_fill=0), evidence_class TEXT NOT NULL CHECK(evidence_class='signal_only'), broker_claim INTEGER NOT NULL CHECK(broker_claim=0), metric_class TEXT NOT NULL CHECK(metric_class='LIVE_FORWARD'), UNIQUE(signal_id,ticker,signal_timestamp), FOREIGN KEY(run_id) REFERENCES runs(run_id));
    CREATE TABLE IF NOT EXISTS evidence_events(event_uid TEXT PRIMARY KEY, run_id TEXT NOT NULL, dataset TEXT NOT NULL, ticker TEXT, raw_event_id TEXT, availability_ts TEXT, availability_field TEXT, transaction_ts_seen TEXT, transaction_date_ignored INTEGER NOT NULL, payload_digest TEXT NOT NULL, cache_id TEXT, polarity REAL NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0, excluded_reason TEXT, metric_class TEXT NOT NULL CHECK(metric_class='LIVE_FORWARD'), created_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id), FOREIGN KEY(cache_id) REFERENCES api_cache_manifest(cache_id));
    CREATE TABLE IF NOT EXISTS candidate_evidence_links(link_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, event_uid TEXT NOT NULL, age_days INTEGER, freshness_weight REAL, contribution REAL, FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id), FOREIGN KEY(event_uid) REFERENCES evidence_events(event_uid), UNIQUE(candidate_id,event_uid));
    CREATE TABLE IF NOT EXISTS shadow_scores(score_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, total_score REAL NOT NULL, bucket TEXT NOT NULL, dataset_contrib_json TEXT NOT NULL, contributing_events_json TEXT NOT NULL, excluded_events_json TEXT NOT NULL, calc_version TEXT NOT NULL, input_digest TEXT NOT NULL, metric_class TEXT NOT NULL CHECK(metric_class='LIVE_FORWARD'), calculated_at TEXT NOT NULL, FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id), FOREIGN KEY(run_id) REFERENCES runs(run_id));
    CREATE TABLE IF NOT EXISTS forward_returns(settlement_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, horizon_sessions INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('PENDING','SETTLED')), entry_price REAL, settlement_price REAL, return_pct REAL, return_R REAL, price_provenance TEXT, settlement_session_date TEXT, settlement_timestamp TEXT, transaction_cost_bps REAL NOT NULL DEFAULT 5.0, gap_behavior TEXT NOT NULL, metric_class TEXT NOT NULL CHECK(metric_class='LIVE_FORWARD'), UNIQUE(candidate_id,horizon_sessions), FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id));
    CREATE TABLE IF NOT EXISTS weekly_metrics(metric_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, week_start TEXT NOT NULL, json_path TEXT, md_path TEXT, csv_path TEXT, metrics_json TEXT NOT NULL, metric_class TEXT NOT NULL CHECK(metric_class IN ('LIVE_FORWARD','HISTORICAL_RESEARCH')), FOREIGN KEY(run_id) REFERENCES runs(run_id));
    CREATE TABLE IF NOT EXISTS high_water(entity_key TEXT PRIMARY KEY, max_value TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS stale_observations(observation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, entity_key TEXT NOT NULL, observed_value TEXT NOT NULL, preserved_max_value TEXT NOT NULL, reason TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id));
    CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence_events BEGIN SELECT RAISE(ABORT,'append_only_evidence_events'); END;
    CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence_events BEGIN SELECT RAISE(ABORT,'append_only_evidence_events'); END;
    CREATE TRIGGER IF NOT EXISTS high_water_no_regress BEFORE UPDATE ON high_water WHEN NEW.max_value < OLD.max_value BEGIN SELECT RAISE(ABORT,'high_water_regression'); END;
    ''')
    c.commit(); c.close()

def atlas_snapshot(db_path:str)->dict[str,Any]:
    c=con(db_path,False)
    try:
        counts={t:c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        return {"sha":sha_file(db_path),"integrity":c.execute('PRAGMA integrity_check').fetchone()[0],"fk_rows":len(c.execute('PRAGMA foreign_key_check').fetchall()),"counts":counts}
    finally: c.close()

def start_run(db_path:str, run_type:str, atlas_db:str)->str:
    rid='run_'+sha_bytes(f'{run_type}|{now()}|{os.getpid()}|{time.time_ns()}'.encode())[:24]
    c=con(db_path,True); c.execute('INSERT INTO runs(run_id,run_type,started_at,status,version,atlas_db_sha_before) VALUES(?,?,?,?,?,?)',(rid,run_type,now(),'STARTED',VERSION,sha_file(atlas_db) if Path(atlas_db).exists() else None)); c.commit(); c.close(); return rid

def finish_run(db_path:str, run_id:str, status:str, atlas_db:str, notes:str=''):
    c=con(db_path,True); c.execute('UPDATE runs SET completed_at=?,status=?,atlas_db_sha_after=?,notes=? WHERE run_id=?',(now(),status,sha_file(atlas_db) if Path(atlas_db).exists() else None,notes,run_id)); c.commit(); c.close()

def initialize_baseline(sidecar:str, atlas_db:str)->dict:
    init_db(sidecar)
    c_ro=con(atlas_db,False); max_id=c_ro.execute('SELECT COALESCE(MAX(id),0) FROM signals').fetchone()[0]; c_ro.close()
    sid='baseline_forward_only'
    c=con(sidecar,True)
    c.execute('INSERT OR IGNORE INTO baseline VALUES(?,?,?,?,?)',(sid,now(),sha_file(atlas_db),int(max_id),'FORWARD_ONLY'))
    c.execute('INSERT OR REPLACE INTO high_water VALUES(?,?,?)',('signals.max_id',str(max_id),now()))
    c.commit(); c.close(); return {'baseline_id':sid,'max_signal_id':int(max_id),'atlas_db_sha':sha_file(atlas_db),'mode':'FORWARD_ONLY'}

def normalize_label(label:str)->str|None:
    m=BUY_RE.search(label or '')
    if not m: return None
    return 'BUY_SMALL' if m.group(1) else 'BUY'

def capture_candidates(sidecar:str, run_id:str, atlas_db:str, *, limit:int=500)->dict:
    db_before=sha_file(atlas_db); c_ro=con(atlas_db,False)
    try:
        cols=[r[1] for r in c_ro.execute('PRAGMA table_info(signals)')]
        wanted=[x for x in ['id','timestamp','ticker','signal','score','entry_price','stop_loss','atr','rvol','trend','catalyst','warnings','signal_json'] if x in cols]
        baseline=c_ro.execute('SELECT COALESCE(MAX(id),0) FROM signals').fetchone()[0]
        # baseline comes from sidecar, not Atlas current max
    finally: c_ro.close()
    c=con(sidecar,True); b=c.execute("SELECT max_signal_id FROM baseline WHERE baseline_id='baseline_forward_only'").fetchone()
    if not b: raise RuntimeError('baseline not initialized')
    base_id=int(b[0]); c.close()
    c_ro=con(atlas_db,False)
    rows=c_ro.execute('SELECT '+','.join(wanted)+' FROM signals WHERE id>? ORDER BY id ASC LIMIT ?', (base_id,limit)).fetchall(); c_ro.close()
    c=con(sidecar,True); inserted=0; seen=0; rejected=0; examples=[]; max_seen=base_id
    for row in rows:
        d=dict(zip(wanted,row)); max_seen=max(max_seen,int(d['id']))
        norm=normalize_label(str(d.get('signal') or ''))
        if not norm: rejected+=1; continue
        seen+=1
        sig_json={}
        try: sig_json=json.loads(d.get('signal_json') or '{}') if 'signal_json' in d else {}
        except Exception: sig_json={}
        cid='cand_'+sha_bytes(canon({'signal_id':d['id'],'ticker':str(d.get('ticker')).upper(),'ts':d.get('timestamp')}).encode())[:32]
        vals=(cid,run_id,int(d['id']),str(d.get('ticker')).upper(),str(d.get('timestamp')),str(d.get('signal')),norm,str(d.get('score')),safe_float(d.get('entry_price')),safe_float(d.get('stop_loss')),safe_float(d.get('atr') or sig_json.get('atr')),safe_float(d.get('rvol') or sig_json.get('rvol')),d.get('trend') or sig_json.get('trend'),d.get('catalyst') or sig_json.get('catalyst'),d.get('warnings') or sig_json.get('warnings'),now(),db_before,0,'signal_only',0,'LIVE_FORWARD')
        cur=c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals); inserted+=cur.rowcount
        if len(examples)<5: examples.append({'signal_id':d['id'],'ticker':str(d.get('ticker')).upper(),'raw_label':d.get('signal'),'normalized_label':norm,'is_fill':False,'evidence_class':'signal_only','broker_claim':False})
    old=c.execute("SELECT max_value FROM high_water WHERE entity_key='signals.max_id'").fetchone()
    if max_seen>=int(old[0]): c.execute("UPDATE high_water SET max_value=?, updated_at=? WHERE entity_key='signals.max_id'",(str(max_seen),now()))
    else: c.execute('INSERT OR IGNORE INTO stale_observations VALUES(?,?,?,?,?,?)',('stale_'+sha_bytes(str(max_seen).encode())[:20],run_id,'signals.max_id',str(max_seen),old[0],'non_regression_preserved'))
    c.commit(); c.close(); db_after=sha_file(atlas_db)
    if db_before!=db_after: raise RuntimeError('Atlas DB changed during read')
    return {'source_db_sha_before':db_before,'source_db_sha_after':db_after,'baseline_signal_id':base_id,'new_buy_family_seen':seen,'inserted':inserted,'non_buy_rejected':rejected,'examples':examples}

def record_endpoint(sidecar, run_id, dataset, path, classification, status, latency, fields, wrappers, rows):
    c=con(sidecar,True); c.execute('INSERT OR REPLACE INTO endpoint_entitlements VALUES(?,?,?,?,?,?,?,?,?,?)',(run_id,dataset,'/beta/live/'+path,classification,status,latency,canon(fields),canon(wrappers),rows,now())); c.commit(); c.close()

def request_endpoint(sidecar:str, run_id:str, root:str, key:str, dataset:str, path:str, params:dict|None=None)->dict:
    params=params or {}; url=BASE+path+(('?' + urllib.parse.urlencode(params)) if params else '')
    t0=time.time(); raw=b''; status=None; classification='ERROR'; headers={}; data=None
    req=urllib.request.Request(url,headers={'Authorization':'Token '+key,'User-Agent':'AtlasQuiverRelease/1.0','Accept':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=18,context=ssl.create_default_context()) as resp:
            status=resp.status; headers=dict(resp.headers); raw=resp.read(500000); classification='ENTITLED'
    except urllib.error.HTTPError as e:
        status=e.code; headers=dict(e.headers); raw=e.read(50000); classification='UNENTITLED' if status in (401,403) else ('NOT_FOUND' if status==404 else 'ERROR')
    except Exception as e:
        raw=json.dumps({'error_type':type(e).__name__}).encode(); classification='ERROR'
    latency=round((time.time()-t0)*1000,1)
    try: data=json.loads(raw.decode('utf-8','replace'))
    except Exception: data=None
    records=[]; wrappers=[]
    if isinstance(data,list): records=data
    elif isinstance(data,dict):
        wrappers=sorted(data.keys())
        for v in data.values():
            if isinstance(v,list): records=v; break
    fields=sorted(records[0].keys()) if records and isinstance(records[0],dict) else (sorted(data.keys()) if isinstance(data,dict) else [])
    content_sha=sha_bytes(raw); rid='req_'+sha_bytes(canon({'run':run_id,'dataset':dataset,'path':path,'params':params,'sha':content_sha}).encode())[:32]
    cache_dir=root_paths(root)['cache']; cache_dir.mkdir(parents=True,exist_ok=True); cache_path=cache_dir/(rid+'.json')
    tmp=cache_path.with_suffix('.tmp'); tmp.write_bytes(raw); os.replace(tmp,cache_path)
    cache_id='cache_'+content_sha[:32]; schema_digest=sha_bytes(canon({'fields':fields,'wrappers':wrappers,'top':type(data).__name__}).encode())
    c=con(sidecar,True)
    c.execute('INSERT OR IGNORE INTO api_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,run_id,dataset,'/beta/live/'+path,canon(params),now(),status,latency,classification,content_sha,str(cache_path),schema_digest))
    c.execute('INSERT OR IGNORE INTO api_cache_manifest VALUES(?,?,?,?,?,?,?)',(cache_id,rid,str(cache_path),content_sha,len(raw),now(),1))
    c.commit(); c.close(); record_endpoint(sidecar,run_id,dataset,path,classification,status,latency,fields,wrappers,len(records))
    return {'dataset':dataset,'path':'/beta/live/'+path,'query':params,'classification':classification,'http_status':status,'latency_ms':latency,'top_level_type':type(data).__name__,'wrapper_keys':wrappers,'field_names':fields,'row_count':len(records),'cache_id':cache_id,'records':records[:100]}

def acquire(sidecar:str, run_id:str, root:str, *, entitlement_recheck=True)->dict:
    key=read_key(); out=[]
    for dataset,path in ENABLED.items():
        rec=request_endpoint(sidecar,run_id,root,key,dataset,path,{})
        out.append({k:v for k,v in rec.items() if k!='records'})
        if rec['classification']=='ENTITLED' and rec['records']:
            normalize_events(sidecar,run_id,dataset,rec['records'],rec['cache_id'])
    if entitlement_recheck:
        for dataset,path in DISABLED.items():
            rec=request_endpoint(sidecar,run_id,root,key,dataset,path,{})
            out.append({k:v for k,v in rec.items() if k!='records'})
    return {'requests':out}

def public_availability(record:dict)->tuple[str|None,str|None,str|None]:
    av=None; field=None
    for f in AVAIL_FIELDS:
        if record.get(f): av=parse_dt(record.get(f)); field=f; break
    tx=None
    for f in TX_FIELDS:
        if record.get(f): tx=parse_dt(record.get(f)); break
    return (av.isoformat().replace('+00:00','Z') if av else None, field, tx.isoformat().replace('+00:00','Z') if tx else None)

def raw_event_id(dataset, record):
    parts=[dataset]
    for f in ID_FIELDS:
        if record.get(f): parts.append(str(record.get(f)))
    if len(parts)==1: parts.append(sha_bytes(canon(record).encode())[:24])
    return '|'.join(parts)

def normalize_events(sidecar:str, run_id:str, dataset:str, records:list[dict], cache_id:str|None, *, asof:str|None=None)->dict:
    asof_dt=parse_dt(asof) or dt.datetime.now(dt.timezone.utc); c=con(sidecar,True); inserted=0; excluded=0
    for rec in records:
        ticker=str(rec.get('Ticker') or rec.get('ticker') or '').upper() or None
        av,field,tx=public_availability(rec); reason=None; ex=0
        if not av: reason='no_public_availability_date'; ex=1
        av_dt=parse_dt(av)
        if av_dt and av_dt>asof_dt: reason='future_availability'; ex=1
        if av_dt and (asof_dt-av_dt).days>90: reason='stale_gt_90d'; ex=1
        uid='ev_'+sha_bytes(canon({'dataset':dataset,'raw':raw_event_id(dataset,rec),'availability':av}).encode())[:32]
        pol=1.0 if dataset in ('congress','government_contracts','lobbying') else 0.0
        c.execute('INSERT OR IGNORE INTO evidence_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,run_id,dataset,ticker,raw_event_id(dataset,rec),av,field,tx,1 if tx else 0,sha_bytes(canon(rec).encode()),cache_id,pol,ex,reason,'LIVE_FORWARD',now()))
        inserted+=1; excluded+=ex
    c.commit(); c.close(); return {'records':len(records),'inserted_or_seen':inserted,'excluded':excluded}

def score(sidecar:str, run_id:str)->dict:
    c=con(sidecar,True); cands=c.execute('SELECT candidate_id,ticker,signal_timestamp FROM candidates WHERE run_id=?',(run_id,)).fetchall(); scored=0
    examples=[]
    for cid,ticker,sig_ts in cands:
        sig=parse_dt(sig_ts); evs=c.execute('SELECT event_uid,dataset,availability_ts,excluded,excluded_reason,polarity FROM evidence_events WHERE run_id=? AND (ticker=? OR ticker IS NULL)',(run_id,ticker)).fetchall()
        contrib_by={}; contributing=[]; excluded=[]; signs=[]
        for uid,dataset,av,ex,reason,pol in evs:
            avdt=parse_dt(av)
            if ex or not avdt or not sig or avdt>sig:
                excluded.append({'event_uid':uid,'dataset':dataset,'reason':reason or 'not_available_as_of_signal'}); continue
            age=(sig-avdt).days
            if age>90: excluded.append({'event_uid':uid,'dataset':dataset,'reason':'stale_gt_90d'}); continue
            if dataset=='off_exchange': excluded.append({'event_uid':uid,'dataset':dataset,'reason':'exploratory_off_exchange_excluded_from_primary'}); continue
            w=1.0 if age<=30 else 0.5; val=max(-1.5,min(1.5,float(pol)*w)); contrib_by[dataset]=contrib_by.get(dataset,0)+val; contributing.append({'event_uid':uid,'dataset':dataset,'contribution':val,'freshness_weight':w,'publication_ts':av,'age_days':age}); signs.append(1 if val>0 else -1 if val<0 else 0)
        for k,v in list(contrib_by.items()): contrib_by[k]=max(-1.5,min(1.5,v))
        total=sum(contrib_by.values())
        if any(s>0 for s in signs) and any(s<0 for s in signs): total-=0.5; contrib_by['conflict_penalty']=-0.5
        total=max(-5,min(8,total)); bucket='STRONG_SUPPORT' if total>=5 else 'SUPPORT' if total>=2 else 'STRONG_CONTRADICTION' if total<=-5 else 'CONTRADICTS' if total<=-2 else 'NEUTRAL'
        inp=sha_bytes(canon({'cid':cid,'contrib':contributing,'excluded':excluded,'version':VERSION}).encode()); sid='score_'+sha_bytes((cid+inp).encode())[:32]
        c.execute('INSERT OR REPLACE INTO shadow_scores VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,run_id,total,bucket,canon(contrib_by),canon(contributing),canon(excluded),VERSION,inp,'LIVE_FORWARD',now()))
        scored+=1
        if len(examples)<5: examples.append({'ticker':ticker,'total_score':total,'bucket':bucket,'dataset_contrib':contrib_by,'contributing_events':contributing,'excluded_events':excluded[:5]})
    c.commit(); c.close(); return {'scored':scored,'examples':examples}

def completed_sessions_between(start:dt.date, end:dt.date)->int:
    d=start; n=0
    while d<end:
        d+=dt.timedelta(days=1)
        if d.weekday()<5: n+=1
    return n

def settle(sidecar:str, run_id:str, price_provider:Callable[[str,dt.date],dict|None]|None=None, *, asof_date:dt.date|None=None)->dict:
    asof_date=asof_date or dt.datetime.now(ET).date(); c=con(sidecar,True); rows=c.execute('SELECT candidate_id,ticker,signal_timestamp,entry,stop FROM candidates').fetchall(); attempted=0; settled=0; pending=0
    for cid,ticker,ts,entry,stop in rows:
        sig=parse_dt(ts); sig_date=(sig.astimezone(ET).date() if sig else asof_date)
        for h in (5,10,20):
            sid='settle_'+sha_bytes(f'{cid}|{h}'.encode())[:32]
            sessions=completed_sessions_between(sig_date,asof_date)
            if sessions<h or price_provider is None:
                c.execute('INSERT OR IGNORE INTO forward_returns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,h,'PENDING',entry,None,None,None,None,None,None,5.0,'signal-only; no broker fill claim','LIVE_FORWARD')); pending+=1; attempted+=1; continue
            px=price_provider(ticker, asof_date)
            if not px:
                c.execute('INSERT OR IGNORE INTO forward_returns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,h,'PENDING',entry,None,None,None,None,None,None,5.0,'signal-only; no broker fill claim','LIVE_FORWARD')); pending+=1; attempted+=1; continue
            price=float(px['close']); ret=(price-float(entry))/float(entry)*100 if entry else None; risk=(float(entry)-float(stop)) if entry and stop else None; r_mult=((price-float(entry))/risk) if risk and risk>0 else None
            c.execute('INSERT OR REPLACE INTO forward_returns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,cid,h,'SETTLED',entry,price,ret,r_mult,px.get('source','approved_price_provider'),asof_date.isoformat(),px.get('timestamp',now()),5.0,'signal-only close-to-close; no broker fill claim','LIVE_FORWARD')); settled+=1; attempted+=1
    c.commit(); c.close(); return {'attempted':attempted,'settled':settled,'pending':pending,'horizons':[5,10,20]}

def weekly(sidecar:str, run_id:str, root:str)->dict:
    paths=root_paths(root); paths['reports'].mkdir(parents=True,exist_ok=True); c=con(sidecar,False)
    rows=c.execute('SELECT horizon_sessions,status,return_pct,return_R FROM forward_returns').fetchall(); scores=c.execute('SELECT bucket,total_score FROM shadow_scores').fetchall(); ent=c.execute('SELECT dataset,classification,http_status FROM endpoint_entitlements ORDER BY dataset').fetchall(); c.close()
    settled=[r for r in rows if r[1]=='SETTLED']; pending=[r for r in rows if r[1]=='PENDING']
    gates={'min_50_settled_broad':len(settled)>=50,'min_30_bucket':False,'min_10d_20d':bool(any(r[0]==10 and r[1]=='SETTLED' for r in rows) and any(r[0]==20 and r[1]=='SETTLED' for r in rows))}
    claims_allowed=all(gates.values())
    metrics={'metric_class':'LIVE_FORWARD','sample_size':len(scores),'settled_count':len(settled),'pending_count':len(pending),'average_forward_return':mean([r[2] for r in settled]) if settled and claims_allowed else None,'median_forward_return':median([r[2] for r in settled]) if settled and claims_allowed else None,'hit_rate':(sum(1 for r in settled if r[2] and r[2]>0)/len(settled)) if settled and claims_allowed else None,'false_BUY_reduction':'INSUFFICIENT_EVIDENCE','missed_winner_rate':'INSUFFICIENT_EVIDENCE','average_R':mean([r[3] for r in settled if r[3] is not None]) if settled and claims_allowed else None,'score_bucket_counts':{},'endpoint_status':ent,'research_gates':gates,'performance_conclusion':'INSUFFICIENT_EVIDENCE','strategy_recommendation':'NO_RECOMMENDATION'}
    for b,_ in scores: metrics['score_bucket_counts'][b]=metrics['score_bucket_counts'].get(b,0)+1
    base=paths['reports']/(dt.date.today().isoformat()+'_quiver_weekly')
    jp=base.with_suffix('.json'); mp=base.with_suffix('.md'); cp=base.with_suffix('.csv')
    jp.write_text(json.dumps(metrics,indent=2,sort_keys=True,default=str)+'\n')
    mp.write_text('# Quiver Weekly Observation Report\n\nmetric_class: LIVE_FORWARD\n\nperformance_conclusion: INSUFFICIENT_EVIDENCE\n\nstrategy_recommendation: NO_RECOMMENDATION\n\nsettled_count: %s\npending_count: %s\n' % (len(settled),len(pending)))
    with cp.open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['metric','value'])
        for k,v in metrics.items(): w.writerow([k,canon(v) if isinstance(v,(dict,list,tuple)) else v])
    c=con(sidecar,True); mid='weekly_'+sha_bytes((run_id+str(jp)).encode())[:32]; c.execute('INSERT OR REPLACE INTO weekly_metrics VALUES(?,?,?,?,?,?,?,?)',(mid,run_id,dt.date.today().isoformat(),str(jp),str(mp),str(cp),canon(metrics),'LIVE_FORWARD')); c.commit(); c.close()
    return {'json':str(jp),'markdown':str(mp),'csv':str(cp),'metrics':metrics}

def health(sidecar:str, atlas_db:str, root:str)->dict:
    c=con(sidecar,False)
    try:
        quick=c.execute('PRAGMA quick_check').fetchone()[0]; integ=c.execute('PRAGMA integrity_check').fetchone()[0]; fk=len(c.execute('PRAGMA foreign_key_check').fetchall())
        fixture_rows=sum(c.execute("SELECT COUNT(*) FROM candidates WHERE metric_class='TEST_FIXTURE'").fetchone()) if False else c.execute("SELECT COUNT(*) FROM candidates WHERE metric_class='TEST_FIXTURE'").fetchone()[0] + c.execute("SELECT COUNT(*) FROM evidence_events WHERE metric_class='TEST_FIXTURE'").fetchone()[0]
        test_runs=c.execute("SELECT COUNT(*) FROM runs WHERE run_id LIKE 'test_%' OR notes LIKE '%fixture%'").fetchone()[0]
        last_cap=c.execute("SELECT max(completed_at) FROM runs WHERE run_type='capture' AND status='PASS'").fetchone()[0]
        last_settle=c.execute("SELECT max(completed_at) FROM runs WHERE run_type='settle' AND status='PASS'").fetchone()[0]
        cache_bad=0
        for path,content_sha in c.execute('SELECT cache_path,content_sha256 FROM api_cache_manifest'):
            if not Path(path).exists() or sha_file(path)!=content_sha: cache_bad+=1
        ent=[dict(dataset=a,classification=b,http_status=cstatus) for a,b,cstatus in c.execute('SELECT dataset,classification,http_status FROM endpoint_entitlements')]
        return {'status':'PASS' if quick==integ=='ok' and fk==0 and fixture_rows==0 and test_runs==0 and cache_bad==0 else 'FAIL','quick_check':quick,'integrity_check':integ,'fk_rows':fk,'last_successful_capture':last_cap,'last_successful_settlement':last_settle,'atlas_db_sha':sha_file(atlas_db),'fixture_rows':fixture_rows,'test_run_ids':test_runs,'cache_manifest_bad':cache_bad,'entitlements':ent,'secret_leakage':'NOT_SCANNED_BY_HEALTH_RUNTIME'}
    finally: c.close()

def backup_sidecar(sidecar:str, root:str)->dict:
    paths=root_paths(root); paths['backups'].mkdir(parents=True,exist_ok=True); dest=paths['backups']/('quiver_sidecar_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sqlite')
    src=sqlite3.connect(f'file:{Path(sidecar).resolve()}?mode=ro',uri=True); dst=sqlite3.connect(dest)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    h=health(str(dest),ATLAS_DB_DEFAULT,root); return {'path':str(dest),'sha256':sha_file(dest),'health':h}

def active_busy()->list[str]:
    active=[]
    try:
        txt=subprocess.run(['/bin/launchctl','list'],capture_output=True,text=True,timeout=5).stdout
        for line in txt.splitlines():
            p=line.split('\t')
            if len(p)>=3 and p[2] in BUSY_LABELS and p[0]!='-': active.append('label:'+p[2])
    except Exception: pass
    try:
        txt=subprocess.run(['/bin/ps','-axo','pid=,command='],capture_output=True,text=True,timeout=5).stdout; me=os.getpid()
        for line in txt.splitlines():
            bits=line.strip().split(None,1)
            if len(bits)==2 and int(bits[0])!=me and any(n in bits[1] for n in BUSY_PROCESS_NAMES): active.append('process:'+bits[0])
    except Exception: pass
    return active

def main(argv=None)->int:
    ap=argparse.ArgumentParser(); ap.add_argument('command',choices=['init','capture','settle','weekly','health','backup']); ap.add_argument('--root',default=ROOT_DEFAULT); ap.add_argument('--db',default=None); ap.add_argument('--atlas-db',default=ATLAS_DB_DEFAULT); ap.add_argument('--env',default=ATLAS_ENV_DEFAULT); ap.add_argument('--limit',type=int,default=500); ap.add_argument('--skip-busy-check',action='store_true')
    a=ap.parse_args(argv); paths=root_paths(a.root); db=str(a.db or paths['db']); ensure_dirs(a.root)
    if a.command=='init': init_db(db); print(json.dumps(initialize_baseline(db,a.atlas_db),sort_keys=True)); return 0
    if not Path(db).exists(): raise SystemExit('SIDECAR_DB_MISSING_RUN_INIT_FIRST')
    if not a.skip_busy_check and a.command in ('capture','settle') and active_busy(): print(json.dumps({'status':'SKIP_BUSY','active':active_busy()},sort_keys=True)); return 0
    rid=start_run(db,a.command,a.atlas_db)
    try:
        if a.command=='capture': res={'capture':capture_candidates(db,rid,a.atlas_db,limit=a.limit),'api':acquire(db,rid,a.root),'score':score(db,rid)}
        elif a.command=='settle': res=settle(db,rid)
        elif a.command=='weekly': res=weekly(db,rid,a.root)
        elif a.command=='health': res=health(db,a.atlas_db,a.root)
        elif a.command=='backup': res=backup_sidecar(db,a.root)
        else: res={}
        finish_run(db,rid,'PASS',a.atlas_db); print(json.dumps({'status':'PASS','run_id':rid,'result':res},sort_keys=True,default=str)); return 0
    except Exception as e:
        finish_run(db,rid,'FAIL',a.atlas_db,repr(e)); raise
if __name__=='__main__': raise SystemExit(main())
