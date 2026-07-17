#!/usr/bin/env python3
"""Final runner for Daily Holdings Re-Underwriting.
Uses live acquisition plus corrected post-entry chronology. Advisory-only.
"""
from __future__ import annotations
import argparse, datetime as dt, fcntl, json, os, signal, sqlite3, subprocess, sys, time, hashlib, tempfile
from pathlib import Path
from zoneinfo import ZoneInfo
from atlas_holdings_reunderwrite_acquire import acquire
from atlas_holdings_entry_time_reconcile import reconcile
from atlas_holdings_reunderwrite import evaluate_holding, packet_from_snapshots, write_outputs, persist_packet, open_sidecar
from atlas_holdings_final_action import build_merged_packet
from atlas_macro_context_v1 import load_context, adapt_existing_gates
try:
    from atlas_profit_protection_v2 import evaluate_current_open_from_snapshot as _pp_evaluate_current_open
except Exception:
    _pp_evaluate_current_open = None

ET=ZoneInfo('America/New_York')
DEFAULT_LOCK=os.environ.get('ATLAS_HOLDINGS_REUNDERWRITE_LOCK','/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/run/daily_holdings_reunderwrite.lock')
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

def context_for(ticker, acq, macro_context_v1=None):
    ext=acq.get('external_context') or {}
    qstate=_context_status(ext.get('quiver'), ticker, 'quiver')
    pstate=_context_status(ext.get('perme'), ticker, 'perme')
    news=((ext.get('benzinga_news') or {}).get(ticker) or {})
    catalyst_state='POSITIVE' if news.get('items') else None
    qposture=qstate.get('display') if qstate.get('status')=='VALID_CONTEXT' else None
    result={'quiver_posture': qposture,
            'quiver_status': qstate.get('status'), 'quiver_display': qstate.get('display'),
            'perme_regime': (pstate.get('context') or {}).get('sentiment') if pstate.get('status')=='VALID_CONTEXT' else None,
            'perme_status': pstate.get('status'), 'perme_display': pstate.get('display'),
            'catalyst_state': catalyst_state, 'sector_known': bool((acq.get('sector_map') or {}).get(ticker)), 'event_checked': True,
            'benzinga_news_freshness': news.get('freshness')}
    if macro_context_v1 is not None: result.update(macro_context_v1)
    return result



def _sha_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',',':'), default=str).encode()).hexdigest()


def _atomic_write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, sort_keys=True, default=str) + '\n'
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    with os.fdopen(fd, 'w') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return str(path)



def profit_protection_by_ticker(db_path):
    pp_by_ticker = {}
    if _pp_evaluate_current_open is not None:
        try:
            for r in _pp_evaluate_current_open(db_path=db_path):
                pp_by_ticker[str(getattr(r, 'ticker', '')).upper()] = {'action': getattr(r, 'action', 'HOLD'), 'freshness': getattr(r, 'data_freshness', 'FRESH'), 'why': getattr(r, 'why', None)}
        except TypeError:
            try:
                for r in _pp_evaluate_current_open():
                    pp_by_ticker[str(getattr(r, 'ticker', '')).upper()] = {'action': getattr(r, 'action', 'HOLD'), 'freshness': getattr(r, 'data_freshness', 'FRESH'), 'why': getattr(r, 'why', None)}
            except Exception:
                pp_by_ticker = {}
        except Exception:
            pp_by_ticker = {}
    return pp_by_ticker

def write_runtime_outputs(packet, out_dir, db_path='/Users/yasser/scripts/atlas.db', pp_by_ticker=None):
    out = Path(out_dir)
    archive = out / 'archive' / str(packet.get('run_date') or 'unknown')
    latest = out / 'latest'
    digest = packet.get('packet_digest') or packet.get('input_digest') or _sha_json(packet)
    packet['packet_digest'] = packet.get('packet_digest') or _sha_json(packet)
    paths = write_outputs(packet, archive / digest[:16])
    latest_packet = latest / 'holdings_reunderwrite_packet_v1.json'
    latest_report = latest / 'DAILY_HOLDINGS_REUNDERWRITING.md'
    _atomic_write_json(latest_packet, packet)
    latest_report.write_text(Path(paths['report']).read_text())
    pp_by_ticker = pp_by_ticker if pp_by_ticker is not None else profit_protection_by_ticker(db_path)
    merged = build_merged_packet(packet, profit_protection_by_ticker=pp_by_ticker)
    _atomic_write_json(latest / 'holdings_merged_action_packet_v1.json', merged)
    return {'archive_packet': paths['packet'], 'archive_report': paths['report'], 'latest_packet': str(latest_packet), 'latest_report': str(latest_report), 'latest_merged_packet': str(latest / 'holdings_merged_action_packet_v1.json')}



# Idempotency v1: stable authoritative-input digest.  Excludes runtime metadata
# such as created_at/generated_at, output paths, health timestamps, process ids,
# request ids, archive paths and packet write timestamps.
_VOLATILE_DIGEST_KEYS = {
    'as_of', 'created_at', 'generated_at', 'runner_started_at', 'runner_completed_at',
    'packet_path', 'report_path', 'archive_path', 'latest_path', 'health_path',
    'request_id', 'runtime_uuid', 'process_id', 'pid', 'input_digest', 'packet_digest',
    'acquisition_digest', 'entry_time_reconciliation_digest', 'source_timestamps',
    'prior_action', 'action_changed',
}
_STABLE_SNAPSHOT_KEYS = (
    'trade_id', 'ticker', 'entry_baseline', 'current_metrics', 'current_thesis',
    'thesis_comparison', 'action', 'reason_codes', 'decisive_evidence',
    'contradicting_evidence', 'confidence', 'data_completeness', 'recheck_condition',
    'policy_version', 'broker_authority', 'automatic_trade_closure', 'human_metrics',
    'entry_time_reconciliation',
)


def _canon_value(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k) in _VOLATILE_DIGEST_KEYS:
                continue
            out[str(k)] = _canon_value(v)
        return {k: out[k] for k in sorted(out)}
    if isinstance(value, (list, tuple)):
        vals = [_canon_value(v) for v in value]
        # Lists of dicts with a ticker/trade_id are semantically sets for this digest.
        if all(isinstance(v, dict) for v in vals):
            return sorted(vals, key=lambda d: (str(d.get('ticker') or ''), str(d.get('trade_id') or d.get('id') or ''), json.dumps(d, sort_keys=True, default=str)))
        return vals
    if isinstance(value, float):
        return format(value, '.10g')
    return value


def canonical_authoritative_input(packet, profit_protection_by_ticker=None):
    positions = []
    for s in packet.get('positions') or []:
        row = {k: s.get(k) for k in _STABLE_SNAPSHOT_KEYS if k in s}
        positions.append(_canon_value(row))
    positions.sort(key=lambda d: (str(d.get('ticker') or ''), str(d.get('trade_id') or '')))
    return {
        'schema': 'holdings_reunderwrite_authoritative_input.v1',
        'packet_version': packet.get('packet_version'),
        'policy_version': packet.get('policy_version'),
        'run_date': packet.get('run_date'),
        'positions': positions,
        'profit_protection': _canon_value(profit_protection_by_ticker or {}),
    }


def apply_canonical_digest(packet, profit_protection_by_ticker=None):
    obj = canonical_authoritative_input(packet, profit_protection_by_ticker)
    digest = _sha_json(obj)
    packet['input_digest'] = digest
    packet['canonical_input_schema'] = obj['schema']
    # Stable packet identity used for archive/provenance. It intentionally does
    # not include runtime created_at; created_at remains freshness metadata.
    packet['packet_digest'] = _sha_json({'packet_version': packet.get('packet_version'), 'policy_version': packet.get('policy_version'), 'run_date': packet.get('run_date'), 'input_digest': digest})
    return digest, obj


def persist_packet_idempotent(packet, sidecar=DEFAULT_SIDECAR):
    conn = open_sidecar(sidecar)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id FROM underwriting_runs WHERE run_date=? AND input_digest=? AND policy_version=?', (packet['run_date'], packet['input_digest'], packet['policy_version'])).fetchone()
        if row:
            conn.commit()
            return {'status': 'IDEMPOTENT_NO_OP', 'run_id': int(row[0]), 'snapshots_inserted': 0}
        try:
            conn.execute('INSERT INTO underwriting_runs(run_date,created_at,policy_version,input_digest,packet_json) VALUES(?,?,?,?,?)', (packet['run_date'], packet['created_at'], packet['policy_version'], packet['input_digest'], json.dumps(packet,sort_keys=True,default=str)))
            run_id = conn.execute('SELECT id FROM underwriting_runs WHERE run_date=? AND input_digest=? AND policy_version=?', (packet['run_date'], packet['input_digest'], packet['policy_version'])).fetchone()[0]
        except sqlite3.IntegrityError:
            row = conn.execute('SELECT id FROM underwriting_runs WHERE run_date=? AND input_digest=? AND policy_version=?', (packet['run_date'], packet['input_digest'], packet['policy_version'])).fetchone()
            conn.commit()
            return {'status': 'IDEMPOTENT_NO_OP', 'run_id': int(row[0]), 'snapshots_inserted': 0, 'race_winner': 'other_process'}
        inserted = 0
        for s in packet['positions']:
            conn.execute('INSERT INTO underwriting_snapshots(run_id,trade_id,ticker,action,prior_action,action_changed,reason_codes_json,entry_baseline_json,current_metrics_json,thesis_comparison_json,source_timestamps_json,policy_digest,snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (run_id,s['trade_id'],s['ticker'],s['action'],s.get('prior_action'),1 if s.get('action_changed') else 0,json.dumps(s['reason_codes']),json.dumps(s['entry_baseline'],sort_keys=True,default=str),json.dumps(s['current_metrics'],sort_keys=True,default=str),json.dumps(s['thesis_comparison'],sort_keys=True,default=str),json.dumps({'as_of':s.get('as_of')},sort_keys=True),packet['policy_digest'],json.dumps(s,sort_keys=True,default=str)))
            inserted += 1
        conn.commit()
        return {'status': 'INSERTED', 'run_id': int(run_id), 'snapshots_inserted': inserted}
    finally:
        conn.close()

def evaluate_corrected(acq, rec, db, macro_context_v1=None, macro_receipt=None):
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
        s=evaluate_holding(tr,bars=bars,context=context_for(str(tr.get('ticker')).upper(), acq, macro_context_v1),as_of=rec['latest_session'])
        s['entry_time_reconciliation']=c['authoritative']
        m=s['current_metrics']; peak=m.get('mfe_pct') or 0; cur=m.get('current_gain_pct') or 0; surrendered=max(0, peak-cur); retained=(cur/peak*100) if peak>0 and cur>0 else 0
        s['human_metrics']={'peak_gain_pct':peak,'current_gain_pct':cur,'profit_retained_pct':retained,'profit_surrendered_pct':surrendered,'loss_below_entry_pct':abs(cur) if cur<0 else 0,'overrun_label':'GAIN FULLY SURRENDERED AND POSITION BELOW ENTRY' if peak>0 and cur<0 else None}
        snaps.append(s)
    pkt=packet_from_snapshots(snaps, run_date=rec['latest_session'])
    pkt['acquisition_digest']=acq.get('input_digest'); pkt['entry_time_reconciliation_digest']=rec.get('input_digest')
    if macro_receipt is not None: pkt['macro_context_v1_receipt']=macro_receipt
    return pkt

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default='/Users/yasser/scripts/atlas.db'); ap.add_argument('--out',default=DEFAULT_OUT); ap.add_argument('--sidecar',default=DEFAULT_SIDECAR); ap.add_argument('--context'); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--force-session',action='store_true')
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
            with _conn_ro(args.db) as _c: _holds=[r[0].upper() for r in _c.execute("select ticker from trades where status='OPEN'")]
            _loaded=load_context(args.context or os.environ.get('ATLAS_MACRO_CONTEXT_V1_PATH'), authoritative_holdings=_holds, consumer='daily_reunderwrite.runner/context_for')
            _legacy,_receipt=adapt_existing_gates(_loaded.context,consumer='daily_reunderwrite.runner/context_for',holdings=_holds)
            if _loaded.context is None: _receipt=dict(_loaded.receipt)
            pkt=evaluate_corrected(acq,rec,args.db,_legacy if _loaded.context is not None else None,_receipt)
            pp_by_ticker = profit_protection_by_ticker(args.db)
            digest, canonical_input = apply_canonical_digest(pkt, pp_by_ticker)
            persist_result = {'status': 'DRY_RUN', 'run_id': None, 'snapshots_inserted': 0} if args.dry_run else persist_packet_idempotent(pkt,args.sidecar)
            if persist_result.get('status') == 'IDEMPOTENT_NO_OP':
                health={'status':'IDEMPOTENT_NO_OP','run_id':persist_result.get('run_id'),'input_digest':digest,'canonical_input_schema':canonical_input.get('schema'),'positions':len(pkt['positions']),'actions':{p['ticker']:p['action'] for p in pkt['positions']},'created_at':dt.datetime.utcnow().isoformat()+'Z'}
                (out/'holdings_reunderwrite_health.json').write_text(json.dumps(health,indent=2,sort_keys=True)+'\n')
                log('IDEMPOTENT_NO_OP '+json.dumps(health,sort_keys=True)); return 0
            paths=write_runtime_outputs(pkt,args.out,args.db,pp_by_ticker)
            health={'status':'PASS','persist':persist_result,'paths':paths,'input_digest':digest,'canonical_input_schema':canonical_input.get('schema'),'positions':len(pkt['positions']),'actions':{p['ticker']:p['action'] for p in pkt['positions']},'created_at':dt.datetime.utcnow().isoformat()+'Z'}
            (out/'holdings_reunderwrite_health.json').write_text(json.dumps(health,indent=2,sort_keys=True)+'\n')
            log('PASS '+json.dumps(health,sort_keys=True)); return 0
    finally: signal.alarm(0)

if __name__=='__main__': raise SystemExit(main())
