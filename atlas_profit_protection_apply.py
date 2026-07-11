#!/usr/bin/env python3
"""Profit Protection v2 automatic after-close canonical apply runner.

Final-release staged candidate. Atomic all-or-nothing daily batch. No Telegram,
no broker action, no automatic trade closure. Writes only trades.stop_loss,
trades.target_price, and PPv2 audit events when --apply is explicitly supplied.
"""
from __future__ import annotations

import argparse, datetime as dt, fcntl, hashlib, json, os, re, shutil, signal, sqlite3, subprocess, sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import atlas_profit_protection_v2 as pp
from atlas_time import is_trading_day

ET = ZoneInfo("America/New_York")
DEFAULT_DB = "/Users/yasser/scripts/atlas.db"
DEFAULT_SNAPSHOT_DIR = "/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/snapshots"
DEFAULT_SHADOW_DB = "/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/shadow/evidence.sqlite"
DEFAULT_BACKUP_DIR = "/Users/yasser/scripts/archive"
DEFAULT_AUDIT_DIR = "/Users/yasser/Library/Application Support/Atlas/profit_protection_v2_apply"
DEFAULT_LOCK = "/tmp/atlas_profit_protection_v2_apply.lock"
EVENT_TYPE = "MANUAL_CORRECTION"  # existing constrained enum; payload/idempotency identify PPv2
FINAL_DATA_GATE_ET = dt.time(16, 40)
BUSY_LABELS = ("com.atlas.intraday", "com.atlas.eod.positions", "com.atlas.position_evidence_bake", "com.atlas.macro.postmarket")
BUSY_PROCESS_NAMES = ("atlas_intraday.py", "atlas_manage.py", "atlas_eod_positions.py", "atlas_position_evidence_orchestrator.py", "market_scout")


def canon(x: Any) -> str: return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)
def sha_bytes(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def file_sha(path: str | Path) -> str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
def now_utc() -> str: return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def parse_dt(s: str | None) -> dt.datetime | None:
    if not s: return None
    try:
        d=dt.datetime.fromisoformat(str(s).replace('Z','+00:00').replace(' ', 'T'))
        if d.tzinfo is None: d=d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception: return None
def num(x):
    try:
        if x in (None,''): return None
        return float(x)
    except Exception: return None
def cents(x): return None if x is None else round(float(x)+1e-12,2)
def safe_json(x):
    if isinstance(x,dict): return x
    try: return json.loads(x) if x else {}
    except Exception: return {}


def latest_snapshot(snapshot: str | None = None, snapshot_dir: str = DEFAULT_SNAPSHOT_DIR) -> Path:
    if snapshot:
        p=Path(snapshot)
        if not p.exists(): raise FileNotFoundError(str(p))
        return p
    files=sorted(Path(snapshot_dir).glob('snapshot_*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
    if not files: raise FileNotFoundError('no evidence snapshot found')
    return files[0]


def connect(db_path: str, *, write: bool) -> sqlite3.Connection:
    if write:
        con=sqlite3.connect(db_path); con.execute('PRAGMA foreign_keys=ON'); return con
    con=sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro', uri=True); con.execute('PRAGMA query_only=ON'); return con


def health_state(shadow_db: str = DEFAULT_SHADOW_DB, max_age_hours: float = 72) -> dict[str, Any]:
    con=sqlite3.connect(f'file:{Path(shadow_db).resolve()}?mode=ro', uri=True); con.execute('PRAGMA query_only=ON')
    try:
        quick=con.execute('PRAGMA quick_check').fetchone()[0]
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        fk=len(con.execute('PRAGMA foreign_key_check').fetchall())
        last=con.execute('SELECT max(baked_at) FROM runs').fetchone()[0]
        proof=con.execute('SELECT run_id,snapshot_sha256,source_db_sha256_before,source_db_sha256_after,source_db_unchanged FROM runs ORDER BY baked_at DESC LIMIT 1').fetchone()
        age=None
        if last:
            age=(dt.datetime.now(dt.timezone.utc)-parse_dt(last)).total_seconds()/3600
        ok = quick==integrity=='ok' and fk==0 and proof and proof[4] and proof[2]==proof[3] and age is not None and age<=max_age_hours
        return {'ok':bool(ok),'quick_check':quick,'integrity_check':integrity,'fk_rows':fk,'last_success_at':last,'age_hours':age,'run_id':proof[0] if proof else None,'snapshot_sha256':proof[1] if proof else None,'source_db_unchanged':bool(proof and proof[4])}
    finally: con.close()


def final_session_freshness(snapshot_obj: dict[str, Any], health: dict[str, Any], *, asof: str | None = None, min_minutes_after_gate: int = 5) -> dict[str, Any]:
    cap=parse_dt(snapshot_obj.get('captured_at'))
    now=parse_dt(asof) or dt.datetime.now(dt.timezone.utc)
    et_now=now.astimezone(ET)
    expected=str(snapshot_obj.get('expected_et_session') or '')
    if not expected:
        return {'ok':False,'reason':'missing_expected_et_session'}
    expected_date=dt.date.fromisoformat(expected)
    if not is_trading_day(expected_date):
        return {'ok':False,'reason':'expected_session_not_trading_day','expected_et_session':expected}
    checks=snapshot_obj.get('final_bar_checks') or {}
    latest_dates={str(v.get('last_bar_et_session_date')) for v in checks.values() if isinstance(v,dict) and v.get('required')}
    if latest_dates != {expected}:
        return {'ok':False,'reason':'latest_session_mismatch','expected_et_session':expected,'required_dates':sorted(latest_dates)}
    if not health.get('ok'):
        return {'ok':False,'reason':'evidence_bake_unhealthy','health':health}
    if health.get('snapshot_sha256') and health.get('snapshot_sha256') != snapshot_obj.get('content_sha256'):
        return {'ok':False,'reason':'snapshot_digest_mismatch','health_snapshot':health.get('snapshot_sha256'),'snapshot':snapshot_obj.get('content_sha256')}
    if not cap:
        return {'ok':False,'reason':'missing_capture_timestamp'}
    cap_et=cap.astimezone(ET)
    gate_dt=dt.datetime.combine(expected_date, FINAL_DATA_GATE_ET, ET) + dt.timedelta(minutes=min_minutes_after_gate)
    # Do not treat provider's 04:00Z session marker as final-data availability. Require actual acquisition after gate.
    if cap_et <= gate_dt:
        return {'ok':False,'reason':'early_acquisition','captured_et':cap_et.isoformat(),'required_after_et':gate_dt.isoformat()}
    return {'ok':True,'expected_et_session':expected,'latest_completed_bar_date':expected,'captured_at':snapshot_obj.get('captured_at'),'captured_at_et':cap_et.isoformat(),'final_data_gate_et':gate_dt.isoformat(),'health':health}


def db_open_rows(db_path: str) -> dict[int, dict[str, Any]]:
    con=connect(db_path, write=False)
    try:
        cols=[r[1] for r in con.execute('PRAGMA table_info(trades)').fetchall()]
        wanted=[c for c in cols if c in {'id','ticker','status','quantity','entry_price','entry_at','stop_loss','target_price','broker_ref','notes','current_price','last_price','last_price_at','updated_at'}]
        rows=con.execute('SELECT '+','.join(wanted)+' FROM trades WHERE status="OPEN" ORDER BY ticker,id').fetchall()
        return {int(dict(zip(wanted,r))['id']):dict(zip(wanted,r)) for r in rows}
    finally: con.close()


def snapshot_current_open(snap: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out={}
    for row in snap.get('buckets',{}).get('current_open',[]):
        try: out[int(row.get('id'))]=dict(row)
        except Exception: pass
    return out


def original_stop_from_notes(row: dict[str,Any]) -> float | None:
    notes=str(row.get('notes') or '')
    for pat in (r'Atlas v2 entry:.*?stop\s+\$?([0-9]+(?:\.[0-9]+)?)', r'; stop\s+\$?([0-9]+(?:\.[0-9]+)?)', r'implied stop\s+([0-9]+(?:\.[0-9]+)?)'):
        m=re.search(pat, notes, re.I|re.S)
        if m: return float(m.group(1))
    return num(row.get('stop_loss'))


def load_shadow_events(shadow_db: str) -> dict[int, dict[str, Any]]:
    con=sqlite3.connect(f'file:{Path(shadow_db).resolve()}?mode=ro', uri=True); con.execute('PRAGMA query_only=ON')
    try:
        rows=con.execute("SELECT event_id,entity_key,source_ts,payload_sha256 FROM evidence WHERE bucket='current_open' ORDER BY source_ts DESC").fetchall()
        out={}
        for event_id,key,source_ts,payload_sha in rows:
            try: k=int(key)
            except Exception: continue
            out.setdefault(k, {'evidence_event_id':event_id,'source_ts':source_ts,'payload_sha256':payload_sha})
        return out
    finally: con.close()

@dataclass(frozen=True)
class ProposedUpdate:
    trade_id:int; ticker:str; action:str; old_stop:float|None; new_stop:float|None; old_target:float|None; new_target:float|None; current_price:float|None; policy_version:str; policy_digest:str; evidence_event_id:str; provider_timestamp:str; calculation_timestamp:str; reason:str; target_decision:str; idempotency_key:str; no_change_reason:str|None=None


def build_plan(db_path: str, snapshot_path: str, shadow_db: str, *, force_stale=False, provider_conflict=False) -> dict[str, Any]:
    snap=json.loads(Path(snapshot_path).read_text())
    health=health_state(shadow_db)
    freshness=final_session_freshness(snap, health, asof=snap.get('captured_at'))
    provider=snap.get('provider') or {}; db_rows=db_open_rows(db_path); snap_rows=snapshot_current_open(snap); events=load_shadow_events(shadow_db); calc_ts=now_utc(); recs=[]
    for trade_id, dbrow in db_rows.items():
        srow=snap_rows.get(trade_id)
        if not srow: continue
        ticker=str(dbrow.get('ticker') or srow.get('ticker') or '').upper(); old_stop=cents(num(dbrow.get('stop_loss'))); old_target=cents(num(dbrow.get('target_price'))); entry=num(dbrow.get('entry_price')); src=provider.get(ticker) or {}; bars=list(src.get('bars') or [])
        result=pp.evaluate(ticker=ticker, entry=entry, old_stop=old_stop, old_target=old_target, bars=bars, entry_at=dbrow.get('entry_at') or srow.get('entry_at') or srow.get('updated_at'), original_stop=original_stop_from_notes(srow) or old_stop, captured_at=snap.get('captured_at'), provider_name=f"{src.get('provider')}:{src.get('dataset')}", force_stale=(force_stale or not freshness.get('ok')))
        contract=pp.advisory_contract(result); ev=events.get(trade_id) or {}; evidence_event_id=str(ev.get('evidence_event_id') or ''); provider_ts=str(result.provenance.get('last_provider_timestamp') or ''); policy_digest=str(result.provenance.get('policy_digest') or pp.sha_json({'version':pp.POLICY_VERSION,'params':pp.POLICY_PARAMS})); new_stop=None; new_target=None; no_change=None
        if provider_conflict: no_change='provider_conflict'
        elif not freshness.get('ok') or not evidence_event_id or not provider_ts or str(result.data_freshness).startswith('STALE'): no_change='missing_or_stale_evidence'
        else:
            if result.action in {'TIGHTEN','PROTECT PROFIT','TRIM REVIEW'} and contract.get('recommended_stop') is not None:
                c=cents(num(contract.get('recommended_stop')))
                if c is not None and old_stop is not None and c>old_stop and result.current_price is not None and c<result.current_price: new_stop=c
            if result.target_decision in {'LOWER','EXTEND'} and contract.get('recommended_target') is not None:
                t=cents(num(contract.get('recommended_target')))
                if t is not None and result.current_price is not None and t>result.current_price: new_target=t
            if new_stop is None and new_target is None: no_change='no_eligible_change'
        payload={'trade_id':trade_id,'ticker':ticker,'old_stop':old_stop,'new_stop':new_stop,'old_target':old_target,'new_target':new_target,'policy_digest':policy_digest,'evidence_event_id':evidence_event_id,'action':result.action,'target_decision':result.target_decision,'expected_et_session':snap.get('expected_et_session')}
        idem='ppv2_apply_'+pp.sha_json(payload)
        recs.append(ProposedUpdate(trade_id,ticker,result.action,old_stop,new_stop,old_target,new_target,result.current_price,pp.POLICY_VERSION,policy_digest,evidence_event_id,provider_ts,calc_ts,result.why,result.target_decision,idem,no_change))
    return {'snapshot':str(snapshot_path),'snapshot_sha256':file_sha(snapshot_path),'freshness':freshness,'recommendations':recs,'eligible':[r for r in recs if r.new_stop is not None or r.new_target is not None]}


def validate_rec(rec: ProposedUpdate, row: dict[str, Any]) -> None:
    if str(row.get('status'))!='OPEN': raise ValueError('status is not OPEN')
    if int(row.get('id'))!=rec.trade_id or str(row.get('ticker')).upper()!=rec.ticker: raise ValueError('trade id/ticker mismatch')
    if cents(num(row.get('stop_loss')))!=rec.old_stop or cents(num(row.get('target_price')))!=rec.old_target: raise ValueError('old stop/target preimage drift')
    if rec.new_stop is not None:
        if rec.new_stop <= (rec.old_stop or -1e99): raise ValueError('stop widening/no tighten rejected')
        if rec.current_price is None or rec.new_stop >= rec.current_price: raise ValueError('stop at/above current price rejected')
    if rec.new_target is not None and (rec.current_price is None or rec.new_target <= rec.current_price): raise ValueError('target at/below current price rejected')


def db_snapshot(db_path: str) -> dict[str, Any]:
    con=connect(db_path, write=False)
    try:
        tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts={t:con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        return {'sha':file_sha(db_path),'integrity':con.execute('PRAGMA integrity_check').fetchone()[0],'fk_rows':len(con.execute('PRAGMA foreign_key_check').fetchall()),'counts':counts}
    finally: con.close()


def create_verified_backup(db_path: str, backup_dir: str=DEFAULT_BACKUP_DIR) -> dict[str, Any]:
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    ts=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=Path(backup_dir)/f'atlas_ppv2_apply_{ts}_preapply.bak.db'
    shutil.copy2(db_path, dest)
    meta=db_snapshot(str(dest))
    if meta['integrity']!='ok' or meta['fk_rows']!=0 or meta['sha']!=file_sha(db_path): raise RuntimeError('backup verification failed')
    return {'path':str(dest), **meta}


def apply_atomic(db_path: str, plan: dict[str, Any], *, backup_dir: str=DEFAULT_BACKUP_DIR, inject_failure_ticker: str|None=None) -> dict[str, Any]:
    eligible=list(plan.get('eligible') or [])
    if not eligible: return {'status':'NO_CHANGE','backup':None,'apply_results':[]}
    # Read-only validation of every eligible row before backup/mutation.
    rows=db_open_rows(db_path)
    for rec in eligible: validate_rec(rec, rows.get(rec.trade_id) or {})
    backup=create_verified_backup(db_path, backup_dir)
    con=connect(db_path, write=True); results=[]
    try:
        con.execute('BEGIN IMMEDIATE')
        # Revalidate all rows again inside the single daily transaction.
        for rec in eligible:
            row=con.execute('SELECT id,ticker,status,stop_loss,target_price,entry_price,quantity,broker_ref FROM trades WHERE id=?',(rec.trade_id,)).fetchone()
            if not row: raise ValueError('trade missing')
            rowd=dict(zip(['id','ticker','status','stop_loss','target_price','entry_price','quantity','broker_ref'], row)); validate_rec(rec,rowd)
        for rec in eligible:
            existing=con.execute('SELECT id FROM portfolio_event_journal WHERE idempotency_key=?',(rec.idempotency_key,)).fetchone()
            if existing:
                row=con.execute('SELECT stop_loss,target_price FROM trades WHERE id=?',(rec.trade_id,)).fetchone()
                if rec.new_stop is not None and cents(num(row[0]))!=rec.new_stop: raise ValueError('idempotency stop mismatch')
                if rec.new_target is not None and cents(num(row[1]))!=rec.new_target: raise ValueError('idempotency target mismatch')
                results.append({'trade_id':rec.trade_id,'ticker':rec.ticker,'status':'IDEMPOTENT','event_id':existing[0]}); continue
            sets=[]; vals=[]
            if rec.new_stop is not None: sets.append('stop_loss=?'); vals.append(rec.new_stop)
            if rec.new_target is not None: sets.append('target_price=?'); vals.append(rec.new_target)
            vals.append(rec.trade_id); con.execute('UPDATE trades SET '+', '.join(sets)+' WHERE id=?', vals)
            if inject_failure_ticker and rec.ticker==inject_failure_ticker: raise RuntimeError(f'injected failure for {rec.ticker}')
            payload=asdict(rec); payload.update({'policy_authority':'CANONICAL_APPLY_AFTER_PROF_APPROVAL','broker_authority':'NO','automatic_trade_closure':'NO','freshness':plan.get('freshness')})
            con.execute("INSERT INTO portfolio_event_journal(event_type,ticker,lot_id,occurred_at,recorded_at,effective_at,payload_json,source,evidence_id,prof_approved,supersedes_id,linked_reversal_id,idempotency_key,legacy_trades_id,legacy_cash_ledger_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (EVENT_TYPE,rec.ticker,None,rec.calculation_timestamp,now_utc(),rec.calculation_timestamp,canon(payload),'atlas_profit_protection_apply.py',None,1,None,None,rec.idempotency_key,rec.trade_id,None))
            eid=con.execute('SELECT id FROM portfolio_event_journal WHERE idempotency_key=?',(rec.idempotency_key,)).fetchone()[0]
            results.append({'trade_id':rec.trade_id,'ticker':rec.ticker,'status':'UPDATED','event_id':eid,'new_stop':rec.new_stop,'new_target':rec.new_target})
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RuntimeError('integrity check failed in transaction')
        if con.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('foreign key check failed in transaction')
        con.commit(); return {'status':'UPDATED','backup':backup,'apply_results':results}
    except Exception:
        con.rollback(); raise
    finally: con.close()


def active_writers() -> list[str]:
    active=[]
    try:
        text=subprocess.run(['/bin/launchctl','list'],text=True,capture_output=True,timeout=5).stdout
        for line in text.splitlines():
            parts=line.split('\t')
            if len(parts)>=3 and parts[2] in BUSY_LABELS and parts[0]!='-': active.append('label:'+parts[2])
    except Exception: pass
    try:
        text=subprocess.run(['/bin/ps','-axo','pid=,command='],text=True,capture_output=True,timeout=5).stdout; me=os.getpid()
        for line in text.splitlines():
            bits=line.strip().split(None,1)
            if len(bits)==2 and int(bits[0])!=me and any(n in bits[1] for n in BUSY_PROCESS_NAMES): active.append('process:'+bits[0]+':'+bits[1][:120])
    except Exception: pass
    return sorted(set(active))


def run_orchestrator(args) -> dict[str, Any]:
    lock=Path(args.lock); lock.parent.mkdir(parents=True, exist_ok=True); fd=os.open(lock, os.O_CREAT|os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd); return {'status':'SKIP_LOCKED'}
    try:
        if active_writers(): return {'status':'SKIP_BUSY','active':active_writers()}
        snap=latest_snapshot(args.snapshot or None, args.snapshot_dir); snap_obj=json.loads(snap.read_text()); health=health_state(args.shadow_db); fresh=final_session_freshness(snap_obj, health)
        if not fresh.get('ok'): return {'status':'SKIP_FRESHNESS','freshness':fresh}
        plan=build_plan(args.db, str(snap), args.shadow_db)
        audit_dir=Path(args.audit_dir); audit_dir.mkdir(parents=True, exist_ok=True)
        if not plan['eligible']:
            report={'status':'NO_CHANGE','plan':[asdict(r) for r in plan['recommendations']], 'freshness':plan['freshness']}
        elif args.apply:
            before=db_snapshot(args.db); applied=apply_atomic(args.db, plan, backup_dir=args.backup_dir); after=db_snapshot(args.db); report={'status':applied['status'],'before':before,'after':after,'allowed_table_delta':{'portfolio_event_journal': after['counts'].get('portfolio_event_journal',0)-before['counts'].get('portfolio_event_journal',0)},'apply':applied,'plan':[asdict(r) for r in plan['recommendations']], 'freshness':plan['freshness']}
        else:
            report={'status':'PLAN_ONLY','eligible':[asdict(r) for r in plan['eligible']], 'plan':[asdict(r) for r in plan['recommendations']], 'freshness':plan['freshness']}
        out=audit_dir/(dt.datetime.now(dt.timezone.utc).strftime('ppv2_apply_%Y%m%dT%H%M%SZ.json'))
        out.write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
        return {'status':report['status'],'audit_report':str(out),'eligible_count':len(plan['eligible'])}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)


def main(argv: list[str] | None=None) -> int:
    ap=argparse.ArgumentParser(description='Profit Protection v2 final after-close canonical apply runner')
    ap.add_argument('--db', default=DEFAULT_DB); ap.add_argument('--snapshot', default=''); ap.add_argument('--snapshot-dir', default=DEFAULT_SNAPSHOT_DIR); ap.add_argument('--shadow-db', default=DEFAULT_SHADOW_DB); ap.add_argument('--backup-dir', default=DEFAULT_BACKUP_DIR); ap.add_argument('--audit-dir', default=DEFAULT_AUDIT_DIR); ap.add_argument('--lock', default=DEFAULT_LOCK); ap.add_argument('--apply', action='store_true'); ap.add_argument('--allow-production', action='store_true'); ap.add_argument('--inject-failure-ticker', default='')
    args=ap.parse_args(argv)
    if str(Path(args.db).resolve())==str(Path(DEFAULT_DB).resolve()) and args.apply and not args.allow_production: raise SystemExit('REFUSING_PRODUCTION_DB_APPLY_WITHOUT_ALLOW_PRODUCTION')
    if args.inject_failure_ticker:
        snap=latest_snapshot(args.snapshot or None,args.snapshot_dir); plan=build_plan(args.db,str(snap),args.shadow_db); print(json.dumps(apply_atomic(args.db,plan,backup_dir=args.backup_dir,inject_failure_ticker=args.inject_failure_ticker),indent=2,sort_keys=True,default=str)); return 0
    print(json.dumps(run_orchestrator(args),sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
