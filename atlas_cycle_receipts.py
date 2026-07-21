#!/usr/bin/env python3
"""Observation-only deterministic machine receipts for one inherited Atlas cycle."""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3, tempfile
from pathlib import Path

SCHEMA="atlas.machine_cycle_receipt.v1"
ROOT=Path(os.environ.get("ATLAS_CYCLE_RECEIPT_ROOT","/Users/yasser/.hermes/profiles/atlasops/acceptance/machine_cycles"))
KINDS={"holdings_price","holdings_health","perme_strict","corporate_action","candidate_accounting","child_completion","authority"}
AUTHORITY_SCHEMA="atlas.machine_authority_receipt.v1"
AUTHORITY_FLAGS=("holdings_price_healthy","holdings_reevaluation_healthy","perme_strict","ca_active_complete","tfe_sole_authority","llm_trading_authority_false","no_p0_p1")

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
 empty_open_set=not rows and not (positions or [])
 packet_sha=sha_bytes(canon(packet)); rows_sha=sha_bytes(canon(rows))
 record("holdings_price",{"packet_version":packet.get("packet_version"),"packet_sha256":packet_sha,"header_packet_sha256":packet_sha,"detail_packet_sha256":packet_sha,"open_count":len(rows),"empty_open_set":empty_open_set,"rows_sha256":rows_sha,"rows":rows})
 hp=packet.get("holdings_packet") or {}; src=hp.get("source"); sidecar=os.environ.get("ATLAS_HOLDINGS_REUNDERWRITE_SIDECAR","/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/db/holdings_reunderwrite.sqlite")
 integrity=None
 try:
  c=sqlite3.connect(f"file:{sidecar}?mode=ro",uri=True); integrity=c.execute("pragma integrity_check").fetchone()[0]; c.close()
 except Exception: integrity="UNAVAILABLE"
 record("holdings_health",{"source_version":"holdings_reunderwrite.v1","packet_id":hp.get("input_digest"),"packet_sha256":sha_file(src) if src and Path(src).is_file() else (packet_sha if empty_open_set else None),"run_date":hp.get("run_date"),"freshness":hp.get("freshness"),"action":"EMPTY_OPEN_SET" if empty_open_set else "LOAD_EXISTING_ONLY","source":src,"sidecar_path":sidecar,"sidecar_integrity":"NOT_APPLICABLE" if empty_open_set else integrity,"duplicate":False,"missing":False if empty_open_set else hp.get("status")=="MISSING","empty_open_set":empty_open_set,"open_count":len(rows)})

def record_perme(summary):
 r=(summary or {}).get("macro_context_v1_receipt") or {}; receipt_path=os.environ.get("ATLAS_PERME_CYCLE_SNAPSHOT_RECEIPT"); snapshot={}; raw={}
 try:
  snapshot=json.loads(Path(receipt_path).read_text()) if receipt_path else {}
  unsigned=dict(snapshot); supplied=unsigned.pop("snapshot_sha256",None)
  if supplied!=sha_bytes(canon(unsigned)): raise ValueError("PERME_SNAPSHOT_RECEIPT_HASH")
  raw=json.loads(Path(snapshot["envelope_path"]).read_text())
 except Exception:
  snapshot={}; raw={}
 consumed=[x for x in (r.get("consumed_field_paths") or []) if x=="$.macro_regime" or x=="$.event_risks" or x.endswith(".event_id")]
 record("perme_strict",{"snapshot_receipt_path":receipt_path,"snapshot_sha256":snapshot.get("snapshot_sha256"),"envelope_path":snapshot.get("envelope_path"),"envelope_sha256":snapshot.get("envelope_sha256"),"consumer_input_sha256":r.get("input_sha256"),"payload_path":snapshot.get("payload_path"),"payload_sha256":snapshot.get("payload_sha256"),"status":r.get("status"),"accepted":r.get("status")=="ACCEPTED","rejected":r.get("status")!="ACCEPTED","consumed_paths":consumed,"generated_at":snapshot.get("generated_at"),"ttl_minutes":snapshot.get("ttl_minutes"),"schema":raw.get("schema")})

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

def _load_receipt(d,kind):
 p=d/f"{kind}.json"
 try:
  o=json.loads(p.read_text()); supplied=o.pop("receipt_sha256")
  if o.get("schema")!=SCHEMA or o.get("cycle_id")!=d.name or o.get("kind")!=kind or supplied!=sha_bytes(canon(o)): return None
  o["receipt_sha256"]=supplied; return o
 except Exception: return None

def _manifest_attestation(path):
 try:
  p=Path(path); o=json.loads(p.read_text()); expected=o.get("source_sha256") or {}
  required=set(o.get("sole_trade_instruction_authority_paths") or [])|set(o.get("deterministic_orchestration_paths") or [])
  root=os.environ.get("ATLAS_ATTESTATION_ROOT")
  def resolved(x):
   if root and x.startswith('/Users/yasser/scripts/'):
    rel=x[len('/Users/yasser/scripts/'):]
    candidate=Path(root)/('config' if rel.startswith('config/') else 'src')/(rel[7:] if rel.startswith('config/') else rel)
    if candidate.is_file(): return candidate
   return Path(x)
  match=bool(required) and required==set(expected) and all(resolved(x).is_file() and sha_file(resolved(x))==expected[x] for x in required)
  policy=o.get("policy")=="TFE_SOLE_TRADE_INSTRUCTION_AUTHORITY" and o.get("llm_trading_authority_allowed") is False
  inventory=Path(o.get("llm_boundary_inventory_path") or "")
  if not inventory.is_file(): inventory=p.parent/inventory.name
  inventory_sha=sha_file(inventory) if inventory.is_file() else None; inv={}
  try: inv=json.loads(inventory.read_text()); inventory_complete=inv.get("schema")=="atlas.llm_boundary_inventory.v1" and inv.get("unproven_boundaries")==[]
  except Exception: inventory_complete=False
  inventory_match=inventory_sha==o.get("llm_boundary_inventory_sha256")
  return {"manifest_sha256":sha_file(p),"source_sha256":expected,"active_code_shas_match":match,"policy_valid":policy,"inventory_sha256":inventory_sha,"inventory_match":inventory_match,"inventory_complete":inventory_complete,"inventory":inv if inventory_complete else {}}
 except Exception: return {"manifest_sha256":None,"source_sha256":{},"active_code_shas_match":False,"policy_valid":False,"inventory_sha256":None,"inventory_match":False,"inventory_complete":False,"inventory":{}}

def assert_manifest_consistent(path):
 """Seal-time hard gate for source and LLM-inventory attestations."""
 result=_manifest_attestation(path)
 if not (result["active_code_shas_match"] and result["inventory_match"] and result["inventory_complete"] and result["policy_valid"]):
  raise RuntimeError("ATTESTATION_CONSISTENCY_FAILED")
 return result

def _incident_attestation(path):
 unresolved=[]
 try:
  p=Path(path)
  for i,line in enumerate(p.read_text().splitlines(),1):
   if not line.strip(): continue
   o=json.loads(line); sev=str(o.get("severity") or "").upper(); status=str(o.get("status") or "").upper()
   if sev in {"P0","P1"} and status not in {"RESOLVED","CLOSED"}: unresolved.append(o.get("incident_id") or f"line:{i}")
  return {"register_sha256":sha_file(p),"unresolved_p0_p1":unresolved,"append_only_format":"JSONL"}
 except Exception: return {"register_sha256":None,"unresolved_p0_p1":["REGISTER_INVALID"],"append_only_format":"JSONL"}

def _llm_window_attestation(path,start_utc,end_utc,cid,manifest):
 rows=[]; errors=[]
 try:
  start=dt.datetime.fromisoformat(str(start_utc).replace("Z","+00:00")); end=dt.datetime.fromisoformat(str(end_utc).replace("Z","+00:00")); p=Path(path)
  if not p.is_file(): raise FileNotFoundError
  for line in p.read_text().splitlines():
   if not line.strip(): continue
   o=json.loads(line); ts=dt.datetime.fromisoformat(str(o.get("ts")).replace("Z","+00:00"))
   if start<=ts<=end and o.get("cycle_id") in (None,cid): rows.append(o)
 except Exception as exc: errors.append("LLM_LEDGER_"+type(exc).__name__.upper())
 boundary_map={x.get("boundary"):x for x in (manifest.get("inventory") or {}).get("boundaries",[])}
 unclassified=[x for x in rows if x.get("boundary") not in boundary_map]
 trading=[x for x in rows if (boundary_map.get(x.get("boundary")) or {}).get("trading_authority_capable") is not False]
 return {"ledger_sha256":sha_file(path) if Path(path).is_file() else None,"cycle_window_start_utc":str(start_utc),"cycle_window_end_utc":str(end_utc),"cycle_rows":rows,"unclassified":unclassified,"trading_authority_capable_invocations":trading,"errors":errors}

def emit_authority_receipt(source_envelope_sha256,manifest_path,incident_register_path,llm_ledger_path,start_utc,end_utc,cid=None):
 """Derive seven authority booleans from validated receipts; false remains explicit and fail-closed."""
 cid=cid or cycle_id(); d=cycle_dir(cid); receipts={k:_load_receipt(d,k) for k in ("holdings_price","holdings_health","perme_strict","candidate_accounting","child_completion")}
 hp=(receipts.get("holdings_price") or {}).get("payload") or {}; hh=(receipts.get("holdings_health") or {}).get("payload") or {}; ps=(receipts.get("perme_strict") or {}).get("payload") or {}; ca=(receipts.get("candidate_accounting") or {}).get("payload") or {}
 manifest=_manifest_attestation(manifest_path); incidents=_incident_attestation(incident_register_path); llm=_llm_window_attestation(llm_ledger_path,start_utc,end_utc,cid,manifest)
 flags={
  "holdings_price_healthy":bool(receipts.get("holdings_price") and hp.get("packet_sha256") and hp.get("packet_sha256")==hp.get("header_packet_sha256")==hp.get("detail_packet_sha256") and (not hp.get("empty_open_set") or (hp.get("open_count")==0 and hp.get("rows")==[]))),
  "holdings_reevaluation_healthy":bool(receipts.get("holdings_health") and hh.get("missing") is False and hh.get("duplicate") is False and hh.get("packet_sha256") and ((hh.get("empty_open_set") is True and hh.get("open_count")==0 and hh.get("sidecar_integrity")=="NOT_APPLICABLE") or hh.get("sidecar_integrity")=="ok")),
  "perme_strict":bool(receipts.get("perme_strict") and ps.get("status")=="ACCEPTED" and ps.get("accepted") is True and ps.get("rejected") is False and {"$.macro_regime","$.event_risks"}.issubset(set(ps.get("consumed_paths") or []))),
  "ca_active_complete":bool(receipts.get("candidate_accounting") and ca.get("equation_holds") is True and ca.get("ca_receipt_count")==len(list(d.glob("corporate_action.*.json"))) and ca.get("admission_receipt_count")<=ca.get("ca_receipt_count")),
  "tfe_sole_authority":bool(manifest["policy_valid"] and manifest["active_code_shas_match"] and manifest["inventory_match"] and manifest["inventory_complete"]),
  "llm_trading_authority_false":bool(receipts.get("child_completion") and manifest["active_code_shas_match"] and manifest["policy_valid"] and manifest["inventory_match"] and manifest["inventory_complete"] and not llm["errors"] and not llm["unclassified"] and not llm["trading_authority_capable_invocations"]),
  "no_p0_p1":not incidents["unresolved_p0_p1"],
 }
 derivation={"holdings_price_healthy":(receipts.get("holdings_price") or {}).get("receipt_sha256"),"holdings_reevaluation_healthy":(receipts.get("holdings_health") or {}).get("receipt_sha256"),"perme_strict":(receipts.get("perme_strict") or {}).get("receipt_sha256"),"ca_active_complete":(receipts.get("candidate_accounting") or {}).get("receipt_sha256"),"tfe_sole_authority":manifest["manifest_sha256"],"llm_trading_authority_false":(receipts.get("child_completion") or {}).get("receipt_sha256"),"no_p0_p1":incidents["register_sha256"]}
 body={"schema":AUTHORITY_SCHEMA,"cycle_id":cid,"source_envelope_sha256":source_envelope_sha256,**flags,"derivation_receipts":derivation,"runtime_attestation":{"manifest_sha256":manifest["manifest_sha256"],"inventory_sha256":manifest["inventory_sha256"],"active_code_shas":manifest["source_sha256"],"active_code_shas_match":manifest["active_code_shas_match"],"llm_window":llm},"incident_attestation":incidents}
 body["receipt_sha256"]=sha_bytes(canon(body)); atomic_json(d/"authority.json",body); return body

def verify_cycle(cid,require_envelope=False,require_authority=False):
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
 srp=perme.get("snapshot_receipt_path"); snapshot={}
 try:
  snapshot=json.loads(Path(srp).read_text()); supplied=snapshot.pop("snapshot_sha256")
  if supplied!=sha_bytes(canon(snapshot)): raise ValueError("SNAPSHOT_HASH")
  snapshot["snapshot_sha256"]=supplied
 except Exception: errors.append("PERME_SNAPSHOT_INVALID")
 ep=perme.get("envelope_path"); envelope=None
 if (not ep or ep!=snapshot.get("envelope_path") or not Path(ep).is_file()
     or sha_file(ep)!=perme.get("envelope_sha256") or perme.get("consumer_input_sha256")!=perme.get("envelope_sha256")):
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
 if (not pp or pp!=snapshot.get("payload_path") or not Path(pp).is_file() or sha_file(pp)!=perme.get("payload_sha256")
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
 if require_authority:
  p=d/"authority.json"
  try:
   auth=json.loads(p.read_text()); supplied=auth.pop("receipt_sha256")
   if auth.get("schema")!=AUTHORITY_SCHEMA or auth.get("cycle_id")!=cid or supplied!=sha_bytes(canon(auth)): errors.append("AUTHORITY_INVALID")
   auth["receipt_sha256"]=supplied; objs["authority"]=auth
   if not all(auth.get(k) is True for k in AUTHORITY_FLAGS): errors.append("AUTHORITY_FLAGS")
  except Exception: errors.append("MISSING_AUTHORITY")
 if require_envelope and not (d/"completion_envelope.json").exists(): errors.append("MISSING_ENVELOPE")
 return (not errors),sorted(errors),objs
