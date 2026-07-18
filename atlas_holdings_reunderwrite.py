#!/usr/bin/env python3
"""Deterministic, advisory-only Daily Holdings Re-Evaluation core."""
from __future__ import annotations
import datetime as dt, hashlib, json, math, sqlite3
from pathlib import Path
from typing import Any

ACTIONS=("SELL NOW","EXIT REVIEW","TRIM REVIEW","HOLD TIGHT","HOLD","DATA INCOMPLETE")
POLICY_VERSION="daily_holdings_reunderwrite_v2.0.0"

def sha(obj:Any)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def num(v):
    try:
        x=float(v); return x if math.isfinite(x) and x>0 else None
    except Exception:return None
def ema(values,n):
    if not values:return None
    z=values[0]; a=2/(n+1)
    for v in values[1:]:z=a*v+(1-a)*z
    return z
def rsi(values,n=14):
    if len(values)<n+1:return None
    ds=[b-a for a,b in zip(values[-n-1:-1],values[-n:])]; g=sum(max(x,0) for x in ds)/n; l=sum(max(-x,0) for x in ds)/n
    return 100.0 if l==0 else 100-100/(1+g/l)
def atr(bars,n=14):
    if len(bars)<n+1:return None
    tr=[]
    for a,b in zip(bars[-n-1:-1],bars[-n:]):tr.append(max(float(b['high'])-float(b['low']),abs(float(b['high'])-float(a['close'])),abs(float(b['low'])-float(a['close']))))
    return sum(tr)/len(tr)
def connect_ro(path):
    c=sqlite3.connect("file:"+str(Path(path).resolve())+"?mode=ro&immutable=1",uri=True); c.row_factory=sqlite3.Row;c.execute("PRAGMA query_only=ON");return c
def open_trades(path):
    with connect_ro(path) as c:return [dict(r) for r in c.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY ticker,id")]
def normalize_bars(raw):
    out=[]
    for b in raw:
        date=str(b.get('session_date') or b.get('date') or '')
        vals={k:num(b.get(k)) for k in ('open','high','low','close','volume')}
        if date and all(vals[k] is not None for k in ('open','high','low','close')):
            out.append({'date':date,**vals,'provider_timestamp':b.get('provider_timestamp')})
    return sorted(out,key=lambda x:x['date'])

def evaluate(trade:dict,bars:list[dict],expected_session:str,source:str,daily_prior:dict|None=None,pp_prior:dict|None=None)->dict:
    t=str(trade.get('ticker') or '').upper(); entry=num(trade.get('entry_price')); stop=num(trade.get('stop_loss')); target=num(trade.get('target_price'))
    bars=normalize_bars(bars); last=bars[-1] if bars else None
    missing=[]
    for name,val,src in [('entry',entry,'canonical_db.trades.entry_price'),('stop',stop,'canonical_db.trades.stop_loss'),('target',target,'canonical_db.trades.target_price')]:
        if val is None:missing.append(f"{name}@{src}")
    if not last:missing.append(f"completed_session_ohlcv@{source}")
    elif last['date']!=expected_session:missing.append(f"authoritative_session@{source}:expected={expected_session},actual={last['date']}")
    if last and len(bars)<51:missing.append(f"indicator_history_51_sessions@{source}:actual={len(bars)}")
    action='DATA INCOMPLETE'; reason='missing required evidence: '+', '.join(missing) if missing else ''
    price=last['close'] if last else None; peak=max((b['high'] for b in bars if not trade.get('entry_at') or b['date']>=str(trade['entry_at'])[:10]),default=None)
    gain=((price-entry)/entry*100) if price and entry else None; peak_gain=((peak-entry)/entry*100) if peak and entry else None
    surrendered=max(0.0,(peak_gain or 0)-(gain or 0)) if peak_gain is not None and gain is not None else None
    stop_status='UNKNOWN'
    closes=[b['close'] for b in bars]
    indicators={'ema21':ema(closes,21),'ema50':ema(closes,50),'rsi14':rsi(closes),'atr14':atr(bars)}
    if not missing:
        # Completed-session low is authoritative stop-hit evidence and outranks close-derived rules.
        stop_hit=last['low']<=stop
        stop_status='BREACHED: authoritative completed-session low <= canonical DB stop' if stop_hit else 'NOT BREACHED: authoritative completed-session low > canonical DB stop'
        if stop_hit:action='SELL NOW';reason=f"verified stop hit: session low {last['low']:.4f} <= canonical stop {stop:.4f}"
        elif price<=stop:action='SELL NOW';reason=f"verified close {price:.4f} <= canonical stop {stop:.4f}"
        elif peak_gain is not None and peak_gain>=15 and surrendered/peak_gain>=.65:action='EXIT REVIEW';reason=f"severe giveback: surrendered {surrendered:.2f} points of {peak_gain:.2f}% peak gain"
        elif peak_gain is not None and peak_gain>=15 and surrendered/peak_gain>=.35:action='TRIM REVIEW';reason=f"profit giveback review: surrendered {surrendered:.2f} points of {peak_gain:.2f}% peak gain"
        elif price<indicators['ema21'] and indicators['ema21']<indicators['ema50']:action='HOLD TIGHT';reason='completed close below EMA21 with EMA21 below EMA50'
        else:action='HOLD';reason='canonical stop intact and deterministic completed-session deterioration thresholds not met'
    freshness='FRESH' if not missing else 'INCOMPLETE: '+', '.join(missing)
    return {'ticker':t,'trade_id':trade.get('id'),'authoritative_price':price,'session_date':last['date'] if last else None,'price_authority':source,'entry':entry,'current_gain_loss_pct':gain,'peak_price':peak,'peak_gain_pct':peak_gain,'surrendered_pct_points':surrendered,'stop':stop,'target':target,'stop_status':stop_status,'daily_result':action,'pp_result':(pp_prior or {}).get('action','NOT AVAILABLE'),'final_action':action,'deterministic_reason':reason,'exact_recheck':'After the next completed NYSE session at/after 16:15 ET; immediately on newly authoritative stop-hit evidence.','freshness':freshness,'broker_confirmation':'NOT CONFIRMED — advisory only; no broker query or action','indicators':indicators,'optional_context':{'catalyst':'NOT PROVIDED — optional, non-authoritative','prior_daily_result':(daily_prior or {}).get('action')},'broker_authority':'NO','automatic_trade_closure':'NO'}

def build_packet(db,evidence,expected_session,macro_gate=None,macro_path=None):
    ev=json.loads(Path(evidence).read_text()); provider=ev.get('provider') or {}; trades=open_trades(db); positions=[]
    from atlas_profit_protection_v2 import evaluate as pp_evaluate
    for tr in trades:
        t=str(tr['ticker']).upper(); src=provider.get(t) or {}; raw=src.get('bars') or []
        row=evaluate(tr,raw,expected_session,f"{src.get('provider') or 'UNKNOWN'}:{src.get('dataset') or 'UNKNOWN'}")
        pp=pp_evaluate(ticker=t,entry=tr.get('entry_price'),old_stop=tr.get('stop_loss'),old_target=tr.get('target_price'),bars=raw,entry_at=tr.get('entry_at'),captured_at=ev.get('captured_at'),provider_name=f"{src.get('provider')}:{src.get('dataset')}")
        row['pp_result']=pp.action
        if str(pp.data_freshness).startswith(('STALE','INCOMPLETE')):
            row['final_action']='DATA INCOMPLETE';row['deterministic_reason']='missing required evidence: profit_protection@atlas_profit_protection_v2:'+str(pp.data_freshness)
        elif row['final_action']!='SELL NOW' and pp.action=='EXIT REVIEW':
            row['final_action']='EXIT REVIEW';row['deterministic_reason']='profit protection EXIT REVIEW: '+pp.why
        elif row['final_action'] not in ('SELL NOW','EXIT REVIEW','TRIM REVIEW') and pp.action=='TRIM REVIEW':
            row['final_action']='TRIM REVIEW';row['deterministic_reason']='profit protection TRIM REVIEW: '+pp.why
        elif row['final_action']=='HOLD' and pp.action in ('TIGHTEN','PROTECT PROFIT'):
            row['final_action']='HOLD TIGHT';row['deterministic_reason']='profit protection '+pp.action+': '+pp.why
        status=getattr(macro_gate,'status','MISSING'); digest=getattr(macro_gate,'input_sha256',None)
        row.update(macro_context_status=status,macro_context_sha256=digest,macro_context_path=macro_path)
        if status!='ACCEPTED' and row['final_action']!='SELL NOW':
            if status not in ('MISSING','STALE','INVALID'):status='INVALID'
            row['final_action']='DATA INCOMPLETE';row['deterministic_reason']='PERME_CONTEXT_'+status
        elif status=='ACCEPTED' and getattr(macro_gate,'context',{}).get('perme_regime')=='RISK_OFF' and row['final_action'] not in ('SELL NOW','EXIT REVIEW','TRIM REVIEW'):
            row['final_action']='EXIT REVIEW';row['deterministic_reason']='PERME_RISK_OFF_ADVISORY'
        positions.append(row)
    core={'packet_version':'holdings_reunderwrite.v2','policy_version':POLICY_VERSION,'run_date':expected_session,'positions':positions,'macro_context':{'status':getattr(macro_gate,'status','MISSING'),'sha256':getattr(macro_gate,'input_sha256',None),'path':macro_path},'authority':{'trading':'ADVISORY_ONLY','broker':'NO','mutation':'NO','stop_mutation':'NO'}}
    core['input_digest']=sha({'policy':POLICY_VERSION,'session':expected_session,'positions':positions,'macro_context':core['macro_context']});return core

def stable_actions(packet):
    return json.dumps([{'ticker':p['ticker'],'action':p['final_action'],'reason':p['deterministic_reason']} for p in packet['positions']],sort_keys=True,separators=(',',':'))
