#!/usr/bin/env python3
"""Acquire real completed-session data for Daily Holdings Re-Underwriting v1.

Read-only acquisition: atlas.db mode=ro plus Massive/Benzinga/Perme inputs.
No atlas.db writes, no broker actions, no Telegram.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sqlite3, time, urllib.parse, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ET=ZoneInfo('America/New_York')
DEFAULT_DB='/Users/yasser/scripts/atlas.db'
DEFAULT_ENV='/Users/yasser/.hermes/profiles/atlas/.env'
MASSIVE_BASE_DEFAULT='https://api.massive.com'
SECTOR_ETF={'ABNB':'XLY','BAC':'XLF','LASR':'XLK','PENG':'XLY','SYNA':'XLK','WDFC':'XLB'}

def sha_obj(o): return hashlib.sha256(json.dumps(o, sort_keys=True, default=str, separators=(',',':')).encode()).hexdigest()

def parse_env_names(path=DEFAULT_ENV, names=('MASSIVE_API_KEY','POLYGON_API_KEY','BENZINGA_API_KEY','MASSIVE_BASE')):
    out={}
    p=Path(path)
    if not p.exists(): return out
    for line in p.read_text(errors='replace').splitlines():
        s=line.strip()
        if not s or s.startswith('#') or '=' not in s: continue
        k,v=s.split('=',1); k=k.strip(); v=v.strip().strip('"').strip("'")
        if k in names and k not in out: out[k]=v
    return out

def cfg():
    e=parse_env_names();
    return {'massive_key': os.environ.get('MASSIVE_API_KEY') or os.environ.get('POLYGON_API_KEY') or e.get('MASSIVE_API_KEY') or e.get('POLYGON_API_KEY'),
            'benzinga_key': os.environ.get('BENZINGA_API_KEY') or e.get('BENZINGA_API_KEY'),
            'massive_base': os.environ.get('MASSIVE_BASE') or e.get('MASSIVE_BASE') or MASSIVE_BASE_DEFAULT}

def conn_ro(db=DEFAULT_DB):
    c=sqlite3.connect('file:'+str(Path(db).resolve())+'?mode=ro&immutable=1',uri=True); c.row_factory=sqlite3.Row; c.execute('PRAGMA query_only=ON'); return c

def open_trades(db=DEFAULT_DB):
    c=conn_ro(db)
    try: return [dict(r) for r in c.execute("select * from trades where status='OPEN' order by ticker,id").fetchall()]
    finally: c.close()

def latest_completed_session(today=None):
    # Good-enough NYSE weekday fallback; runner/tests can replace with atlas_time if needed.
    d=(today or dt.datetime.now(ET).date())
    # if weekend, walk back; if before 18:00 ET, previous business day
    if d.weekday()<5 and dt.datetime.now(ET).time() >= dt.time(18,0): pass
    else: d=d-dt.timedelta(days=1)
    while d.weekday()>=5: d-=dt.timedelta(days=1)
    return d.isoformat()

def fetch_json(url, params, timeout=20):
    full=url+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(full, headers={'Accept':'application/json','User-Agent':'AtlasOps/1.0'})
    t0=time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data=json.loads(r.read().decode('utf-8','replace'))
        return data, {'http_status':r.status,'latency_ms':round((time.time()-t0)*1000), 'field_names':list(data.keys()) if isinstance(data,dict) else [], 'row_count':len(data.get('results') or []) if isinstance(data,dict) else (len(data) if isinstance(data,list) else None)}

def massive_aggs(ticker, start, end, key, base):
    url=f"{base.rstrip('/')}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    data,meta=fetch_json(url, {'apiKey':key,'adjusted':'true','sort':'asc','limit':50000})
    rows=[]
    for r in data.get('results') or []:
        ts=dt.datetime.fromtimestamp((r.get('t') or 0)/1000, tz=dt.timezone.utc).astimezone(ET).date().isoformat()
        rows.append({'date':ts,'open':r.get('o'),'high':r.get('h'),'low':r.get('l'),'close':r.get('c'),'volume':r.get('v'),'vwap':r.get('vw'),'transactions':r.get('n')})
    meta.update({'provider':'Massive','endpoint_category':'daily_aggs','ticker':ticker,'start':start,'end':end,'acquired_at':dt.datetime.utcnow().isoformat()+'Z','freshness':'FRESH' if rows else 'EMPTY'})
    meta['provenance_digest']=sha_obj({'ticker':ticker,'rows':rows,'meta':{k:v for k,v in meta.items() if k!='provenance_digest'}})
    return rows,meta

def benzinga_news(ticker, key, base):
    if not key: return {'status':'MISSING_KEY','items':[],'freshness':'UNAVAILABLE'}
    try:
        data,meta=fetch_json(f"{base.rstrip('/')}/benzinga/v2/news", {'apiKey':key,'tickers':ticker,'limit':10}, timeout=12)
        rows=data.get('results') or data.get('data') or [] if isinstance(data,dict) else []
        return {'status':'OK','items':rows[:5],'meta':meta,'freshness':'FRESH' if rows else 'EMPTY_RESPONSE'}
    except Exception as e: return {'status':'ERROR','error':type(e).__name__,'items':[],'freshness':'UNAVAILABLE'}

def load_json_if_fresh(path, max_age_hours=30):
    p=Path(path)
    if not p.exists(): return {'status':'MISSING','freshness':'UNAVAILABLE'}
    try: obj=json.loads(p.read_text(errors='replace'))
    except Exception as e: return {'status':'INVALID','error':type(e).__name__,'freshness':'UNAVAILABLE'}
    ttl_minutes=obj.get('ttl_minutes')
    generated=obj.get('generated_at') or obj.get('created_at') or obj.get('generated_at_et')
    if generated:
        try:
            g=str(generated).replace('Z','+00:00')
            ts=dt.datetime.fromisoformat(g)
            if ts.tzinfo is None: ts=ts.replace(tzinfo=dt.timezone.utc)
            age=(dt.datetime.now(dt.timezone.utc)-ts.astimezone(dt.timezone.utc)).total_seconds()/3600
        except Exception:
            age=(time.time()-p.stat().st_mtime)/3600
    else:
        age=(time.time()-p.stat().st_mtime)/3600
    allowed=(float(ttl_minutes)/60.0) if ttl_minutes else max_age_hours
    return {'status':'OK','freshness':'FRESH' if age<=allowed else 'STALE','age_hours':round(age,2),'ttl_minutes':ttl_minutes,'payload':obj,'path':str(p)}

def acquire(db=DEFAULT_DB, out=None):
    c=cfg(); key=c['massive_key']
    if not key: raise SystemExit('BLOCKED: MASSIVE_API_KEY/POLYGON_API_KEY missing')
    trades=open_trades(db); session=latest_completed_session()
    end_date=dt.date.fromisoformat(session)
    start=(end_date-dt.timedelta(days=430)).isoformat()
    tickers=sorted({str(t['ticker']).upper() for t in trades})
    all_tickers=sorted(set(tickers+['SPY']+[SECTOR_ETF.get(t,t) for t in tickers if SECTOR_ETF.get(t)]))
    bars={}; meta={}
    for t in all_tickers:
        rows,m=massive_aggs(t,start,session,key,c['massive_base']); bars[t]=rows; meta[t]=m
    perme=load_json_if_fresh('/Users/yasser/atlas_inbox/latest_context.json')
    packet={'packet_version':'holdings_reunderwrite_acquisition.v1','created_at':dt.datetime.utcnow().isoformat()+'Z','latest_completed_session':session,'market_session':session,'trades':trades,'tickers':tickers,'bars':bars,'provider_meta':meta,'sector_map':{t:SECTOR_ETF.get(t) for t in tickers},'external_context':{'perme':perme},'quiver_raw_evidence_digest':None,'provider':'Massive','authority':'READ_ONLY'}
    # add news separately, no secrets exposed
    packet['external_context']['benzinga_news']={t:benzinga_news(t,c.get('benzinga_key'),c['massive_base']) for t in tickers}
    packet['input_digest']=sha_obj(packet)
    if out:
        p=Path(out); p.parent.mkdir(parents=True, exist_ok=True); tmp=p.with_suffix(p.suffix+'.tmp'); tmp.write_text(json.dumps(packet, indent=2, sort_keys=True, default=str)+'\n'); os.replace(tmp,p)
    return packet

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default=DEFAULT_DB); ap.add_argument('--out',required=True)
    args=ap.parse_args(); pkt=acquire(args.db,args.out); print(json.dumps({'status':'PASS','tickers':pkt['tickers'],'session':pkt['latest_completed_session'],'input_digest':pkt['input_digest']},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
