#!/usr/bin/env python3
"""Observation-only deterministic machine receipts for one inherited Atlas cycle."""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3, tempfile
from pathlib import Path

SCHEMA="atlas.machine_cycle_receipt.v1"
ROOT=Path(os.environ.get("ATLAS_CYCLE_RECEIPT_ROOT","/Users/yasser/.hermes/profiles/atlasops/acceptance/machine_cycles"))
KINDS={"holdings_price","holdings_health","perme_strict","corporate_action","candidate_accounting","child_completion"}

def canon(o): return json.dumps(o,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False,default=str).encode()
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def cycle_id(): return os.environ.get("ATLAS_CYCLE_ID")
def cycle_dir(cid=None): return ROOT/(cid or cycle_id() or "NO_CYCLE")
def _safe(v):
 if isinstance(v,dict): return {str(k):_safe(x) for k,x in sorted(v.items()) if not any(s in str(k).lower() for s in ("token","secret","chat_id","credential","password"))}
 if isinstance(v,(list,tuple)): return [_safe(x) for x in v]
 if isinstance(v,(str,int,float,bool)) or v is None: return v
 return str(v)
def atomic_json(path,obj):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); os.chmod(path.parent,0o700)
 raw=canon(obj)+b"\n"; fd,tmp=tempfile.mkstemp(prefix="."+path.name+".",dir=path.parent)
 try:
  with os.fdopen(fd,"wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
  os.chmod(tmp,0o600); os.replace(tmp,path)
  dfd=os.open(path.parent,os.O_RDONLY)
  try: os.fsync(dfd)
  finally: os.close(dfd)
  if sha_file(path)!=sha_bytes(raw): raise OSError("ATOMIC_SHA_VERIFY_FAILED")
 finally:
  try: os.unlink(tmp)
  except FileNotFoundError: pass
 return sha_bytes(raw)
def record(kind,payload):
 """Never raises into business code. Duplicate singleton receipts are rejected as observer errors."""
 cid=cycle_id()
 if not cid or kind not in KINDS: return False
 try:
  d=cycle_dir(cid); d.mkdir(parents=True,exist_ok=True); os.chmod(d,0o700)
  if kind=="corporate_action":
   seq=len(list(d.glob("corporate_action.*.json")))+1; p=d/f"corporate_action.{seq:06d}.json"
  else: p=d/f"{kind}.json"
  if p.exists():
   atomic_json(d/f"observer_error.{kind}.json",{"schema":SCHEMA,"cycle_id":cid,"error":"DUPLICATE_RECEIPT_REJECTED","kind":kind})
   return False
  body={"schema":SCHEMA,"cycle_id":cid,"kind":kind,"payload":_safe(payload)}
  body["receipt_sha256"]=sha_bytes(canon(body))
  atomic_json(p,body); return True
 except Exception:
  return False

def record_holdings(packet,positions):
 rows=[]
 for h in packet.get("holdings") or []:
  pa=h.get("authoritative_price") or {}; broker=h.get("broker_confirmation_evidence") or {}
  rows.append({"ticker":h.get("ticker"),"trade_id":h.get("stop_event_trade_id") or next((p.get("id") or p.get("trade_id") for p in positions if str(p.get("ticker") or "").upper()==str(h.get("ticker") or "").upper()),None),"price":h.get("current_price"),"timestamp":h.get("price_source_timestamp"),"session":h.get("session"),"provider":pa.get("provider"),"source":h.get("current_price_source"),"event_id":h.get("stop_event_id"),"actionable":bool(pa.get("valuation_included")),"incomplete":h.get("final_action")=="DATA INCOMPLETE","entry":h.get("entry"),"stop":h.get("canonical_stop"),"target":h.get("canonical_target"),"broker_confirmation":{"status":h.get("broker_status"),"event_id":broker.get("event_id"),"source":broker.get("source")},"action":h.get("final_action")})
 packet_sha=sha_bytes(canon(packet)); rows_sha=sha_bytes(canon(rows))
 record("holdings_price",{"packet_version":packet.get("packet_version"),"packet_sha256":packet_sha,"header_packet_sha256":packet_sha,"detail_packet_sha256":packet_sha,"open_count":len(rows),"rows_sha256":rows_sha,"rows":rows})
 hp=packet.get("holdings_packet") or {}; src=hp.get("source"); sidecar=os.environ.get("ATLAS_HOLDINGS_REUNDERWRITE_SIDECAR","/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/db/holdings_reunderwrite.sqlite")
 integrity=None
 try:
  c=sqlite3.connect(f"file:{sidecar}?mode=ro",uri=True); integrity=c.execute("pragma integrity_check").fetchone()[0]; c.close()
 except Exception: integrity="UNAVAILABLE"
 record("holdings_health",{"source_version":"holdings_reunderwrite.v1","packet_id":hp.get("input_digest"),"packet_sha256":sha_file(src) if src and Path(src).is_file() else None,"run_date":hp.get("run_date"),"freshness":hp.get("freshness"),"action":"LOAD_EXISTING_ONLY","source":src,"sidecar_path":sidecar,"sidecar_integrity":integrity,"duplicate":False,"missing":hp.get("status")=="MISSING"})

def record_perme(summary):
 r=(summary or {}).get("macro_context_v1_receipt") or {}; path=os.environ.get("ATLAS_MACRO_CONTEXT_V1_PATH"); raw={}; artifact={}
 try:
  raw=json.loads(Path(path).read_text()) if path else {}; artifact=raw.get("artifact") or {}
 except Exception: pass
 consumed=[x for x in (r.get("consumed_field_paths") or []) if x=="$.macro_regime" or x=="$.event_risks" or x.endswith(".event_id")]
 envelope_sha=sha_file(path) if path and Path(path).is_file() else None
 record("perme_strict",{"envelope_path":path,"envelope_sha256":envelope_sha,"consumer_input_sha256":r.get("input_sha256"),"payload_path":artifact.get("path"),"payload_sha256":artifact.get("sha256"),"status":r.get("status"),"accepted":r.get("status")=="ACCEPTED","rejected":r.get("status")!="ACCEPTED","consumed_paths":consumed,"generated_at":raw.get("generated_at"),"ttl_minutes":(raw.get("freshness") or {}).get("ttl_minutes"),"schema":raw.get("schema")})

def record_accounting(summary):
 d=cycle_dir(); events=[]
 for p in sorted(d.glob("corporate_action.*.json")):
  try: events.append(json.loads(p.read_text())["payload"])
  except Exception: pass
 admission_events=[e for e in events if e.get("path")=="central_candidate_admission"]
 outcomes={x:sum(1 for e in admission_events if e.get("outcome")==x) for x in ("CLEAR","BLOCK","DEFER")}
 discovered=sorted(set(str(x).upper() for x in ((summary or {}).get("candidates") or []) if x))
 admitted=sorted(set(str(e.get("ticker") or "").upper() for e in admission_events))
 rejected=sorted(set(discovered)-set(admitted))
 total=len(admission_events)+len(rejected)
 record("candidate_accounting",{"discovery":discovered,"admission":admitted,"projection":sorted(set(str(x.get("ticker") or "").upper() for x in ((summary or {}).get("high_candidates") or []) if x.get("ticker"))),"write_choke":sorted(set(str(e.get("ticker") or "").upper() for e in events if e.get("path")=="final_automatic_trade_write")),"total":total,"clear":outcomes["CLEAR"],"block":outcomes["BLOCK"],"defer":outcomes["DEFER"],"rejected_before_gate":len(rejected),"rejected_before_gate_ids":rejected,"equation_holds":total==sum(outcomes.values())+len(rejected),"zero_candidate":total==0,"ca_receipt_count":len(events),"admission_receipt_count":len(admission_events)})

def db_health(path):
 try:
  c=sqlite3.connect(f"file:{path}?mode=ro",uri=True); x={"integrity":c.execute("pragma integrity_check").fetchone()[0],"fk_errors":len(c.execute("pragma foreign_key_check").fetchall()),"sha256":sha_file(path)}; c.close(); return x
 except Exception as e: return {"integrity":"ERROR","fk_errors":None,"error":type(e).__name__}

def verify_cycle(cid,require_envelope=False):
 d=cycle_dir(cid); errors=[]; objs={}
 for k in ("holdings_price","holdings_health","perme_strict","candidate_accounting","child_completion"):
  p=d/f"{k}.json"
  if not p.exists(): errors.append("MISSING_"+k.upper()); continue
  try:
   o=json.loads(p.read_text()); expected=o.pop("receipt_sha256");
   if sha_bytes(canon(o))!=expected: errors.append("HASH_"+k.upper())
   o["receipt_sha256"]=expected; objs[k]=o
  except Exception: errors.append("INVALID_"+k.upper())
 if list(d.glob("observer_error.*.json")): errors.append("OBSERVER_ERROR")
 a=(objs.get("candidate_accounting") or {}).get("payload") or {}
 if not a.get("equation_holds"): errors.append("ACCOUNTING_EQUATION")
 if a.get("ca_receipt_count")!=len(list(d.glob("corporate_action.*.json"))): errors.append("CA_COUNT")
 hp=(objs.get("holdings_price") or {}).get("payload") or {}
 if hp.get("packet_sha256")!=hp.get("header_packet_sha256") or hp.get("packet_sha256")!=hp.get("detail_packet_sha256"): errors.append("HOLDINGS_PACKET_LINK")
 perme=(objs.get("perme_strict") or {}).get("payload") or {}
 if perme.get("status")!="ACCEPTED" or perme.get("accepted") is not True or perme.get("rejected") is not False: errors.append("PERME_NOT_ACCEPTED")
 ep=perme.get("envelope_path"); envelope=None
 if not ep or not Path(ep).is_file() or sha_file(ep)!=perme.get("envelope_sha256") or perme.get("consumer_input_sha256")!=perme.get("envelope_sha256"):
  errors.append("PERME_ENVELOPE_SHA_LINK")
 else:
  try:
   envelope=json.loads(Path(ep).read_text())
   from atlas_macro_context_v1 import validate_machine_context
   generated_for_shape=dt.datetime.fromisoformat(str(envelope.get("generated_at")).replace("Z","+00:00"))
   validate_machine_context(envelope,now=generated_for_shape,artifact_path=perme.get("payload_path"))
  except Exception: errors.append("PERME_ENVELOPE_INVALID")
 artifact=(envelope or {}).get("artifact") or {}
 pp=perme.get("payload_path")
 if (not pp or not Path(pp).is_file() or sha_file(pp)!=perme.get("payload_sha256")
     or artifact.get("path")!=pp or artifact.get("sha256")!=perme.get("payload_sha256")):
  errors.append("PERME_PAYLOAD_SHA_LINK")
 freshness=(envelope or {}).get("freshness") or {}
 if ((envelope or {}).get("generated_at")!=perme.get("generated_at") or freshness.get("ttl_minutes")!=perme.get("ttl_minutes")):
  errors.append("PERME_FRESHNESS_LINK")
 if not {"$.macro_regime","$.event_risks"}.issubset(set(perme.get("consumed_paths") or [])): errors.append("PERME_UNCONSUMED")
 try:
  generated=dt.datetime.fromisoformat(str(perme.get("generated_at")).replace("Z","+00:00")); ttl=int(perme.get("ttl_minutes")); now=dt.datetime.now(dt.timezone.utc)
  if generated.tzinfo is None or now>generated.astimezone(dt.timezone.utc)+dt.timedelta(minutes=ttl): errors.append("PERME_STALE")
 except Exception: errors.append("PERME_FRESHNESS_INVALID")
 if require_envelope and not (d/"completion_envelope.json").exists(): errors.append("MISSING_ENVELOPE")
 return (not errors),sorted(errors),objs
