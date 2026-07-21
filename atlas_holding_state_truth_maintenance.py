#!/usr/bin/env python3
"""Append-only Atlas V3 shadow truth maintenance; canonical remains locked."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, sqlite3, tempfile, uuid
from zoneinfo import ZoneInfo
from atlas_holding_state_schema import digest, make_packet, make_receipt, verify_packet, verify_receipt
def base_path(): return pathlib.Path(os.environ.get('ATLAS_HOLDING_STATE_BASE','/Users/yasser/Library/Application Support/Atlas/holding_state_v3'))
def db_path(): return pathlib.Path(os.environ.get('ATLAS_DB','/Users/yasser/scripts/atlas.db'))
def daily_path(): return pathlib.Path(os.environ.get('ATLAS_DAILY_PACKET','/Users/yasser/atlas_inbox/holdings_reunderwrite/latest/holdings_merged_action_packet_v1.json'))
def snap_dir(): return pathlib.Path(os.environ.get('ATLAS_EVIDENCE_SNAPSHOT_DIR','/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/snapshots'))
def pp_dir(): return pathlib.Path(os.environ.get('ATLAS_PP_AUDIT_DIR','/Users/yasser/Library/Application Support/Atlas/profit_protection_v2_apply'))
def truth_db(): return base_path()/'truth/holding_state_truth.sqlite'
def pointer_path(): return base_path()/'manifests/current_runtime_manifest.json'
UNITS=('PRE_MARKET_HOLDINGS','INTRADAY_HOLDINGS','EOD_POSTMARKET_HOLDINGS','CONVERSATION_HOLDINGS','BROKER_PENDING_VISIBILITY','DAILY_PP_HOLDING_SECTIONS')
ET=ZoneInfo('America/New_York')
CONTEXTS={'LIVE_SCHEDULER','HISTORICAL_REPLAY','DEPLOYMENT_SMOKE','DRY_RUN','INTERNAL_PROBE'}
def nowz(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def stable(o): return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str)
def sha(o): return hashlib.sha256((o if isinstance(o,bytes) else stable(o).encode())).hexdigest()
def readj(p): return json.loads(pathlib.Path(p).read_text())
def atomic_json(path,obj,mode=0o444):
 p=pathlib.Path(path);p.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix='.'+p.name+'.',dir=p.parent)
 try:
  with os.fdopen(fd,'w') as f:f.write(json.dumps(obj,sort_keys=True,indent=2,default=str)+'\n');f.flush();os.fsync(f.fileno())
  os.chmod(tmp,mode);os.replace(tmp,p);d=os.open(p.parent,os.O_RDONLY);os.fsync(d);os.close(d)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 return str(p)
def latest(globber):
 xs=sorted(globber,key=lambda p:p.stat().st_mtime,reverse=True);return xs[0] if xs else None
def connect_truth(path=None):
 path=pathlib.Path(path) if path else truth_db()
 path.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(path);c.execute('pragma journal_mode=WAL');c.execute('pragma foreign_keys=on');c.executescript('''
CREATE TABLE IF NOT EXISTS packet_publications(packet_id TEXT PRIMARY KEY,packet_digest TEXT NOT NULL,ticker TEXT,trade_id INTEGER,lot_id INTEGER,nyse_session TEXT,run_id TEXT,execution_context TEXT,rebuild_reason TEXT,packet_path TEXT NOT NULL,receipt_id TEXT,receipt_path TEXT,current_state TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packet_supersessions(event_id TEXT PRIMARY KEY,prior_packet_id TEXT,new_packet_id TEXT,ticker TEXT,trade_id INTEGER,lot_id INTEGER,reason TEXT,run_id TEXT,nyse_session TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lifecycle_evidence(event_id TEXT PRIMARY KEY,ticker TEXT,trade_id INTEGER,lot_id INTEGER,lifecycle TEXT,broker_reference TEXT,event_json TEXT NOT NULL,run_id TEXT,nyse_session TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadow_comparison_evidence(evidence_id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,nyse_session TEXT NOT NULL,run_id TEXT NOT NULL,execution_context TEXT NOT NULL,unit TEXT NOT NULL,entrypoint TEXT NOT NULL,ticker TEXT,trade_id INTEGER,lot_id INTEGER,legacy_action TEXT,canonical_action TEXT,packet_id TEXT,packet_digest TEXT,external_authority_selected TEXT NOT NULL,owner_facing_send INTEGER NOT NULL,evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS canonical_action_ledger(event_id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,nyse_session TEXT NOT NULL,run_id TEXT NOT NULL,execution_context TEXT NOT NULL,unit TEXT NOT NULL,entrypoint TEXT NOT NULL,ticker TEXT,trade_id INTEGER,lot_id INTEGER,action TEXT,packet_id TEXT,packet_digest TEXT,event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dispatch_evidence(event_id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,nyse_session TEXT NOT NULL,run_id TEXT NOT NULL,execution_context TEXT NOT NULL,unit TEXT NOT NULL,entrypoint TEXT NOT NULL,ticker TEXT,trade_id INTEGER,lot_id INTEGER,legacy_action TEXT,canonical_action TEXT,packet_id TEXT,packet_digest TEXT,external_authority_selected TEXT NOT NULL,owner_facing_send INTEGER NOT NULL,event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS send_boundary_evidence(event_id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,nyse_session TEXT NOT NULL,run_id TEXT NOT NULL,execution_context TEXT NOT NULL,external_authority_selected TEXT NOT NULL,canonical_internal INTEGER NOT NULL,canonical_owner_sends INTEGER NOT NULL,event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_attestations(run_id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,nyse_session TEXT NOT NULL,execution_context TEXT NOT NULL,bypass_clean INTEGER NOT NULL,broker_order_state TEXT NOT NULL,manifest_path TEXT,event_json TEXT NOT NULL);
''');c.commit();return c
def db_open():
 c=sqlite3.connect(f'file:{db_path().resolve()}?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row
 q='''SELECT t.id trade_id,t.ticker,t.status,t.quantity,t.entry_price,t.entry_at,t.stop_loss,t.target_price,t.broker_ref,t.updated_at,l.id lot_id,l.status lot_status,l.quantity_text FROM trades t JOIN position_lots l ON l.legacy_trades_id=t.id AND l.status='OPEN' WHERE t.status='OPEN' ORDER BY t.ticker,t.id'''
 rows=[dict(r) for r in c.execute(q)];closed=[dict(r) for r in c.execute("SELECT t.id trade_id,t.ticker,t.status,t.broker_ref,t.exit_at,t.exit_price,l.id lot_id,l.status lot_status,l.exit_event_id FROM trades t JOIN position_lots l ON l.legacy_trades_id=t.id WHERE t.status='CLOSED' AND l.status='CLOSED' AND t.ticker='LASR' ORDER BY t.id DESC")];c.close();return rows,closed
def source_inputs():
 daily=readj(daily_path()) if daily_path().exists() else {};dp={str(x.get('ticker')).upper():x for x in daily.get('positions') or []}
 sp=latest(snap_dir().glob('snapshot_*.json'));snap=readj(sp) if sp else {};session=str(snap.get('expected_et_session') or daily.get('run_date') or dt.datetime.now(ET).date());provider=snap.get('provider') or {}
 ppfile=latest(pp_dir().glob('ppv2_apply_*.json'));pp=readj(ppfile) if ppfile else {};ppmap={str(x.get('ticker')).upper():x for x in pp.get('plan') or []}
 return daily,dp,sp,snap,session,provider,ppfile,pp,ppmap
def bar(provider,ticker,session):
 rows=(provider.get(ticker) or {}).get('bars') or [];xs=[x for x in rows if str(x.get('session_date'))==session];return xs[-1] if xs else None
def current_digest(row,session):
 return {'trade_lot_binding_digest':sha({'trade_id':row['trade_id'],'lot_id':row['lot_id'],'ticker':row['ticker'],'quantity':row.get('quantity_text') or row.get('quantity')}),'broker_lifecycle_digest':sha({'trade_id':row['trade_id'],'lot_id':row['lot_id'],'state':'OPEN'}),'calendar_digest':sha({'calendar':'NYSE','completed_session':session})}
def build_packet(row,daily,pp,price_bar,session,built,ttl_hours=18):
 t=row['ticker'];ids=current_digest(row,session);price=price_bar.get('close') if price_bar else None;pts=price_bar.get('provider_timestamp') if price_bar else None
 reasons=[]
 if not daily: reasons.append('DAILY_COMPONENT_MISSING')
 if not pp: reasons.append('PROFIT_PROTECTION_COMPONENT_MISSING')
 if not price_bar: reasons.append('COMPLETED_SESSION_PRICE_MISSING')
 final=(daily or {}).get('final_action') or 'DATA INCOMPLETE';observed='DATA_INCOMPLETE'
 if price is not None:
  observed='BELOW_STOP' if float(price)<=float(row['stop_loss']) else ('TARGET_ZONE_REACHED' if float(price)>=float(row['target_price']) else 'ABOVE_STOP')
 if reasons: final='DATA INCOMPLETE'
 payload={'trade_id':row['trade_id'],'lot_id':row['lot_id'],'ticker':t,'completed_session':session,'canonical_input_digest':sha({'row':row,'daily':daily,'pp':pp,'bar':price_bar,'session':session}),'trade_identity':{'trade_id':row['trade_id'],'lot_id':row['lot_id'],'ticker':t,'status':'OPEN','quantity':row.get('quantity_text') or row.get('quantity'),'entry_price':row.get('entry_price'),'entry_at':row.get('entry_at')},'canonical_levels':{'entry':row.get('entry_price'),'stop':row.get('stop_loss'),'target':row.get('target_price'),'source':'ATLAS_DB_GOVERNED','version_digest':sha({'stop':row.get('stop_loss'),'target':row.get('target_price'),'updated_at':row.get('updated_at')})},'provider_candidates':[{'provider':'MASSIVE','source_class':'COMPLETED_SESSION_DAILY_BAR','price':price,'timestamp':pts,'session':session,'role':'DISPLAY_VALUATION_STOP_TARGET','validity':'VALID' if price_bar else 'MISSING'}],'stop_target_broker_events':[],'selected_components':{'DAILY':{'component_id':daily.get('input_digest') if daily else None,'timestamp':(daily or {}).get('source_timestamps',{}).get('daily_packet_position_as_of'),'freshness':'FRESH' if daily else 'MISSING'},'PP':{'component_id':pp.get('evidence_event_id') if pp else None,'timestamp':pp.get('provider_timestamp') if pp else None,'freshness':'FRESH' if pp else 'MISSING'}},'provenance':{**ids,'governed_calendar_digest':ids['calendar_digest'],'provider_source':'MASSIVE','provider_timestamp':pts,'source_session':session,'governed_levels_digest':sha({'stop':row.get('stop_loss'),'target':row.get('target_price')}),'daily_digest':sha(daily) if daily else None,'profit_protection_digest':sha(pp) if pp else None,'broker_order_state':'UNVERIFIED'},'axes':{'observed_market_risk_state':{'state':observed,'reason_codes':reasons},'advisory_action':{'action':final,'reason_codes':(daily or {}).get('final_reason_codes') or reasons,'source':'RECONCILED_DAILY_PP_AUTHORITY','automatic_trade_authority':'NO'},'broker_ledger_lifecycle':{'state':'OPEN','event_ids':[],'authority':'ATLAS_LEDGER','automatic_trade_authority':'NO'}},'price_roles':{k:{'price':price,'source':'MASSIVE_COMPLETED_SESSION','timestamp':pts,'session':session,'validity':'VALID' if price_bar else 'UNAVAILABLE'} for k in ('display','valuation','stop_evaluation','target_evaluation')},'retention':{'retention_valid':True},'alert_projection':{'external_visibility':'shadow_internal_only','manual_execution_only':True,'broker_order_state':'UNVERIFIED'},'policy_versions':['atlas-authority.v3','atlas-v3.0.1-single-action-authority','atlas-truth-maintenance.v1'],'built_at':built,'freshness_expires_at':(dt.datetime.fromisoformat(built.replace('Z','+00:00'))+dt.timedelta(hours=ttl_hours)).isoformat().replace('+00:00','Z')}
 return make_packet(payload)
def build_empty_open_set_packet(session,built,ttl_hours=18):
 """Build the canonical, positive representation of a verified empty OPEN set."""
 binding=sha({'state':'EMPTY_OPEN_SET','open_trade_lot_count':0});calendar=sha({'calendar':'NYSE','completed_session':session})
 expires=(dt.datetime.fromisoformat(built.replace('Z','+00:00'))+dt.timedelta(hours=ttl_hours)).isoformat().replace('+00:00','Z')
 payload={'ticker':'EMPTY_OPEN_SET','trade_id':None,'lot_id':None,'empty_open_set':True,'open_trade_lot_count':0,'completed_session':session,'canonical_input_digest':sha({'state':'EMPTY_OPEN_SET','open_trade_lot_count':0,'session':session}),'trade_identity':{'trade_id':None,'lot_id':None,'ticker':None,'status':'EMPTY_OPEN_SET','quantity':0},'canonical_levels':{'entry':None,'stop':None,'target':None,'source':'NOT_APPLICABLE'},'provider_candidates':[],'stop_target_broker_events':[],'selected_components':{'DAILY':{'freshness':'NOT_APPLICABLE'},'PP':{'freshness':'NOT_APPLICABLE'}},'provenance':{'trade_lot_binding_digest':binding,'broker_lifecycle_digest':binding,'calendar_digest':calendar,'governed_calendar_digest':calendar,'provider_source':'NOT_APPLICABLE','provider_timestamp':None,'source_session':session,'broker_order_state':'NOT_APPLICABLE'},'axes':{'observed_market_risk_state':{'state':'NO_OPEN_HOLDINGS','reason_codes':['EMPTY_OPEN_SET']},'advisory_action':{'action':'HOLD','reason_codes':['EMPTY_OPEN_SET'],'source':'CANONICAL_EMPTY_OPEN_SET','automatic_trade_authority':'NO'},'broker_ledger_lifecycle':{'state':'NO_BROKER_EVENT','event_ids':[],'authority':'BROKER_LEDGER_AXIS','automatic_trade_authority':'NO'}},'price_roles':{n:{'price':None,'source':'NOT_APPLICABLE','timestamp':None,'session':session,'validity':'NOT_APPLICABLE'} for n in ('display','valuation','stop_evaluation','target_evaluation')},'retention':{'retention_valid':True,'retention_expires_at':expires},'alert_projection':{'eligible':False,'reason_codes':['EMPTY_OPEN_SET']},'policy_versions':['atlas-empty-open-set.v1'],'built_at':built,'freshness_expires_at':expires}
 return make_packet(payload)
def receipt(packet,row,session,loaded):
 if packet.get('empty_open_set') is True and packet.get('open_trade_lot_count')==0:
  p=packet['provenance']
  return make_receipt({'loaded_at':loaded,'current_calendar_digest':p.get('governed_calendar_digest'),'current_trade_lot_binding_digest':p.get('trade_lot_binding_digest'),'current_broker_lifecycle_digest':p.get('broker_lifecycle_digest'),'validation_policy_version':'atlas-truth-load-validation.v1','usability':'USABLE','reason_codes':[],'rebuild_required':False,'price_role_usability':{k:True for k in (packet.get('price_roles') or {})},'retention_valid':True,'empty_open_set':True},packet)
 reasons=[];p=packet['provenance'];roles=packet.get('price_roles') or {};levels=packet.get('canonical_levels') or {}
 if row.get('status')!='OPEN' or row.get('lot_status')!='OPEN':reasons.append('TRADE_OR_LOT_NOT_OPEN')
 if str(packet.get('completed_session'))!=session:reasons.append('SOURCE_SESSION_INVALID')
 if levels.get('stop')!=row.get('stop_loss') or levels.get('target')!=row.get('target_price'):reasons.append('GOVERNED_LEVEL_VERSION_MISMATCH')
 for n in ('display','valuation','stop_evaluation','target_evaluation'):
  r=roles.get(n) or {}
  if r.get('validity')!='VALID' or r.get('session')!=session or not r.get('timestamp'):reasons.append('PRICE_ROLE_INVALID_'+n.upper())
 expiry=dt.datetime.fromisoformat(packet['freshness_expires_at'].replace('Z','+00:00'));ld=dt.datetime.fromisoformat(loaded.replace('Z','+00:00'))
 if ld>expiry:reasons.append('PACKET_FRESHNESS_EXPIRED')
 state='USABLE' if not reasons else 'DATA_INCOMPLETE'
 return make_receipt({'loaded_at':loaded,'current_calendar_digest':p.get('governed_calendar_digest'),'current_trade_lot_binding_digest':p.get('trade_lot_binding_digest'),'current_broker_lifecycle_digest':p.get('broker_lifecycle_digest'),'validation_policy_version':'atlas-truth-load-validation.v1','usability':state,'reason_codes':sorted(set(reasons)),'rebuild_required':bool(reasons),'price_role_usability':{k:not any(k.upper() in x for x in reasons) for k in roles},'retention_valid':True},packet)
def append_index(db,table,columns,values,keycol,key):
 if db.execute(f'SELECT 1 FROM {table} WHERE {keycol}=?',(key,)).fetchone():return
 marks=','.join('?' for _ in values);db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",values)
def swap_pointer(target):
 p=pointer_path();p.parent.mkdir(parents=True,exist_ok=True);tmp=p.parent/('.current.'+uuid.uuid4().hex);os.symlink(target,tmp);os.replace(tmp,p);return str(p)
def refresh(*,reason='MANUAL_REFRESH',execution_context='INTERNAL_PROBE',run_id=None,force=False):
 if execution_context not in CONTEXTS:raise ValueError('EXECUTION_CONTEXT_INVALID')
 run_id=run_id or uuid.uuid4().hex;built=nowz();daily,dp,sp,snap,session,provider,ppfile,pp,ppmap=source_inputs();rows,closed=db_open();base=base_path();truth=connect_truth()
 (base/'packets').mkdir(parents=True,exist_ok=True);(base/'receipts').mkdir(parents=True,exist_ok=True)
 pdb=sqlite3.connect(base/'packets/holding_state_packets.sqlite');rdb=sqlite3.connect(base/'receipts/packet_load_validation_receipts.sqlite')
 pdb.execute('CREATE TABLE IF NOT EXISTS holding_state_packets(packet_id TEXT PRIMARY KEY,packet_digest TEXT NOT NULL,ticker TEXT,trade_id INTEGER,lot_id INTEGER,path TEXT NOT NULL,packet_json TEXT NOT NULL)')
 rdb.execute('CREATE TABLE IF NOT EXISTS packet_load_validation_receipts(receipt_id TEXT PRIMARY KEY,packet_id TEXT NOT NULL,packet_digest TEXT NOT NULL,ticker TEXT,trade_id INTEGER,lot_id INTEGER,path TEXT NOT NULL,receipt_json TEXT NOT NULL)')
 packet_index={};receipt_index={};results=[]
 if not rows:
  rows=[{'ticker':'EMPTY_OPEN_SET','trade_id':None,'lot_id':None,'status':'EMPTY_OPEN_SET','lot_status':'EMPTY_OPEN_SET'}]
 for row in rows:
  t=row['ticker'];pkt=build_empty_open_set_packet(session,built) if t=='EMPTY_OPEN_SET' else build_packet(row,dp.get(t),ppmap.get(t),bar(provider,t,session),session,built);rec=receipt(pkt,row,session,built);verify_packet(pkt);verify_receipt(rec,pkt)
  pp=base/'packets/json'/(pkt['packet_id']+'.json');rp=base/'receipts/json'/(rec['receipt_id']+'.json')
  if not pp.exists():atomic_json(pp,pkt)
  elif digest(readj(pp))!=digest(pkt):raise RuntimeError('PACKET_ID_COLLISION')
  if not rp.exists():atomic_json(rp,rec)
  packet_index[f"{t}:{row['trade_id']}:{row['lot_id']}"]={'path':str(pp),'digest':digest(pkt),'packet_id':pkt['packet_id']};receipt_index[pkt['packet_id']]={'path':str(rp),'receipt_id':rec['receipt_id'],'usability':rec['usability']}
  prior=truth.execute("SELECT packet_id FROM packet_publications WHERE ticker=? AND trade_id=? AND lot_id=? AND current_state='CURRENT' ORDER BY created_at DESC LIMIT 1",(t,row['trade_id'],row['lot_id'])).fetchone();prior_id=prior[0] if prior else None
  if prior_id and prior_id!=pkt['packet_id']:
   truth.execute("UPDATE packet_publications SET current_state='SUPERSEDED' WHERE packet_id=?",(prior_id,));eid=sha({'prior':prior_id,'new':pkt['packet_id'],'reason':reason,'run':run_id});truth.execute("INSERT OR IGNORE INTO packet_supersessions VALUES(?,?,?,?,?,?,?,?,?,?)",(eid,prior_id,pkt['packet_id'],t,row['trade_id'],row['lot_id'],reason,run_id,session,built))
  truth.execute("INSERT OR IGNORE INTO packet_publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(pkt['packet_id'],pkt['packet_digest'],t,row['trade_id'],row['lot_id'],session,run_id,execution_context,reason,str(pp),rec['receipt_id'],str(rp),'CURRENT',built))
  append_index(pdb,'holding_state_packets',['packet_id','packet_digest','ticker','trade_id','lot_id','path','packet_json'],[pkt['packet_id'],pkt['packet_digest'],t,row['trade_id'],row['lot_id'],str(pp),stable(pkt)],'packet_id',pkt['packet_id']);append_index(rdb,'packet_load_validation_receipts',['receipt_id','packet_id','packet_digest','ticker','trade_id','lot_id','path','receipt_json'],[rec['receipt_id'],pkt['packet_id'],pkt['packet_digest'],t,row['trade_id'],row['lot_id'],str(rp),stable(rec)],'receipt_id',rec['receipt_id'])
  action=(pkt.get('axes',{}).get('advisory_action') or {}).get('action');ae=sha({'run':run_id,'packet':pkt['packet_id'],'action':action});event={'timestamp':built,'nyse_session':session,'run_id':run_id,'execution_context':execution_context,'unit':'PACKET_PUBLICATION','entrypoint':'atlas_holding_state_truth_maintenance.refresh','ticker':t,'trade_id':row['trade_id'],'lot_id':row['lot_id'],'action':action,'packet_id':pkt['packet_id'],'packet_digest':pkt['packet_digest']};truth.execute("INSERT OR IGNORE INTO canonical_action_ledger VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(ae,built,session,run_id,execution_context,'PACKET_PUBLICATION','atlas_holding_state_truth_maintenance.refresh',t,row['trade_id'],row['lot_id'],action,pkt['packet_id'],pkt['packet_digest'],stable(event)));results.append({'ticker':t,'trade_id':row['trade_id'],'lot_id':row['lot_id'],'packet_id':pkt['packet_id'],'packet_digest':pkt['packet_digest'],'receipt_id':rec['receipt_id'],'receipt_usability':rec['usability'],'action':action,'price_roles':pkt['price_roles'],'canonical_levels':pkt['canonical_levels']})
 # Closed LASR lifecycle evidence is append-only and excluded from current index.
 for x in closed:
  ev={'classification':'BROKER_AUTO_STOP_TRIGGER','trade_id':x['trade_id'],'lot_id':x['lot_id'],'ticker':'LASR','trade_status':x['status'],'lot_status':x['lot_status'],'broker_reference':x.get('broker_ref'),'exit_at':x.get('exit_at'),'exit_price':x.get('exit_price'),'exit_event_id':x.get('exit_event_id'),'current_open_projection':False};eid=sha(ev);truth.execute("INSERT OR IGNORE INTO lifecycle_evidence VALUES(?,?,?,?,?,?,?,?,?,?)",(eid,'LASR',x['trade_id'],x['lot_id'],'BROKER_AUTO_STOP_TRIGGER',x.get('broker_ref'),stable(ev),run_id,session,built))
 default_key=next(iter(packet_index),None);default_packet=readj(packet_index[default_key]['path']) if default_key else {};default_current={'trade_lot_binding_digest':(default_packet.get('provenance') or {}).get('trade_lot_binding_digest'),'broker_lifecycle_digest':(default_packet.get('provenance') or {}).get('broker_lifecycle_digest'),'calendar_digest':(default_packet.get('provenance') or {}).get('governed_calendar_digest'),'component_freshness':{'DAILY':'FRESH','PP':'FRESH'},'component_stale':False,'retention_valid':True,'price_role_usability':{'display':True,'valuation':True,'stop_evaluation':True,'target_evaluation':True}};current_path=base/'current_generations'/(run_id+'.json');atomic_json(current_path,default_current)
 empty_open_set=len(results)==1 and results[0]['ticker']=='EMPTY_OPEN_SET'
 manifest={'schema_version':'atlas.runtime_manifest.v3','mode':'shadow','units':sorted(UNITS),'canonical_unlocked':False,'generation_id':sha({'run':run_id,'packets':packet_index,'receipts':receipt_index}),'previous_generation_id':None,'publication_sequence':0,'packets':packet_index,'receipts':receipt_index,'default_packet_key':default_key,'current':{'path':str(current_path),'digest':digest(default_current)},'build':{'component_paths':[],'normalized_inputs_path':None,'packet_store':str(base/'packets/json'),'lease_path':str(base/'rebuild/leases/build.lock'),'empty_open_set_packet_path':str(packet_index[default_key]['path']) if empty_open_set else None},'rebuild_queue':str(base/'rebuild/queue'),'truth_db':str(truth_db()),'built_at':built,'nyse_session':session,'run_id':run_id,'execution_context':execution_context,'broker_order_state':'UNVERIFIED'}
 old=None
 try:old=readj(pointer_path().resolve()) if pointer_path().exists() else None
 except Exception:old=None
 if old:manifest['previous_generation_id']=old.get('generation_id');manifest['publication_sequence']=int(old.get('publication_sequence') or 0)+1
 manifest['manifest_digest']=digest({k:v for k,v in manifest.items() if k!='manifest_digest'});mp=base/'manifests'/('holding_state_runtime_shadow_'+run_id+'.json');atomic_json(mp,manifest);swap_pointer(mp)
 bypass=base/'events'/('bypass_sentinel_'+run_id+'.json');atomic_json(bypass,{'run_id':run_id,'timestamp':built,'nyse_session':session,'execution_context':execution_context,'status':'CLEAN','events':[]})
 sb={'timestamp':built,'nyse_session':session,'run_id':run_id,'execution_context':execution_context,'external_authority_selected':'legacy','canonical_internal':True,'canonical_owner_sends':0};sid=sha(sb);truth.execute("INSERT OR IGNORE INTO send_boundary_evidence VALUES(?,?,?,?,?,?,?,?,?)",(sid,built,session,run_id,execution_context,'legacy',1,0,stable(sb)));att={'manifest_path':str(mp),'pointer':str(pointer_path()),'bypass_artifact':str(bypass),'broker_order_state':'UNVERIFIED'};truth.execute("INSERT OR REPLACE INTO run_attestations VALUES(?,?,?,?,?,?,?,?)",(run_id,built,session,execution_context,1,'UNVERIFIED',str(mp),stable(att)));truth.commit();pdb.commit();rdb.commit();truth.close();pdb.close();rdb.close()
 empty_open_set=len(results)==1 and results[0]['ticker']=='EMPTY_OPEN_SET'
 return {'status':'PASS' if (empty_open_set or (len(results)==4 and all(x['receipt_usability']=='USABLE' for x in results))) else 'DATA_INCOMPLETE','run_id':run_id,'session':session,'execution_context':execution_context,'reason':reason,'manifest_path':str(mp),'manifest_pointer':str(pointer_path()),'manifest_digest':manifest['manifest_digest'],'empty_open_set':empty_open_set,'open_set':[] if empty_open_set else [x['ticker'] for x in results],'packets':results,'lasr_closed_evidence':closed,'bypass_artifact':str(bypass),'send_boundary':sb,'truth_db':str(truth_db()),'source_paths':{'daily':str(daily_path()),'snapshot':str(sp) if sp else None,'profit_protection':str(ppfile) if ppfile else None},'broker_order_state':'UNVERIFIED'}
def refresh_if_needed(*,reason='CONSUMER_PRE_DISPATCH',execution_context=None,run_id=None):
 ctx=execution_context or os.environ.get('ATLAS_EXECUTION_CONTEXT','LIVE_SCHEDULER');return refresh(reason=reason,execution_context=ctx,run_id=run_id)
def governed_refresh_once(*,reason,run_id=None,trigger='BROKEN_RUNTIME_POINTER',context=None):
 """One fail-closed canonical refresh attempt with a durable machine receipt."""
 rid=run_id or uuid.uuid4().hex; out=base_path()/'receipts/hygiene'/('canonical_hygiene_'+rid+'.json'); attempted=0
 body={'schema':'atlas.canonical_hygiene_refresh.v1','run_id':rid,'trigger':trigger,'reason':reason,'attempt_count':1,'context':context or {},'started_at':nowz()}
 try:
  attempted+=1; result=refresh(reason=reason,execution_context=os.environ.get('ATLAS_EXECUTION_CONTEXT','LIVE_SCHEDULER'),run_id=rid)
  from atlas_holding_state_packet_builder import verify_runtime_manifest
  verified=verify_runtime_manifest(result['manifest_path'])
  if not verified.get('default_packet_key') or not (verified.get('packets') or {}).get(verified['default_packet_key']): raise RuntimeError('CANONICAL_POINTER_REPAIRED_MANIFEST_INVALID')
  body.update(status='PASS',failure_name=None,manifest_path=result['manifest_path'],generation_id=verified.get('generation_id'),default_packet_key=verified.get('default_packet_key'),completed_at=nowz())
  atomic_json(out,body); return {**result,'hygiene_receipt_path':str(out)}
 except Exception as exc:
  body.update(status='FAIL',failure_name='CANONICAL_HYGIENE_REFRESH_FAILED',reason_code=str(exc) or type(exc).__name__,exception_type=type(exc).__name__,completed_at=nowz())
  try: atomic_json(out,body)
  finally: raise RuntimeError('CANONICAL_HYGIENE_REFRESH_FAILED:'+str(out)) from exc
def ensure_current_manifest(*,reason='CONSUMER_PRE_DISPATCH'):
 """Refresh current truth before live consumers; test/dry-run contexts are inert."""
 ctx=os.environ.get('ATLAS_EXECUTION_CONTEXT','LIVE_SCHEDULER')
 if ctx in {'DEPLOYMENT_SMOKE','DRY_RUN','HISTORICAL_REPLAY','INTERNAL_PROBE'} or os.environ.get('ATLAS_TRUTH_REFRESH_DISABLE')=='1':
  return os.environ.get('ATLAS_HOLDING_STATE_RUNTIME_MANIFEST')
 result=governed_refresh_once(reason=reason,run_id=os.environ.get('ATLAS_RUN_ID'),trigger='CONSUMER_REFRESH')
 path=result.get('manifest_path')
 if path: os.environ['ATLAS_HOLDING_STATE_RUNTIME_MANIFEST']=path
 return path
def record_dispatch(*,unit,entrypoint,packet,legacy_action=None,canonical_action=None,owner_facing_send=False,execution_context=None,run_id=None,nyse_session=None):
 ctx=execution_context or os.environ.get('ATLAS_EXECUTION_CONTEXT','LIVE_SCHEDULER');rid=run_id or os.environ.get('ATLAS_RUN_ID') or uuid.uuid4().hex;ts=nowz();session=nyse_session or packet.get('completed_session') or dt.datetime.now(ET).date().isoformat();ti=packet.get('trade_identity') or {};canonical_action=canonical_action or ((packet.get('axes') or {}).get('advisory_action') or {}).get('action');base={'timestamp':ts,'nyse_session':session,'run_id':rid,'execution_context':ctx,'unit':unit,'entrypoint':entrypoint,'ticker':ti.get('ticker') or packet.get('ticker'),'trade_id':ti.get('trade_id') or packet.get('trade_id'),'lot_id':ti.get('lot_id') or packet.get('lot_id'),'legacy_action':legacy_action,'canonical_action':canonical_action,'packet_id':packet.get('packet_id'),'packet_digest':packet.get('packet_digest'),'external_authority_selected':'legacy','owner_facing_send':bool(owner_facing_send)};eid=sha(base);c=connect_truth();vals=(eid,ts,session,rid,ctx,unit,entrypoint,base['ticker'],base['trade_id'],base['lot_id'],legacy_action,canonical_action,base['packet_id'],base['packet_digest'],'legacy',int(bool(owner_facing_send)),stable(base));c.execute("INSERT OR IGNORE INTO dispatch_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals);c.execute("INSERT OR IGNORE INTO shadow_comparison_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals);ae=sha({'dispatch':eid,'canonical':canonical_action});c.execute("INSERT OR IGNORE INTO canonical_action_ledger VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(ae,ts,session,rid,ctx,unit,entrypoint,base['ticker'],base['trade_id'],base['lot_id'],canonical_action,base['packet_id'],base['packet_digest'],stable(base)));c.commit();c.close();return base
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--refresh',action='store_true');ap.add_argument('--reason',default='MANUAL_REFRESH');ap.add_argument('--execution-context',default='INTERNAL_PROBE',choices=sorted(CONTEXTS));ap.add_argument('--run-id');a=ap.parse_args(argv);print(json.dumps(refresh(reason=a.reason,execution_context=a.execution_context,run_id=a.run_id),indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
