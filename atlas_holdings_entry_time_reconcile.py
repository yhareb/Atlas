#!/usr/bin/env python3
"""Entry-time reconciliation for daily holdings re-underwriting.

Builds authoritative post-entry bar chronology so MFE/MAE/high-water/giveback
never use pre-fill prices. Read-only: no atlas.db writes, no broker, no Telegram.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, sqlite3, urllib.parse, urllib.request, time
from pathlib import Path
from zoneinfo import ZoneInfo

ET=ZoneInfo('America/New_York')
HOST=dt.datetime.now().astimezone().tzinfo
DEFAULT_DB='/Users/yasser/scripts/atlas.db'
DEFAULT_ENV='/Users/yasser/.hermes/profiles/atlas/.env'
MASSIVE_BASE_DEFAULT='https://api.massive.com'

def sha_obj(o): return hashlib.sha256(json.dumps(o,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()

def parse_env_names(path=DEFAULT_ENV):
    out={}; p=Path(path)
    if not p.exists(): return out
    for line in p.read_text(errors='replace').splitlines():
        s=line.strip()
        if not s or s.startswith('#') or '=' not in s: continue
        k,v=s.split('=',1); k=k.strip(); v=v.strip().strip('"').strip("'")
        if k in {'MASSIVE_API_KEY','POLYGON_API_KEY','MASSIVE_BASE'} and k not in out: out[k]=v
    return out

def cfg():
    e=parse_env_names(); return {'key':os.environ.get('MASSIVE_API_KEY') or os.environ.get('POLYGON_API_KEY') or e.get('MASSIVE_API_KEY') or e.get('POLYGON_API_KEY'), 'base':os.environ.get('MASSIVE_BASE') or e.get('MASSIVE_BASE') or MASSIVE_BASE_DEFAULT}

def conn_ro(db=DEFAULT_DB):
    c=sqlite3.connect('file:'+str(Path(db).resolve())+'?mode=ro&immutable=1',uri=True); c.row_factory=sqlite3.Row; c.execute('PRAGMA query_only=ON'); return c

def parse_db_ts_assume_utc(s):
    raw=str(s or '').replace('T',' ').replace('Z','').strip()
    if not raw: return None
    # Atlas ledger/report timestamps are stored as UTC-naive strings; record assumption explicitly.
    try: d=dt.datetime.fromisoformat(raw)
    except Exception: d=dt.datetime.strptime(raw[:19],'%Y-%m-%d %H:%M:%S')
    if d.tzinfo is None: d=d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)

def tz_record(ts_utc):
    return {'utc':ts_utc.isoformat(), 'america_new_york':ts_utc.astimezone(ET).isoformat(), 'host_timezone':ts_utc.astimezone(HOST).isoformat(), 'source_timezone_assumption':'DB naive timestamps are UTC based on Atlas ledger/journal convention and UTC notes'}

def fetch_json(url, params, timeout=20):
    full=url+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(full,headers={'Accept':'application/json','User-Agent':'AtlasOps/entry-recon'})
    t0=time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data=json.loads(r.read().decode('utf-8','replace'))
        return data, {'http_status':r.status,'latency_ms':round((time.time()-t0)*1000),'field_names':list(data.keys()) if isinstance(data,dict) else [],'row_count':len(data.get('results') or []) if isinstance(data,dict) else None}

def massive_aggs(ticker,start,end,mult='1',span='day', key=None, base=None):
    c=cfg(); key=key or c['key']; base=base or c['base']
    if not key: raise RuntimeError('MASSIVE_API_KEY/POLYGON_API_KEY missing')
    url=f"{base.rstrip('/')}/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{start}/{end}"
    data,meta=fetch_json(url, {'apiKey':key,'adjusted':'true','sort':'asc','limit':50000})
    rows=[]
    for r in data.get('results') or []:
        ts_utc=dt.datetime.fromtimestamp((r.get('t') or 0)/1000,tz=dt.timezone.utc)
        row={'timestamp_utc':ts_utc.isoformat(),'timestamp_et':ts_utc.astimezone(ET).isoformat(),'date':ts_utc.astimezone(ET).date().isoformat(),'open':r.get('o'),'high':r.get('h'),'low':r.get('l'),'close':r.get('c'),'volume':r.get('v'),'vwap':r.get('vw'),'transactions':r.get('n')}
        rows.append(row)
    meta.update({'provider':'Massive','endpoint_category':f'{span}_aggs','ticker':ticker,'start':start,'end':end,'acquired_at':dt.datetime.utcnow().isoformat()+'Z','freshness':'FRESH' if rows else 'EMPTY','provenance_digest':sha_obj(rows)})
    return rows,meta

def load_position_lot(conn, trade_id):
    try:
        r=conn.execute('select * from position_lots where legacy_trades_id=? order by id desc limit 1',(trade_id,)).fetchone()
        return dict(r) if r else None
    except Exception: return None

def broker_fill_event(conn, trade_id):
    r=conn.execute("select * from portfolio_event_journal where legacy_trades_id=? and event_type='BROKER_BUY_FILLED' order by occurred_at desc limit 1",(trade_id,)).fetchone()
    return dict(r) if r else None

def nearest_signal(conn,ticker,entry_ts):
    r=conn.execute('select * from signals where ticker=? and timestamp<=? order by timestamp desc,id desc limit 1',(ticker,entry_ts.strftime('%Y-%m-%d %H:%M:%S'))).fetchone()
    return dict(r) if r else None

def entry_source(conn, trade):
    trade_id=trade['id']; ticker=trade['ticker']
    ev=broker_fill_event(conn, trade_id); lot=load_position_lot(conn, trade_id)
    choices=[]
    if ev:
        payload=json.loads(ev.get('payload_json') or '{}')
        choices.append({'rank':1,'source':'broker_confirmed_fill_event','timestamp_raw':ev.get('occurred_at') or ev.get('effective_at'),'price':float(payload.get('entry_price') or trade['entry_price']),'detail':ev})
    if lot:
        price=float(lot.get('entry_price_decimal_text') or (lot.get('entry_price_micros') or 0)/1_000_000)
        choices.append({'rank':2,'source':'position_lot','timestamp_raw':lot.get('created_at') or trade.get('entry_at'),'price':price,'detail':lot})
    choices.append({'rank':3,'source':'canonical_trade_row','timestamp_raw':trade.get('entry_at'),'price':float(trade.get('entry_price')),'detail':trade})
    chosen=sorted(choices,key=lambda x:x['rank'])[0]
    ts=parse_db_ts_assume_utc(chosen['timestamp_raw'])
    sig=nearest_signal(conn,ticker,ts)
    material_conflicts=[]
    trade_ts=parse_db_ts_assume_utc(trade.get('entry_at'))
    if abs((ts-trade_ts).total_seconds())>900:
        material_conflicts.append({'type':'timestamp','chosen':chosen['timestamp_raw'],'trade_entry_at':trade.get('entry_at'),'delta_seconds':(ts-trade_ts).total_seconds()})
    if abs(float(chosen['price'])-float(trade['entry_price']))>0.02:
        material_conflicts.append({'type':'price','chosen':chosen['price'],'trade_entry_price':trade['entry_price']})
    return {'ticker':ticker,'trade_id':trade_id,'chosen_source':chosen['source'],'fill_timestamp':tz_record(ts),'fill_timestamp_utc_obj':ts,'fill_price':chosen['price'],'all_sources':choices,'nearest_signal_supporting_context':sig,'material_conflicts':material_conflicts}

def post_entry_chronology(trade, entry, latest_session):
    ticker=trade['ticker']; fill_utc=entry['fill_timestamp_utc_obj']; fill_et=fill_utc.astimezone(ET); entry_day=fill_et.date().isoformat()
    daily_start=(fill_et.date()-dt.timedelta(days=430)).isoformat()
    daily,dm=massive_aggs(ticker,daily_start,latest_session,'1','day')
    intraday=[]; im={'freshness':'EMPTY'}
    try: intraday,im=massive_aggs(ticker,entry_day,entry_day,'1','minute')
    except Exception as e: im={'freshness':'UNAVAILABLE','error':type(e).__name__}
    used=[]; rejected=[]; entry_incomplete=False
    for b in intraday:
        ts=dt.datetime.fromisoformat(b['timestamp_utc'])
        if ts >= fill_utc: used.append(b)
        else: rejected.append(b)
    if not intraday: entry_incomplete=True
    # later daily full bars only strictly after entry day
    later=[b for b in daily if b['date']>entry_day and b['date']<=latest_session]
    bars=[]
    if used:
        bars.extend(used)
    bars.extend(later)
    if not bars:
        entry_incomplete=True
    highs=[float(b['high']) for b in bars if b.get('high') is not None]
    lows=[float(b['low']) for b in bars if b.get('low') is not None]
    closes=[float(b['close']) for b in bars if b.get('close') is not None]
    entry_price=float(entry['fill_price'])
    peak=max(highs) if highs else None; trough=min(lows) if lows else None; cur=closes[-1] if closes else None
    peak_gain=((peak-entry_price)/entry_price*100) if peak is not None else None
    mae=((trough-entry_price)/entry_price*100) if trough is not None else None
    current_gain=((cur-entry_price)/entry_price*100) if cur is not None else None
    profit_surrendered=(peak_gain-current_gain) if peak_gain is not None and current_gain is not None else None
    giveback=(profit_surrendered/peak_gain*100) if peak_gain and peak_gain>0 and profit_surrendered is not None else 0
    auth={'authoritative_peak_price':peak,'authoritative_peak_gain_pct':peak_gain,'authoritative_trough_price':trough,'mae_pct':mae,'current_close':cur,'current_gain_pct':current_gain,'profit_surrendered_pct_points':profit_surrendered,'giveback_pct':giveback,'entry_session_intraday_incomplete':entry_incomplete}
    return {'ticker':ticker,'trade_id':trade['id'],'entry_day':entry_day,'fill':entry['fill_timestamp'],'entry_session_intraday_bars_used':used,'entry_session_intraday_bars_rejected_pre_fill':rejected,'subsequent_daily_bars':later,'daily_provider_meta':dm,'intraday_provider_meta':im,'authoritative':auth}

def reconcile(db=DEFAULT_DB, latest_session=None, out=None):
    conn=conn_ro(db)
    try:
        trades=[dict(r) for r in conn.execute("select * from trades where status='OPEN' order by ticker,id").fetchall()]
        latest_session=latest_session or previous_session()
        entries=[]; chron=[]
        for tr in trades:
            es=entry_source(conn,tr); entries.append({k:v for k,v in es.items() if k!='fill_timestamp_utc_obj'}); chron.append(post_entry_chronology(tr,es,latest_session))
    finally: conn.close()
    packet={'packet_version':'entry_time_reconciliation.v1','created_at':dt.datetime.utcnow().isoformat()+'Z','latest_session':latest_session,'entry_sources':entries,'chronologies':chron,'authority':'READ_ONLY','input_digest':sha_obj({'entries':entries,'chron':chron})}
    if out:
        p=Path(out); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(packet,indent=2,sort_keys=True,default=str)+'\n')
    return packet

def previous_session():
    d=dt.datetime.now(ET).date()-dt.timedelta(days=1)
    while d.weekday()>=5: d-=dt.timedelta(days=1)
    return d.isoformat()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default=DEFAULT_DB); ap.add_argument('--latest-session'); ap.add_argument('--out',required=True)
    a=ap.parse_args(); pkt=reconcile(a.db,a.latest_session,a.out); print(json.dumps({'status':'PASS','tickers':[c['ticker'] for c in pkt['chronologies']],'input_digest':pkt['input_digest']},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
