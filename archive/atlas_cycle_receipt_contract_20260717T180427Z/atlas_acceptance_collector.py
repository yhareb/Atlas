#!/usr/bin/env python3
"""Read-only Atlas acceptance evidence scanner with an INSERT-only SQLite ledger.

It never imports Atlas, starts a process, sends a message, or writes production data.
Historical evidence is accepted only when bounded by a scheduler start marker and the
next start marker. Missing machine receipts remain missing; report prose is not a
corporate-action receipt.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_EPOCH = Path('/tmp/atlas_corporate_action_gate_20260717T140852Z/release/atlas_corporate_action_gate_20260717/evidence/ACCEPTANCE_EPOCH.json')
DEFAULT_LOG = Path('/Users/yasser/scripts/atlas_intraday.log')
DEFAULT_DB = Path('/Users/yasser/scripts/atlas.db')
DEFAULT_STATE = Path('/Users/yasser/scripts/.atlas_ca_enforcement_state.json')
DEFAULT_LEDGER = Path('/Users/yasser/.hermes/profiles/atlasops/acceptance/final_acceptance.sqlite3')
DEFAULT_SIDECARS = Path('/Users/yasser/.hermes/profiles/atlasops/acceptance/cycle_completion_sidecars')
START = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] Atlas intraday loop starting\.\.\.$', re.M)
BODY_BEGIN = '[intraday] telegram report body begin'
BODY_END = '[intraday] telegram report body end'
DELIVERY = re.compile(r'^\[intraday\] telegram report success=(True|False)$', re.M)
MSG_RECEIPT = re.compile(r'^\[atlas\] telegram report sent: chunks=(\d+) message_ids=\[([^]]*)\]$', re.M)
CA_PROSE = re.compile(r'CORPORATE_ACTION_(?:CLEAR|BLOCK|DEFER):[^\n]+')


def sha_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def connect_ledger(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True); os.chmod(path.parent, 0o700)
    c=sqlite3.connect(path)
    c.executescript('''
      PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
      CREATE TABLE IF NOT EXISTS cycles(
        cycle_id TEXT PRIMARY KEY, epoch_utc TEXT NOT NULL, scheduled_utc TEXT NOT NULL,
        started_utc TEXT NOT NULL, ended_utc TEXT, pid INTEGER, classification TEXT NOT NULL
          CHECK(classification IN ('PASS','FAIL','UNPROVABLE')),
        reason TEXT NOT NULL, report_receipt_json TEXT, holdings_receipt_json TEXT,
        perme_receipt_json TEXT, corporate_action_receipt_count INTEGER NOT NULL,
        corporate_action_candidate_count INTEGER NOT NULL, exit_code INTEGER,
        db_health_json TEXT, lock_overlap_json TEXT NOT NULL, artifact_json TEXT NOT NULL,
        inserted_utc TEXT NOT NULL
      );
      CREATE TRIGGER IF NOT EXISTS cycles_no_update BEFORE UPDATE ON cycles
        BEGIN SELECT RAISE(ABORT,'append-only ledger: UPDATE forbidden'); END;
      CREATE TRIGGER IF NOT EXISTS cycles_no_delete BEFORE DELETE ON cycles
        BEGIN SELECT RAISE(ABORT,'append-only ledger: DELETE forbidden'); END;
      CREATE TABLE IF NOT EXISTS cycle_validations_v2(
        epoch_utc TEXT NOT NULL, cycle_id TEXT NOT NULL,
        classification TEXT NOT NULL CHECK(classification IN ('PASS','FAIL')),
        reason TEXT NOT NULL, sidecar_path TEXT NOT NULL, sidecar_sha256 TEXT NOT NULL,
        completed_observed_utc TEXT NOT NULL, emitted_utc TEXT NOT NULL,
        inserted_utc TEXT NOT NULL, evidence_json TEXT NOT NULL,
        PRIMARY KEY(epoch_utc,cycle_id)
      );
      CREATE TRIGGER IF NOT EXISTS cycle_validations_v2_no_update BEFORE UPDATE ON cycle_validations_v2
        BEGIN SELECT RAISE(ABORT,'append-only ledger: UPDATE forbidden'); END;
      CREATE TRIGGER IF NOT EXISTS cycle_validations_v2_no_delete BEFORE DELETE ON cycle_validations_v2
        BEGIN SELECT RAISE(ABORT,'append-only ledger: DELETE forbidden'); END;
    ''')
    c.commit(); os.chmod(path,0o600)
    return c

def ro_db_health(path: Path) -> dict:
    c=sqlite3.connect(f'file:{path}?mode=ro&immutable=1',uri=True)
    try:
        return {'observed_only_not_cycle_bound':True,
                'integrity':c.execute('pragma integrity_check').fetchone()[0],
                'fk_errors':len(c.execute('pragma foreign_key_check').fetchall()),
                'path':str(path),'sha256':sha_file(path)}
    finally: c.close()

def local_tz() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or ZoneInfo('UTC')

def scan(args: argparse.Namespace) -> list[dict]:
    epoch_obj=json.loads(args.epoch.read_text()); epoch=dt.datetime.fromisoformat(epoch_obj['not_before_utc'])
    raw=args.log.read_bytes(); text=raw.decode('utf-8','replace'); starts=list(START.finditer(text)); out=[]
    state=json.loads(args.state.read_text())
    if state.get('mode')!='BLOCK_NEW_TRADES' or state.get('unlock_receipt_sha256') is not None:
        raise SystemExit('ACCEPTANCE_STATE_NOT_BLOCKED')
    dbh=ro_db_health(args.production_db)
    tz=local_tz()
    for i,m in enumerate(starts):
        naive=dt.datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S')
        started=naive.replace(tzinfo=tz).astimezone(dt.timezone.utc)
        if started < epoch or started.date()!=epoch.date(): continue
        end=starts[i+1].start() if i+1<len(starts) else len(text)
        block=text[m.start():end]
        delivery=list(DELIVERY.finditer(block)); body_begin=block.count(BODY_BEGIN); body_end=block.count(BODY_END)
        # An unclosed current cycle is not ledgered yet.
        if not delivery and i+1==len(starts): continue
        delivered=bool(delivery and delivery[-1].group(1)=='True')
        report_start=block.find(BODY_BEGIN); report_end=block.find(BODY_END)
        report_bytes=(block[report_start:report_end+len(BODY_END)].encode() if report_start>=0 and report_end>report_start else b'')
        msg=MSG_RECEIPT.search(block)
        report_receipt={'complete':body_begin==1 and body_end==1,'delivered':delivered,
          'body_sha256':sha_bytes(report_bytes) if report_bytes else None,
          'chunks':int(msg.group(1)) if msg else None,
          'delivery_artifact_present':bool(msg)}
        ca_candidates=CA_PROSE.findall(block)
        # These lines are human/log prose: they intentionally do not count as machine receipts.
        missing=[]
        if not report_receipt['complete'] or not delivered: missing.append('complete_report_delivery_receipt')
        missing += ['historical_pid','process_exit_code','authoritative_holdings_price_machine_receipt',
                    'holdings_reevaluation_health_machine_receipt','perme_strict_context_machine_receipt',
                    'corporate_action_machine_receipt_per_evaluated_new_buy_candidate',
                    'cycle_bound_db_integrity_fk_receipt','cycle_bound_lock_overlap_receipt']
        classification='UNPROVABLE' if missing else 'PASS'
        scheduled=started.replace(second=0,microsecond=0)
        cycle_id='intraday-'+scheduled.strftime('%Y%m%dT%H%M%SZ')+'-'+sha_bytes(report_bytes)[:12]
        artifact={'log_path':str(args.log),'log_sha256_observed':sha_bytes(raw),
          'byte_start':m.start(),'byte_end':end,'cycle_block_sha256':sha_bytes(block.encode()),
          'state_path':str(args.state),'state_sha256':sha_file(args.state),
          'ca_prose_events_not_receipts':ca_candidates}
        out.append({'cycle_id':cycle_id,'epoch_utc':epoch.isoformat(),'scheduled_utc':scheduled.isoformat(),
          'started_utc':started.isoformat(),'ended_utc':None,'pid':None,'classification':classification,
          'reason':'MISSING:'+','.join(missing) if missing else 'ALL_REQUIRED_EVIDENCE_CYCLE_BOUND',
          'report_receipt_json':json.dumps(report_receipt,sort_keys=True),'holdings_receipt_json':None,
          'perme_receipt_json':None,'corporate_action_receipt_count':0,
          'corporate_action_candidate_count':len(ca_candidates),'exit_code':None,
          'db_health_json':json.dumps(dbh,sort_keys=True),
          'lock_overlap_json':json.dumps({'cycle_bound':False,'overlap':None,'lock_health':None},sort_keys=True),
          'artifact_json':json.dumps(artifact,sort_keys=True),
          'inserted_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
    return out

def import_sidecars(c: sqlite3.Connection, directory: Path) -> tuple[int,list]:
    inserted=0
    if not directory.exists(): return inserted,[]
    for path in sorted(directory.glob('intraday-*.json')):
        raw=path.read_bytes(); o=json.loads(raw)
        if o.get('schema')!='atlasops_non_authoritative_cycle_completion_v1': continue
        classification=o.get('classification')
        if classification not in ('PASS','FAIL'): raise SystemExit(f'INVALID_SIDECAR_CLASSIFICATION:{path}')
        statuses=o.get('receipt_status') or {}
        exact_missing=[k+':'+v for k,v in statuses.items() if v!='PRESENT_AND_LINKED']
        expected='FAIL' if exact_missing else 'PASS'
        if classification!=expected: raise SystemExit(f'SIDECAR_CLASSIFICATION_MISMATCH:{path}')
        reason='EXACT_MISSING_OR_UNLINKED:'+','.join(exact_missing) if exact_missing else 'ALL_REQUIRED_RECEIPTS_PRESENT_AND_LINKED'
        # The sidecar producer may emit the same exact status set in a stable
        # domain-specific order.  Verify semantic equality instead of brittle
        # string ordering while preserving collector-computed canonical reason.
        supplied_reason=o.get('reason')
        prefix='EXACT_MISSING_OR_UNLINKED:'
        if exact_missing:
            if not isinstance(supplied_reason,str) or not supplied_reason.startswith(prefix):
                raise SystemExit(f'SIDECAR_REASON_MISMATCH:{path}')
            supplied_items=supplied_reason[len(prefix):].split(',')
            if len(supplied_items)!=len(exact_missing) or set(supplied_items)!=set(exact_missing):
                raise SystemExit(f'SIDECAR_REASON_MISMATCH:{path}')
        elif supplied_reason!=reason:
            raise SystemExit(f'SIDECAR_REASON_MISMATCH:{path}')
        row=(o['epoch_utc'],o['cycle_id'],classification,reason,str(path),sha_bytes(raw),
             o['completed_observed_utc'],o['emitted_utc'],dt.datetime.now(dt.timezone.utc).isoformat(),
             json.dumps(o,sort_keys=True))
        before=c.total_changes
        c.execute('INSERT OR IGNORE INTO cycle_validations_v2 VALUES(?,?,?,?,?,?,?,?,?,?)',row)
        inserted += c.total_changes-before
    rows=c.execute('select cycle_id,classification,reason,emitted_utc,inserted_utc from cycle_validations_v2 order by emitted_utc').fetchall()
    return inserted,rows

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--epoch',type=Path,default=DEFAULT_EPOCH)
    p.add_argument('--log',type=Path,default=DEFAULT_LOG); p.add_argument('--production-db',type=Path,default=DEFAULT_DB)
    p.add_argument('--state',type=Path,default=DEFAULT_STATE); p.add_argument('--ledger',type=Path,default=DEFAULT_LEDGER)
    p.add_argument('--sidecars',type=Path,default=DEFAULT_SIDECARS)
    p.add_argument('--sidecars-only',action='store_true',help='fast post-completion import; do not rescan historical log')
    p.add_argument('--from-scheduled-utc',help='optional exact lower bound, ISO-8601')
    a=p.parse_args(); rows=[] if a.sidecars_only else scan(a)
    if a.from_scheduled_utc:
        low=dt.datetime.fromisoformat(a.from_scheduled_utc); rows=[r for r in rows if dt.datetime.fromisoformat(r['scheduled_utc'])>=low]
    c=connect_ledger(a.ledger); inserted=0
    try:
        for r in rows:
            cols=','.join(r); qs=','.join('?' for _ in r)
            before=c.total_changes; c.execute(f'INSERT OR IGNORE INTO cycles({cols}) VALUES({qs})',tuple(r.values()))
            inserted += c.total_changes-before
        validation_inserted,validation_rows=import_sidecars(c,a.sidecars)
        c.commit(); c.execute('pragma wal_checkpoint(FULL)')
        summary={'ledger':str(a.ledger),'discovered':len(rows),'inserted':inserted,
          'rows':c.execute('select cycle_id,scheduled_utc,classification,reason from cycles order by scheduled_utc').fetchall(),
          'validation_inserted':validation_inserted,'validation_rows':validation_rows}
        print(json.dumps(summary,sort_keys=True))
    finally: c.close()
    return 0
if __name__=='__main__': raise SystemExit(main())
