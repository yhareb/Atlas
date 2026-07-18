"""ORDER #38 atomic broker registration, audit state and reversible commands."""
from __future__ import annotations
import hashlib,json,sqlite3,uuid
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from atlas_registration_gate import canonical_decimal,packet_digest

Q=Decimal('0.01'); QS=100_000_000; PS=1_000_000
now=lambda:datetime.now(timezone.utc).isoformat()
def jid(prefix): return prefix+'-'+uuid.uuid4().hex
def canon(o): return json.dumps(o,sort_keys=True,separators=(',',':'),default=str)
def sha(o): return hashlib.sha256((o if isinstance(o,bytes) else canon(o).encode())).hexdigest()
def cents(x): return int((Decimal(str(x))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def scaled(x): return int(Decimal(str(x))*QS)
def micros(x): return int(Decimal(str(x))*PS)

def _addcol(c,t,n,ddl):
    if n not in {r[1] for r in c.execute(f'PRAGMA table_info({t})')}: c.execute(f'ALTER TABLE {t} ADD COLUMN {n} {ddl}')
def migrate(conn):
    c=conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS broker_registrations(
      registration_id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL,source_path TEXT NOT NULL,artifact_dir TEXT NOT NULL,parser_version TEXT NOT NULL,
      broker TEXT NOT NULL,broker_ref TEXT NOT NULL,side TEXT NOT NULL,ticker TEXT NOT NULL,quantity_text TEXT NOT NULL,price_text TEXT NOT NULL,fees_text TEXT NOT NULL,
      currency TEXT NOT NULL,execution_at TEXT NOT NULL,gate_receipt_json TEXT NOT NULL,trade_id INTEGER,closed_trade_id INTEGER,lot_id INTEGER,ladder_stage TEXT,
      instruction_digest TEXT,audit_status TEXT NOT NULL CHECK(audit_status IN('PENDING_AUDIT','MATCHED','DATA_INCOMPLETE','CONFIRMED_BY_PROF','UNDONE','SUPERSEDED')),
      audit_reason TEXT,supersedes_registration_id TEXT,pre_write_json TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
      UNIQUE(source_sha256,broker,broker_ref,side));
    CREATE TABLE IF NOT EXISTS broker_registration_audits(
      audit_id TEXT PRIMARY KEY,registration_id TEXT NOT NULL,auditor_profile TEXT NOT NULL,auditor_model TEXT NOT NULL,request_sha256 TEXT NOT NULL,response_sha256 TEXT,
      observed_json TEXT,comparison_json TEXT,status TEXT NOT NULL,error_code TEXT,started_at TEXT NOT NULL,completed_at TEXT,
      FOREIGN KEY(registration_id) REFERENCES broker_registrations(registration_id));
    CREATE TABLE IF NOT EXISTS broker_registration_commands(
      command_id TEXT PRIMARY KEY,registration_id TEXT NOT NULL,command TEXT NOT NULL,command_payload_json TEXT NOT NULL,result_json TEXT NOT NULL,
      professor_authenticated INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(registration_id,command,command_payload_json));
    CREATE TABLE IF NOT EXISTS registration_alert_queue(
      alert_id TEXT PRIMARY KEY,registration_id TEXT,media_path TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,created_at TEXT NOT NULL,delivered_at TEXT);
    CREATE TABLE IF NOT EXISTS broker_exit_instructions(
      instruction_id TEXT PRIMARY KEY,trade_id INTEGER NOT NULL,ticker TEXT NOT NULL,stage TEXT NOT NULL,quantity_text TEXT NOT NULL,packet_digest TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'OUTSTANDING',created_at TEXT NOT NULL,consumed_registration_id TEXT);
    CREATE TABLE IF NOT EXISTS broker_support_state(
      broker TEXT PRIMARY KEY,state TEXT NOT NULL,reason TEXT NOT NULL,updated_at TEXT NOT NULL,event_id INTEGER);
    """)
    for t in ('trades','cash_ledger','portfolio_event_journal','position_lots','broker_position_display_snapshots','exit_policy_events'):
        _addcol(c,t,'registration_id','TEXT')
    _addcol(c,'trades','quantity_text','TEXT')
    _addcol(c,'trades','registration_effect_status','TEXT')
    _addcol(c,'position_lots','entry_atr14','TEXT')
    _addcol(c,'position_lots','registration_effect_status','TEXT')
    conn.commit()

def retire_wio(conn, reason='WIO position fully closed'):
    """Persist the one-way WIO retirement state and immutable event."""
    c=conn.cursor(); c.execute('BEGIN IMMEDIATE')
    old=c.execute("SELECT state,event_id FROM broker_support_state WHERE broker='WIO_LEGACY'").fetchone()
    if old and old[0]=='RETIRED': conn.rollback(); return {'state':'RETIRED','event_id':old[1],'idempotent':True}
    ev=_event(c,'WIO_SUPPORT_RETIRED','SYNA',{'state':'RETIRED','reason':reason},'WIO-RETIREMENT',key='wio-retired')
    c.execute("INSERT OR REPLACE INTO broker_support_state VALUES('WIO_LEGACY','RETIRED',?,?,?)",(reason,now(),ev)); conn.commit()
    return {'state':'RETIRED','event_id':ev,'idempotent':False}

def wio_is_retired(conn):
    row=conn.execute("SELECT state FROM broker_support_state WHERE broker='WIO_LEGACY'").fetchone()
    return bool(row and row[0]=='RETIRED')

def _checkpoint(fault,name):
    if fault==name: raise RuntimeError('FAULT_INJECTED:'+name)
def _cash(c,amount,reason,reg):
    row=c.execute('SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1').fetchone()
    bal=Decimal(str(row[0])) if row else Decimal(str((c.execute('SELECT starting_cash FROM account WHERE id=1').fetchone() or [0])[0]))
    amount=Decimal(amount).quantize(Q,rounding=ROUND_HALF_UP); bal=(bal+amount).quantize(Q)
    c.execute('INSERT INTO cash_ledger(amount,reason,balance_after,registration_id) VALUES(?,?,?,?)',(str(amount),reason,str(bal),reg)); return c.lastrowid

def _event(c,typ,ticker,payload,reg,trade=None,cash=None,lot=None,key=None,sup=None,rev=None):
    # The legacy journal has a closed CHECK enum. Preserve the exact ORDER #38
    # semantic type in the immutable payload while using its accepted envelope.
    legacy_allowed={'ACCOUNT_OPENED','BUY_DECISION','BROKER_BUY_FILLED','SELL_DECISION','BROKER_SELL_FILLED','STOP_HIT_DETECTED','CASH_DEBIT_POSTED','CASH_CREDIT_POSTED','MANUAL_CORRECTION','RECONCILIATION_EXCEPTION','REVERSAL','VALUATION_MARK_RECORDED','IDEMPOTENT_DUPLICATE_REJECTED','BROKER_SELL_SUBMITTED','PROFESSOR_HOLD_OVERRIDE_ACTIVE','PROFESSOR_HOLD_OVERRIDE_DEACTIVATED'}
    envelope=typ if typ in legacy_allowed else ('REVERSAL' if 'UNDONE' in typ else 'MANUAL_CORRECTION')
    material=dict(payload or {}); material['semantic_event_type']=typ
    stamp=now(); c.execute("""INSERT INTO portfolio_event_journal(event_type,ticker,lot_id,occurred_at,effective_at,payload_json,source,evidence_id,prof_approved,idempotency_key,legacy_trades_id,legacy_cash_ledger_id,supersedes_id,linked_reversal_id,registration_id)
    VALUES(?,?,?,?,?,?, 'atlas_registration',NULL,0,?,?,?,?,?,?)""",(envelope,ticker,lot,stamp,stamp,canon(material),key,trade,cash,sup,rev,reg)); return c.lastrowid

def _post(c,event,account,amount,reason,cash=None):
    c.execute("INSERT INTO ledger_postings(event_id,account,posting_kind,amount_cents,reason,legacy_cash_ledger_id) VALUES(?,?,'PRINCIPAL',?,?,?)",(event,account,int(amount),reason,cash))

def _insert_registration(c,p,gate,reg,pre=None,supersedes=None):
    d=p.canonical(); stamp=now()
    c.execute("""INSERT INTO broker_registrations(registration_id,source_sha256,source_path,artifact_dir,parser_version,broker,broker_ref,side,ticker,quantity_text,price_text,fees_text,currency,execution_at,gate_receipt_json,ladder_stage,instruction_digest,audit_status,supersedes_registration_id,pre_write_json,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING_AUDIT',?,?,?,?)""",(reg,d['source_sha256'],d['source_path'],d['artifact_dir'],d['parser_version'],d['broker'],d['broker_ref'],d['side'],d['ticker'],d['quantity_text'],d['price_text'],d['fees_text'],d['currency'],d['execution_at'],canon(gate),d.get('stage'),d.get('instruction_digest'),supersedes,canon(pre or {}),stamp,stamp))

def register_buy_atomic(conn,p,gate,*,fault=None,registration_id=None,supersedes=None,final_status=None,manage_transaction=True):
    if gate.get('status')!='PASS': raise ValueError('gate not PASS')
    reg=registration_id or jid('reg'); d=p.canonical(); qty,px,fee=map(Decimal,(d['quantity_text'],d['price_text'],d['fees_text'])); ep=p.entry_plan or {}
    c=conn.cursor()
    try:
      if manage_transaction: c.execute('BEGIN IMMEDIATE')
      _insert_registration(c,p,gate,reg,supersedes=supersedes); _checkpoint(fault,'registration')
      c.execute("""INSERT INTO trades(ticker,status,quantity,quantity_text,entry_price,entry_at,entry_fees,stop_loss,entry_atr14,target_price,broker_ref,notes,updated_at,registration_id)
      VALUES(?,'OPEN',?,?,?,?,?,?,?,?,?,?,?,?)""",(d['ticker'],str(qty),d['quantity_text'],str(px),d['execution_at'],str(fee),str(ep['stop_loss']),str(ep['entry_atr14']),str(ep['target_price']),d['broker_ref'],'Automatic broker registration',now(),reg)); trade=c.lastrowid; _checkpoint(fault,'trade')
      debit=-(qty*px+fee).quantize(Q,rounding=ROUND_HALF_UP); cash=_cash(c,debit,f"Broker buy {d['ticker']} {d['broker_ref']}",reg); _checkpoint(fault,'cash')
      event=_event(c,'BROKER_BUY_FILLED_AUTO',d['ticker'],{'quantity_text':d['quantity_text'],'price_text':d['price_text'],'fees_text':d['fees_text'],'source_sha256':d['source_sha256']},reg,trade,cash,key='reg-buy:'+reg); _checkpoint(fault,'journal')
      amount=abs(cents(debit)); _post(c,event,'CASH',-amount,'Buy cash',cash); _post(c,event,'POSITION:'+d['ticker'],amount,'Buy position',cash); _checkpoint(fault,'postings')
      c.execute("""INSERT INTO position_lots(ticker,status,quantity_text,quantity_scaled,quantity_scale,quantity_source,entry_price_micros,entry_price_decimal_text,entry_event_id,stop_loss_micros,stop_loss_decimal_text,target_price_micros,target_price_decimal_text,cost_basis_cents,cost_basis_source,currency,broker_quantity_text,broker_price_text,legacy_trades_id,entry_atr14,registration_id)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(d['ticker'],'OPEN',d['quantity_text'],scaled(qty),QS,'broker_fill',micros(px),d['price_text'],event,micros(ep['stop_loss']),canonical_decimal(ep['stop_loss']),micros(ep['target_price']),canonical_decimal(ep['target_price']),amount,'broker_amount',d['currency'],d['quantity_text'],d['price_text'],trade,canonical_decimal(ep['entry_atr14']),reg)); lot=c.lastrowid; _checkpoint(fault,'lot')
      disp=p.display or {}
      c.execute("INSERT INTO broker_position_display_snapshots(legacy_trades_id,lot_id,ticker,broker_ref,shares_text,shares_scaled,shares_scale,broker_entry_micros,broker_entry_text,source_filename,registration_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(trade,lot,d['ticker'],d['broker_ref'],d['quantity_text'],scaled(qty),QS,micros(px),d['price_text'],d['source_path'],reg)); snap=c.lastrowid; _checkpoint(fault,'snapshot')
      c.execute('UPDATE broker_registrations SET trade_id=?,lot_id=? WHERE registration_id=?',(trade,lot,reg));
      assert c.execute('SELECT SUM(amount_cents) FROM ledger_postings WHERE event_id=?',(event,)).fetchone()[0]==0
      assert Decimal(c.execute('SELECT quantity_text FROM position_lots WHERE id=?',(lot,)).fetchone()[0])==qty
      if final_status: c.execute('UPDATE broker_registrations SET audit_status=?,updated_at=? WHERE registration_id=?',(final_status,now(),reg))
      _checkpoint(fault,'reconcile')
      if manage_transaction: conn.commit()
      return {'registration_id':reg,'trade_id':trade,'lot_id':lot,'cash_ledger_id':cash,'event_id':event,'snapshot_id':snap,'reconciliation_digest':sha({'reg':reg,'trade':trade,'lot':lot,'cash':str(debit),'event':event})}
    except Exception:
      if manage_transaction: conn.rollback()
      raise

def register_sell_atomic(conn,p,gate,*,fault=None,registration_id=None,supersedes=None,final_status=None,manage_transaction=True):
    if gate.get('status')!='PASS': raise ValueError('gate not PASS')
    reg=registration_id or jid('reg'); d=p.canonical(); qty,px,fee=map(Decimal,(d['quantity_text'],d['price_text'],d['fees_text'])); c=conn.cursor()
    try:
      if manage_transaction: c.execute('BEGIN IMMEDIATE')
      tr=c.execute("SELECT ticker,status,quantity,COALESCE(quantity_text,quantity),entry_price,entry_at,entry_fees,stop_loss,entry_atr14,target_price,notes FROM trades WHERE id=?",(p.trade_id,)).fetchone()
      lots=c.execute("SELECT id,quantity_text,quantity_scaled,cost_basis_cents,entry_event_id,entry_price_micros,entry_price_decimal_text,stop_loss_micros,stop_loss_decimal_text,target_price_micros,target_price_decimal_text FROM position_lots WHERE id=? AND legacy_trades_id=? AND status='OPEN'",(p.lot_id,p.trade_id)).fetchall()
      if not tr or tr[0]!=d['ticker'] or tr[1]!='OPEN' or len(lots)!=1: raise ValueError('exact OPEN trade/lot required')
      openq=Decimal(str(tr[3]));
      if qty>openq: raise ValueError('overfill')
      pre={'trade':list(tr),'lot':list(lots[0]),'open_quantity':str(openq)}; _insert_registration(c,p,gate,reg,pre,supersedes); _checkpoint(fault,'registration')
      remaining=openq-qty; entry=Decimal(str(tr[4])); entryfee=Decimal(str(tr[6] or 0)); soldfee=entryfee*qty/openq
      realized=(px-entry)*qty-soldfee-fee; rpct=realized/(entry*qty)*100
      if remaining:
       c.execute('UPDATE trades SET quantity=?,quantity_text=?,entry_fees=?,updated_at=? WHERE id=?',(str(remaining),canonical_decimal(remaining),str(entryfee-soldfee),now(),p.trade_id))
       c.execute("""INSERT INTO trades(ticker,status,quantity,quantity_text,entry_price,entry_at,exit_price,exit_at,entry_fees,exit_fees,realized_pnl,realized_pnl_pct,parent_id,stop_loss,entry_atr14,target_price,broker_ref,notes,updated_at,registration_id)
       VALUES(?,'CLOSED',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(d['ticker'],str(qty),d['quantity_text'],str(entry),tr[5],str(px),d['execution_at'],str(soldfee),str(fee),str(realized),str(rpct),p.trade_id,tr[7],tr[8],tr[9],d['broker_ref'],'Automatic partial sell',now(),reg)); closed=c.lastrowid
      else:
       c.execute("UPDATE trades SET status='CLOSED',exit_price=?,exit_at=?,exit_fees=?,realized_pnl=?,realized_pnl_pct=?,broker_ref=?,updated_at=?,registration_id=? WHERE id=?",(str(px),d['execution_at'],str(fee),str(realized),str(rpct),d['broker_ref'],now(),reg,p.trade_id)); closed=p.trade_id
      _checkpoint(fault,'trade')
      credit=(px*qty-fee).quantize(Q,rounding=ROUND_HALF_UP); cash=_cash(c,credit,f"Broker sell {d['ticker']} {d['broker_ref']}",reg); _checkpoint(fault,'cash')
      payload={'original_quantity':str(openq),'filled_quantity':d['quantity_text'],'remaining_quantity':canonical_decimal(remaining),'stage':d.get('stage'),'instruction_digest':d.get('instruction_digest')}
      ev=_event(c,'BROKER_SELL_FILLED',d['ticker'],payload,reg,closed,cash,p.lot_id,'reg-sell:'+reg); _checkpoint(fault,'journal')
      cashc=cents(credit); basis=(Decimal(lots[0][3])*qty/openq).quantize(Decimal('1'),rounding=ROUND_HALF_UP); pnl=cashc-int(basis)
      _post(c,ev,'CASH',cashc,'Sell cash',cash); _post(c,ev,'POSITION:'+d['ticker'],-int(basis),'Cost basis',cash); _post(c,ev,'REALIZED_PNL',-pnl,'Realized P/L',cash); _checkpoint(fault,'postings')
      if remaining:
       c.execute('UPDATE position_lots SET quantity_text=?,quantity_scaled=?,cost_basis_cents=?,last_rebuilt_at=? WHERE id=?',(canonical_decimal(remaining),scaled(remaining),lots[0][3]-int(basis),now(),p.lot_id))
       c.execute("""INSERT INTO position_lots(ticker,status,quantity_text,quantity_scaled,quantity_scale,quantity_source,entry_price_micros,entry_price_decimal_text,entry_event_id,exit_price_micros,exit_price_decimal_text,exit_event_id,stop_loss_micros,stop_loss_decimal_text,target_price_micros,target_price_decimal_text,cost_basis_cents,cost_basis_source,realized_pnl_cents,currency,legacy_trades_id,last_rebuilt_at,registration_id)
       VALUES(?,'CLOSED',?,?,?,'broker_fill',?,?,?,?,?,?,?,?,?,?,?,'broker_amount',?,'USD',?,?,?)""",(d['ticker'],d['quantity_text'],scaled(qty),QS,lots[0][5],lots[0][6],lots[0][4],micros(px),d['price_text'],ev,lots[0][7],lots[0][8],lots[0][9],lots[0][10],int(basis),pnl,closed,now(),reg))
      else:c.execute("UPDATE position_lots SET status='CLOSED',exit_price_micros=?,exit_price_decimal_text=?,exit_event_id=?,realized_pnl_cents=?,last_rebuilt_at=?,registration_id=? WHERE id=?",(micros(px),d['price_text'],ev,pnl,now(),reg,p.lot_id))
      _checkpoint(fault,'lot')
      semantic='BROKER_PARTIAL_SELL_FILLED' if remaining else 'BROKER_SELL_FILLED'
      c.execute("INSERT INTO exit_policy_events(event_type,trade_id,lot_id,stage,occurred_at,payload_json,idempotency_key,policy_version,registration_id) VALUES(?,?,?,?,?,?,?,'atlas_exit_policy.v1',?)",(semantic,p.trade_id,p.lot_id,d.get('stage'),d['execution_at'],canon(payload),'reg-policy:'+reg,reg))
      if d.get('stage'):
       c.execute("INSERT INTO exit_policy_events(event_type,trade_id,lot_id,stage,occurred_at,payload_json,idempotency_key,policy_version,registration_id) VALUES('EXIT_STAGE_COMPLETED',?,?,?,?,?,?,'atlas_exit_policy.v1',?)",(p.trade_id,p.lot_id,d['stage'],d['execution_at'],canon(payload),'reg-stage:'+reg,reg))
      if d.get('instruction_digest'): c.execute("UPDATE broker_exit_instructions SET status='CONSUMED',consumed_registration_id=? WHERE trade_id=? AND packet_digest=? AND status='OUTSTANDING'",(reg,p.trade_id,d['instruction_digest']))
      _checkpoint(fault,'exit_policy')
      c.execute('UPDATE broker_registrations SET trade_id=?,closed_trade_id=?,lot_id=? WHERE registration_id=?',(p.trade_id,closed,p.lot_id,reg))
      assert c.execute('SELECT SUM(amount_cents) FROM ledger_postings WHERE event_id=?',(ev,)).fetchone()[0]==0
      if final_status:c.execute('UPDATE broker_registrations SET audit_status=?,updated_at=? WHERE registration_id=?',(final_status,now(),reg))
      _checkpoint(fault,'reconcile')
      if manage_transaction: conn.commit()
      return {'registration_id':reg,'trade_id':p.trade_id,'closed_trade_id':closed,'lot_id':p.lot_id,'event_id':ev,'cash_ledger_id':cash,'remaining_quantity':canonical_decimal(remaining),'reconciliation_digest':sha(payload)}
    except Exception:
      if manage_transaction: conn.rollback()
      raise

def registration_projection(c,reg):
    r=c.execute('SELECT ticker,side,quantity_text,price_text,execution_at,broker FROM broker_registrations WHERE registration_id=?',(reg,)).fetchone()
    if not r: raise ValueError('registration not found')
    return {'ticker':r[0],'side':r[1],'quantity_text':r[2],'price_text':r[3],'execution_date':r[4][:10],'broker':r[5]}

def apply_audit(conn,reg,audit,*,fault=None):
    c=conn.cursor(); c.execute('BEGIN IMMEDIATE')
    try:
      proj=registration_projection(c,reg); started=now(); aid=jid('audit'); req=sha({'schema':'BrokerVisionAuditV1','image_only':True,'registration_id':reg})
      observed=audit.get('observed') if isinstance(audit,dict) else None; error=audit.get('error_code') if isinstance(audit,dict) else 'MALFORMED'
      comparison={}; kind='UNAVAILABLE'
      if observed and not error:
       doubt=bool(audit.get('doubt')); cert=audit.get('field_certainty') or {}
       for k in proj:
        if k in ('quantity_text','price_text'):
         try: match=Decimal(str(proj[k]))==Decimal(str(observed.get(k)))
         except: match=False
        else: match=str(proj[k]).upper()==str(observed.get(k,'')).upper()
        comparison[k]={'registered':proj[k],'observed':observed.get(k),'match':match,'certainty':cert.get(k)}
       low=any(Decimal(str(cert.get(k,0)))<Decimal('.95') for k in proj)
       kind='DOUBT' if doubt or low else ('MATCH' if all(x['match'] for x in comparison.values()) else 'MISMATCH')
      status='MATCHED' if kind=='MATCH' else 'DATA_INCOMPLETE'; et='REGISTRATION_AUDIT_MATCHED' if kind=='MATCH' else ('REGISTRATION_AUDIT_DOUBT' if kind=='DOUBT' else ('REGISTRATION_AUDIT_MISMATCH' if kind=='MISMATCH' else 'REGISTRATION_AUDITOR_UNAVAILABLE'))
      raw=canon(audit) if isinstance(audit,dict) else str(audit)
      c.execute('INSERT INTO broker_registration_audits VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,reg,'atlas-registration-auditor','openai/gpt-5.6-sol',req,sha(raw),canon(observed) if observed else None,canon(comparison),kind,error,started,now())); _checkpoint(fault,'audit_row')
      c.execute('UPDATE broker_registrations SET audit_status=?,audit_reason=?,updated_at=? WHERE registration_id=?',(status,kind,now(),reg)); _checkpoint(fault,'audit_status')
      _event(c,et,proj['ticker'],{'audit_id':aid,'request_sha256':req,'response_sha256':sha(raw),'comparison':comparison},reg,key='audit:'+aid); _checkpoint(fault,'audit_event')
      conn.commit(); return {'audit_id':aid,'status':status,'kind':kind,'comparison':comparison,'silent':status=='MATCHED'}
    except Exception:
      conn.rollback(); raise

def professor_command(conn,reg,command,payload,*,authenticated,reply_bound,fault=None):
    if not authenticated or not reply_bound: raise PermissionError('authenticated Professor reply required')
    cmd=command.upper(); material=canon(payload or {})
    old=conn.execute('SELECT result_json FROM broker_registration_commands WHERE registration_id=? AND command=? AND command_payload_json=?',(reg,cmd,material)).fetchone()
    if old:return json.loads(old[0])|{'idempotent':True}
    c=conn.cursor(); c.execute('BEGIN IMMEDIATE')
    row=c.execute('SELECT audit_status,side,ticker,trade_id,closed_trade_id,lot_id,pre_write_json FROM broker_registrations WHERE registration_id=?',(reg,)).fetchone()
    if not row: conn.rollback(); raise ValueError('registration not found')
    status,side,ticker,trade,closed,lot,pre=row
    if status not in ('DATA_INCOMPLETE','PENDING_AUDIT'): conn.rollback(); raise ValueError('command invalid for status')
    try:
      if cmd=='CONFIRM':
       c.execute("UPDATE broker_registrations SET audit_status='CONFIRMED_BY_PROF',updated_at=? WHERE registration_id=?",(now(),reg)); _checkpoint(fault,'command_effect')
       _event(c,'REGISTRATION_CONFIRMED_BY_PROF',ticker,{},reg,trade=trade,key='confirm:'+reg); result={'status':'CONFIRMED_BY_PROF','economic_mutation':False}
      elif cmd=='UNDO': result=_undo_in_tx(c,reg,row,fault=fault)
      else: raise ValueError('unsupported command')
      _checkpoint(fault,'command_event')
      cid=jid('cmd'); c.execute('INSERT INTO broker_registration_commands VALUES(?,?,?,?,?,?,?)',(cid,reg,cmd,material,canon(result),1,now())); _checkpoint(fault,'command_row')
      conn.commit(); return result|{'command_id':cid}
    except Exception:
      conn.rollback(); raise

def correct_registration(conn,reg,corrected_packet,gate,*,authenticated,reply_bound,fault=None):
    """Atomically reverse and reapply BUY or SELL with immutable lineage."""
    if not authenticated or not reply_bound: raise PermissionError('authenticated Professor reply required')
    if gate.get('status')!='PASS': raise ValueError('corrected gate not PASS')
    c=conn.cursor(); c.execute('BEGIN IMMEDIATE')
    try:
      row=c.execute('SELECT audit_status,side,ticker,trade_id,closed_trade_id,lot_id,pre_write_json FROM broker_registrations WHERE registration_id=?',(reg,)).fetchone()
      if not row or row[0] not in ('DATA_INCOMPLETE','PENDING_AUDIT'): raise ValueError('correction invalid for status')
      if row[1] != corrected_packet.side.upper(): raise ValueError('correction side must match original')
      reversal=_undo_in_tx(c,reg,row); _checkpoint(fault,'correct_reverse'); new_id=jid('reg')
      if row[1]=='BUY':
        created=register_buy_atomic(conn,corrected_packet,gate,registration_id=new_id,supersedes=reg,final_status='CONFIRMED_BY_PROF',manage_transaction=False)
      else:
        created=register_sell_atomic(conn,corrected_packet,gate,registration_id=new_id,supersedes=reg,final_status='CONFIRMED_BY_PROF',manage_transaction=False)
      _checkpoint(fault,'correct_reapply')
      c.execute("UPDATE broker_registrations SET audit_status='SUPERSEDED',updated_at=? WHERE registration_id=?",(now(),reg)); _checkpoint(fault,'correct_supersede')
      ev=_event(c,'REGISTRATION_CORRECTED',corrected_packet.ticker.upper(),{'original_registration_id':reg,'corrected_registration_id':new_id,'before':registration_projection(c,reg),'after':registration_projection(c,new_id)},new_id,trade=created['trade_id'],key='correct:'+reg)
      result={'status':'CORRECTED','original_status':'SUPERSEDED','new_status':'CONFIRMED_BY_PROF','new_registration_id':new_id,'reversal':reversal,'correction_event_id':ev}
      c.execute('INSERT INTO broker_registration_commands VALUES(?,?,?,?,?,?,?)',(jid('cmd'),reg,'CORRECT',canon(corrected_packet.canonical()),canon(result),1,now())); _checkpoint(fault,'correct_command')
      conn.commit(); return result
    except Exception:
      conn.rollback(); raise

def _undo_in_tx(c,reg,row,fault=None):
    status,side,ticker,trade,closed,lot,pre_raw=row; pre=json.loads(pre_raw or '{}')
    later=c.execute("SELECT COUNT(*) FROM broker_registrations WHERE trade_id=? AND registration_id<>? AND created_at>(SELECT created_at FROM broker_registrations WHERE registration_id=?) AND audit_status NOT IN('UNDONE','SUPERSEDED')",(trade,reg,reg)).fetchone()[0]
    if later: raise ValueError('later broker-confirmed child events exist')
    orig=c.execute("SELECT id,legacy_cash_ledger_id FROM portfolio_event_journal WHERE registration_id=? AND (event_type='BROKER_SELL_FILLED' OR json_extract(payload_json,'$.semantic_event_type')='BROKER_BUY_FILLED_AUTO') ORDER BY id LIMIT 1",(reg,)).fetchone()
    if not orig: raise ValueError('original economic event unavailable')
    amount=Decimal(str(c.execute('SELECT amount FROM cash_ledger WHERE id=?',(orig[1],)).fetchone()[0]))
    cash=_cash(c,-amount,'Registration reversal '+reg,reg); _checkpoint(fault,'undo_cash')
    ev=_event(c,'BROKER_REGISTRATION_UNDONE' if side=='BUY' else 'BROKER_SELL_REGISTRATION_UNDONE',ticker,{'reverses':reg},reg,trade,cash,lot,'undo:'+reg,sup=orig[0],rev=orig[0]); _checkpoint(fault,'undo_event')
    posts=c.execute('SELECT account,amount_cents FROM ledger_postings WHERE event_id=?',(orig[0],)).fetchall()
    for account,amt in posts:_post(c,ev,account,-amt,'Registration reversal',cash)
    _checkpoint(fault,'undo_postings')
    if side=='BUY':
      # Legacy CHECK enums cannot accept the reporting state. Close the rows and
      # persist the exact exclusion state in the additive authoritative column.
      c.execute("UPDATE trades SET status='CLOSED',registration_effect_status='VOIDED_BY_REGISTRATION_UNDO',updated_at=? WHERE registration_id=?",(now(),reg)); c.execute("UPDATE position_lots SET status='CLOSED',registration_effect_status='VOIDED_BY_REGISTRATION_UNDO',last_rebuilt_at=? WHERE registration_id=?",(now(),reg))
    else:
      tr=pre['trade']; lt=pre['lot'];
      c.execute("UPDATE trades SET status=?,quantity=?,quantity_text=?,entry_fees=?,exit_price=NULL,exit_at=NULL,exit_fees=0,realized_pnl=NULL,realized_pnl_pct=NULL,updated_at=? WHERE id=?",(tr[1],tr[2],tr[3],tr[6],now(),trade))
      if closed!=trade:c.execute("UPDATE trades SET status='CLOSED',registration_effect_status='REVERSED_BY_REGISTRATION_UNDO',updated_at=? WHERE id=?",(now(),closed))
      c.execute("UPDATE position_lots SET status='OPEN',quantity_text=?,quantity_scaled=?,cost_basis_cents=?,exit_event_id=NULL,realized_pnl_cents=NULL,last_rebuilt_at=? WHERE id=?",(lt[1],lt[2],lt[3],now(),lot)); c.execute("UPDATE position_lots SET status='CLOSED',registration_effect_status='REVERSED_BY_REGISTRATION_UNDO' WHERE registration_id=? AND id<>?",(reg,lot))
      c.execute("INSERT INTO exit_policy_events(event_type,trade_id,lot_id,stage,occurred_at,payload_json,idempotency_key,policy_version,registration_id) SELECT 'REVERSAL',trade_id,lot_id,stage,?, ?, 'undo-policy:'||id,'atlas_exit_policy.v1',? FROM exit_policy_events WHERE registration_id=?",(now(),canon({'reverses_registration':reg}),reg,reg)); c.execute("UPDATE broker_exit_instructions SET status='OUTSTANDING',consumed_registration_id=NULL WHERE consumed_registration_id=?",(reg,))
    _checkpoint(fault,'undo_restore')
    c.execute("UPDATE broker_registrations SET audit_status='UNDONE',updated_at=? WHERE registration_id=?",(now(),reg)); _checkpoint(fault,'undo_status'); return {'status':'UNDONE','reversal_event_id':ev,'reversal_cash_id':cash}

__all__=['migrate','register_buy_atomic','register_sell_atomic','apply_audit','professor_command','correct_registration','registration_projection','retire_wio','wio_is_retired']
