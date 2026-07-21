#!/usr/bin/env python3
"""Thin operational wrapper: owns immutable cycle identity and post-exit envelope."""
import datetime as dt, hashlib, json, os, subprocess, sys, uuid
from pathlib import Path
from zoneinfo import ZoneInfo
SCRIPTS=Path(os.environ.get('ATLAS_SCRIPTS_DIR') or '/Users/yasser/scripts'); ROOT=Path(os.environ.get('ATLAS_CYCLE_RECEIPT_ROOT') or '/Users/yasser/.hermes/profiles/atlasops/acceptance/machine_cycles')
sys.path.insert(0,str(SCRIPTS))
from atlas_cycle_receipts import atomic_json,canon,sha_bytes,sha_file,db_health,verify_cycle,emit_authority_receipt
DEFAULT_MANIFEST=Path('/Users/yasser/scripts/config/tfe_authority_manifest.json')
DEFAULT_INCIDENT_REGISTER=Path('/Users/yasser/scripts/config/incident_register.jsonl')
DEFAULT_LLM_LEDGER=Path('/Users/yasser/scripts/config/llm_invocations.jsonl')

def governed_paths():
 base=Path(os.environ.get('ATLAS_AUTHORITY_CONFIG_DIR') or DEFAULT_MANIFEST.parent)
 return (Path(os.environ.get('ATLAS_TFE_AUTHORITY_MANIFEST') or base/'tfe_authority_manifest.json'),Path(os.environ.get('ATLAS_INCIDENT_REGISTER') or base/'incident_register.jsonl'),Path(os.environ.get('ATLAS_LLM_INVOCATION_LEDGER') or base/'llm_invocations.jsonl'))

def attach_authority(envelope,manifest_path,incident_register_path,llm_ledger_path,cid):
 missing=[name for name,path in (("TFE_AUTHORITY_MANIFEST",manifest_path),("INCIDENT_REGISTER",incident_register_path),("LLM_INVOCATION_LEDGER",llm_ledger_path)) if not Path(path).is_file()]
 envelope['authority_config_receipt']={'status':'PASS' if not missing else 'DATA_INCOMPLETE','missing':missing,'manifest_path':str(manifest_path),'incident_register_path':str(incident_register_path),'llm_invocation_ledger_path':str(llm_ledger_path)}
 if missing: envelope['exact_failures'].extend('AUTHORITY_CONFIG_MISSING:'+x for x in missing)
 # D2: finalize authority-derived source fields before binding the source envelope.
 authority=emit_authority_receipt('',manifest_path,incident_register_path,llm_ledger_path,envelope['start_utc'],envelope['end_utc'],cid)
 if not all(authority.get(k) is True for k in ('holdings_price_healthy','holdings_reevaluation_healthy','perme_strict','ca_active_complete','tfe_sole_authority','llm_trading_authority_false','no_p0_p1')): envelope['exact_failures'].append('AUTHORITY_FLAGS'); envelope['classification']='FAIL'
 source_envelope_sha=sha_bytes(canon(envelope))
 authority['source_envelope_sha256']=source_envelope_sha
 unsigned=dict(authority); unsigned.pop('receipt_sha256',None)
 authority['receipt_sha256']=sha_bytes(canon(unsigned))
 atomic_json(ROOT/cid/'authority.json',authority)
 envelope['authority_receipt']=authority; envelope['receipt_hashes']['authority']=authority['receipt_sha256']
 envelope['envelope_sha256']=sha_bytes(canon(envelope)); return envelope

def main():
 start=dt.datetime.now(dt.timezone.utc); scheduled=start.replace(minute=(start.minute//10)*10,second=0,microsecond=0)
 cid='intraday-'+scheduled.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
 env=os.environ.copy(); env['ATLAS_CYCLE_ID']=cid; env['ATLAS_CYCLE_SCHEDULED_ET']=scheduled.astimezone(ZoneInfo('America/New_York')).isoformat(); env['ATLAS_CYCLE_RECEIPT_ROOT']=str(ROOT)
 os.environ['ATLAS_CYCLE_ID']=cid; os.environ['ATLAS_CYCLE_RECEIPT_ROOT']=str(ROOT)
 d=ROOT/cid; d.mkdir(parents=True,exist_ok=False); os.chmod(d,0o700)
 start_o={'schema':'atlas.machine_cycle_start.v1','cycle_id':cid,'scheduled_et':env['ATLAS_CYCLE_SCHEDULED_ET'],'started_utc':start.isoformat(),'wrapper_pid':os.getpid(),'wrapper_ppid':os.getppid(),'source':str(SCRIPTS/'atlas_intraday.py'),'interpreter':'/usr/bin/python3'}
 atomic_json(d/'process_start.json',start_o)
 before={p.name:sha_file(p) for p in [SCRIPTS/'atlas.db'] if p.exists()}
 child=subprocess.Popen(['/usr/bin/python3',str(SCRIPTS/'atlas_intraday.py'),*sys.argv[1:]],env=env)
 child_pid=child.pid; exit_code=child.wait()
 end=dt.datetime.now(dt.timezone.utc)
 report={}; delivery={}
 try:
  raw=(SCRIPTS/'atlas_intraday.log').read_bytes(); marker=(f'ATLAS_CYCLE_ID={cid}').encode(); pos=raw.rfind(marker); block=raw[pos:] if pos>=0 else b''
  b=block.find(b'[intraday] telegram report body begin'); e=block.find(b'[intraday] telegram report body end')
  body=block[b:e+len(b'[intraday] telegram report body end')] if b>=0 and e>b else b''
  report={'sha256':sha_bytes(body) if body else None,'complete':bool(body)}
  delivery={'sha256':sha_bytes(block[e:]) if e>=0 else None,'success':b'telegram report success=True' in block}
 except Exception: pass
 completion={'schema':'atlas.machine_child_completion.v1','cycle_id':cid,'child_pid_observed':child_pid,'wrapper_pid':os.getpid(),'wrapper_ppid':os.getppid(),'started_utc':start.isoformat(),'ended_utc':end.isoformat(),'exit_code':exit_code,'source':str(SCRIPTS/'atlas_intraday.py'),'source_sha256':sha_file(SCRIPTS/'atlas_intraday.py'),'interpreter':'/usr/bin/python3','report':report,'delivery':delivery,'db':db_health(SCRIPTS/'atlas.db'),'lock':{'path':'/tmp/atlas_intraday.lock','present_after_child':Path('/tmp/atlas_intraday.lock').exists()},'side_effect_baseline':before}
 from atlas_cycle_receipts import record
 record('child_completion',completion)
 ok,errors,objs=verify_cycle(cid)
 receipt_hashes={k:v.get('receipt_sha256') for k,v in objs.items()}
 envelope={'schema':'atlas.machine_completion_envelope.v1','cycle_id':cid,'scheduled_et':env['ATLAS_CYCLE_SCHEDULED_ET'],'pid':os.getpid(),'ppid':os.getppid(),'child_pid':child_pid,'start_utc':start.isoformat(),'end_utc':end.isoformat(),'exit_code':exit_code,'source':completion['source'],'source_sha256':completion['source_sha256'],'interpreter':completion['interpreter'],'report':report,'delivery':delivery,'receipt_hashes':receipt_hashes,'db':completion['db'],'lock':completion['lock'],'side_effects':{'observer_local_files_only':True},'classification':'PASS' if ok else 'FAIL','exact_failures':errors}
 manifest,incidents,llm_ledger=governed_paths(); envelope=attach_authority(envelope,manifest,incidents,llm_ledger,cid); atomic_json(d/'completion_envelope.json',envelope)
 print('ATLAS_CYCLE_ENVELOPE='+json.dumps({'cycle_id':cid,'classification':envelope['classification'],'exact_failures':errors},sort_keys=True),flush=True)
 return exit_code
if __name__=='__main__': raise SystemExit(main())
