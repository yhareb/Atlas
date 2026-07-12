#!/usr/bin/env python3
"""Final runner for Daily Holdings Re-Underwriting.
Uses live acquisition plus corrected post-entry chronology. Advisory-only.
"""
from __future__ import annotations
import argparse, datetime as dt, fcntl, json, os, signal, sqlite3, subprocess, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo
from atlas_holdings_reunderwrite_acquire import acquire
from atlas_holdings_entry_time_reconcile import reconcile
from atlas_holdings_reunderwrite import evaluate_holding, packet_from_snapshots, write_outputs, persist_packet

ET=ZoneInfo('America/New_York')
DEFAULT_LOCK='/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/run/daily_holdings_reunderwrite.lock'
DEFAULT_ROOT='/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite'
DEFAULT_OUT='/Users/yasser/atlas_inbox/holdings_reunderwrite'
DEFAULT_SIDECAR=DEFAULT_ROOT+'/db/holdings_reunderwrite.sqlite'
TOTAL_TIMEOUT=240
BUSY=['atlas_manage.py','atlas_intraday.py','atlas_eod_positions.py','atlas_position_evidence_bake.py','atlas_profit_protection_apply.py','atlas_quiver_sidecar.py','atlas_perme.py','atlas_holdings_reunderwrite_runner.py']

def log(s): print(dt.datetime.now().isoformat(timespec='seconds')+' '+s, flush=True)
def _timeout(sig, frame): raise TimeoutError('TOTAL_TIMEOUT')
class Lock:
    def __init__(self,p): self.p=Path(p); self.fp=None
    def __enter__(self):
        self.p.parent.mkdir(parents=True,exist_ok=True); self.fp=open(self.p,'a+')
        try: fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('LOCK_HELD')
        self.fp.seek(0); self.fp.truncate(); self.fp.write(str(os.getpid())+'\n'); self.fp.flush(); return self
    def __exit__(self,*a):
        if self.fp: fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN); self.fp.close()

def tm_clear():
    cp=subprocess.run(['/usr/bin/tmutil','status'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
    text=cp.stdout+cp.stderr
    if 'Running = 1' in text: return False,'ACTIVE'
    if 'Running = 0' in text: return True,'CLEAR'
    return False,'UNKNOWN'

def busy_clear():
    forced=os.environ.get('HOLDINGS_REUNDERWRITE_TEST_BUSY')
    if forced: return forced=='CLEAR',[{'gate':'forced','state':forced}]
    states=[]
    for pat in BUSY:
        cp=subprocess.run(['/usr/bin/pgrep','-fl',pat],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        lines=[l for l in cp.stdout.splitlines() if str(os.getpid()) not in l and 'atlas_holdings_reunderwrite_runner.py' not in l]
        states.append({'gate':pat,'state':'ACTIVE' if lines else 'CLEAR','detail':lines[:3]})
    return all(s['state']=='CLEAR' for s in states),states

def _conn_ro(db):
    conn=sqlite3.connect('file:'+str(Path(db).resolve())+'?mode=ro&immutable=1',uri=True); conn.row_factory=sqlite3.Row; conn.execute('PRAGMA query_only=ON'); return conn

def _context_status(packet, ticker, kind):
    if not packet or packet.get('status') in {'MISSING','INVALID'}:
        return {'status':'PACKET_UNAVAILABLE','display':'PACKET_UNAVAILABLE'}
    if packet.get('freshness') == 'STALE':
        return {'status':'PACKET_STALE','display':'PACKET_STALE'}
    payload=packet.get('payload') or {}
    if kind=='quiver':
        health=(payload.get('source_health') or {}).get('status')
        contexts=payload.get('ticker_contexts') or {}
        if health and health!='PASS':
            return {'status':'PACKET_STALE','display':'PACKET_STALE'}
        if ticker in contexts:
            posture=contexts[ticker].get('quiver_view') or contexts[ticker].get('quiver_posture') or 'VALID_CONTEXT'
            return {'status':'VALID_CONTEXT','display':posture,'context':contexts[ticker]}
        endpoint_states=[e.get('state') for e in payload.get('endpoint_status') or []]
        if any(s=='UNENTITLED' for s in endpoint_states):
            return {'status':'NO_USABLE_TICKER_EVIDENCE','display':'NO USABLE TICKER EVIDENCE — packet healthy; some datasets unentitled'}
        return {'status':'NO_USABLE_TICKER_EVIDENCE','display':'NO USABLE TICKER EVIDENCE — packet healthy'}
    if kind=='perme':
        sentiment=payload.get('sentiment') or payload.get('regime') or payload.get('direction')
        if sentiment:
            return {'status':'VALID_CONTEXT','display':f'{sentiment} — fresh post-market packet','context':payload}
        return {'status':'NO_USABLE_TICKER_EVIDENCE','display':'NO USABLE TICKER EVIDENCE — packet healthy'}
    return {'status':'PACKET_UNAVAILABLE','display':'PACKET_UNAVAILABLE'}

def context_for(ticker, acq):
    ext=acq.get('external_context') or {}
    qstate=_context_status(ext.get('quiver'), ticker, 'quiver')
    pstate=_context_status(ext.get('perme'), ticker, 'perme')
    news=((ext.get('benzinga_news') or {}).get(ticker) or {})
    catalyst_state='POSITIVE' if news.get('items') else None
    qposture=qstate.get('display') if qstate.get('status')=='VALID_CONTEXT' else None
    return {'quiver_posture': qposture,
            'quiver_status': qstate.get('status'), 'quiver_display': qstate.get('display'),
            'perme_regime': (pstate.get('context') or {}).get('sentiment') if pstate.get('status')=='VALID_CONTEXT' else None,
            'perme_status': pstate.get('status'), 'perme_display': pstate.get('display'),
            'catalyst_state': catalyst_state, 'sector_known': bool((acq.get('sector_map') or {}).get(ticker)), 'event_checked': True,
            'benzinga_news_freshness': news.get('freshness')}

def evaluate_corrected(acq, rec, db):
    conn=_conn_ro(db)
    try:
        trades={r['id']:dict(r) for r in conn.execute("select * from trades where status='OPEN'").fetchall()}
    finally: conn.close()
    snaps=[]
    for c in rec['chronologies']:
        tr=trades[c['trade_id']]
        bars=[]
        for b in c['entry_session_intraday_bars_used']+c['subsequent_daily_bars']:
            bars.append({'date':b.get('date'),'open':b.get('open'),'high':b.get('high'),'low':b.get('low'),'close':b.get('close'),'volume':b.get('volume')})
        s=evaluate_holding(tr,bars=bars,context=context_for(str(tr.get('ticker')).upper(), acq),as_of=rec['latest_session'])
        s['entry_time_reconciliation']=c['authoritative']
        m=s['current_metrics']; peak=m.get('mfe_pct') or 0; cur=m.get('current_gain_pct') or 0; surrendered=max(0, peak-cur); retained=(cur/peak*100) if peak>0 and cur>0 else 0
        s['human_metrics']={'peak_gain_pct':peak,'current_gain_pct':cur,'profit_retained_pct':retained,'profit_surrendered_pct':surrendered,'loss_below_entry_pct':abs(cur) if cur<0 else 0,'overrun_label':'GAIN FULLY SURRENDERED AND POSITION BELOW ENTRY' if peak>0 and cur<0 else None}
        snaps.append(s)
    pkt=packet_from_snapshots(snaps, run_date=rec['latest_session'])
    pkt['acquisition_digest']=acq.get('input_digest'); pkt['entry_time_reconciliation_digest']=rec.get('input_digest')
    return pkt

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default='/Users/yasser/scripts/atlas.db'); ap.add_argument('--out',default=DEFAULT_OUT); ap.add_argument('--sidecar',default=DEFAULT_SIDECAR); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--force-session',action='store_true')
    args=ap.parse_args(argv); signal.signal(signal.SIGALRM,_timeout); signal.alarm(TOTAL_TIMEOUT)
    try:
        if not args.force_session and dt.datetime.now(ET).weekday()>=5: log('SKIP_NON_TRADING_DAY'); return 0
        with Lock(DEFAULT_LOCK):
            ok,tm=tm_clear();
            if not ok: log('SKIP_TM_'+tm); return 0
            ok,states=busy_clear(); log('BUSY_GATES '+json.dumps(states,sort_keys=True))
            if not ok: log('SKIP_BUSY'); return 0
            out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
            acq=acquire(args.db, str(out/'holdings_reunderwrite_acquisition_v1.json'))
            rec=reconcile(args.db, acq.get('latest_completed_session'), str(out/'holdings_entry_time_reconciliation_v1.json'))
            pkt=evaluate_corrected(acq,rec,args.db)
            if not args.dry_run: persist_packet(pkt,args.sidecar)
            write_outputs(pkt,args.out)
            health={'status':'PASS','positions':len(pkt['positions']),'actions':{p['ticker']:p['action'] for p in pkt['positions']},'created_at':dt.datetime.utcnow().isoformat()+'Z'}
            (out/'holdings_reunderwrite_health.json').write_text(json.dumps(health,indent=2,sort_keys=True)+'\n')
            log('PASS '+json.dumps(health,sort_keys=True)); return 0
    finally: signal.alarm(0)
if __name__=='__main__': raise SystemExit(main())
