#!/usr/bin/env python3
"""Strict, immutable Perme Strategy Contract adapter (V1.2).

Maps TFEMachineContextV1 only onto pre-existing Atlas gates.  It has no broker,
notification, sizing, score, stop, target, or Profit Protection authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping
import json, math, re

_TOP={"schema","source","artifact","generated_at","macro_regime","event_risks","freshness","provenance"}
_SOURCE={"producer","source_sha256"}; _ARTIFACT={"path","sha256"}; _PROV={"evidence_ids"}
_EVENT={"event_id","event_type","importance","scheduled_event_time","confidence","evidence_ids"}
_SECTOR={"event_id","sector","ticker","numeric_facts","confidence","evidence_ids"}
_HOLD={"ticker","relationship","evidence_ids"}
_FACT={"name","value","unit"}; _FRESH={"ttl_minutes","status"}
_SYMBOL=re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_TRADE=re.compile(r"\b(buy|sell|short|cover|enter|exit|stop[- ]?loss|take[- ]?profit|target price|position size)\b",re.I)

class ContextRejected(ValueError): pass

def _freeze(v:Any)->Any:
    if isinstance(v,dict): return MappingProxyType({k:_freeze(x) for k,x in v.items()})
    if isinstance(v,list): return tuple(_freeze(x) for x in v)
    return v

def _paths(v:Any,p="$")->list[str]:
    out=[]
    if isinstance(v,Mapping):
        for k,x in v.items(): out.append(f"{p}.{k}"); out.extend(_paths(x,f"{p}.{k}"))
    elif isinstance(v,(list,tuple)):
        for i,x in enumerate(v): out.append(f"{p}[{i}]"); out.extend(_paths(x,f"{p}[{i}]"))
    return out

def _iso(s:Any)->datetime:
    if not isinstance(s,str): raise ContextRejected("INVALID_TIMESTAMP")
    try: d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception as e: raise ContextRejected("INVALID_TIMESTAMP") from e
    if d.tzinfo is None: raise ContextRejected("NAIVE_TIMESTAMP")
    return d.astimezone(timezone.utc)

def _exact(v:Any,keys:set[str],code:str):
    if not isinstance(v,dict) or set(v)!=keys: raise ContextRejected(code)

def _confidence(v:Any):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1: raise ContextRejected("INVALID_CONFIDENCE")

def _ids(v:Any):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v) or len(v)!=len(set(v)): raise ContextRejected("INVALID_EVIDENCE_IDS")

def validate_machine_context(raw:Any,*,now:datetime|None=None,authoritative_holdings:Iterable[str]|None=None,artifact_path:str|Path|None=None)->dict[str,Any]:
    _exact(raw,_TOP,"STRICT_TOP_LEVEL_FIELDS")
    try: encoded=json.dumps(raw,sort_keys=True,separators=(",",":"),allow_nan=False)
    except Exception as e: raise ContextRejected("NON_FINITE_OR_NON_JSON") from e
    if _TRADE.search(encoded): raise ContextRejected("TRADING_INSTRUCTION")
    if raw["schema"]!="PermeAtlasContextV1" or raw["macro_regime"] not in {"RISK_OFF","RISK_ON","NEUTRAL"}: raise ContextRejected("INVALID_SCHEMA_OR_REGIME")
    _exact(raw["source"],_SOURCE,"STRICT_SOURCE_FIELDS"); _exact(raw["artifact"],_ARTIFACT,"STRICT_ARTIFACT_FIELDS"); _exact(raw["provenance"],_PROV,"STRICT_PROVENANCE_FIELDS")
    if raw["source"]["producer"]!="perme" or not re.fullmatch(r"[0-9a-f]{64}",str(raw["source"]["source_sha256"])): raise ContextRejected("INVALID_SOURCE_IDENTITY")
    if not re.fullmatch(r"[0-9a-f]{64}",str(raw["artifact"]["sha256"])): raise ContextRejected("INVALID_ARTIFACT_IDENTITY")
    if raw["source"]["source_sha256"]!=raw["artifact"]["sha256"]: raise ContextRejected("SOURCE_ARTIFACT_IDENTITY_CONFLICT")
    bound_path=Path(artifact_path or raw["artifact"]["path"])
    if not bound_path.is_file() or sha256(bound_path.read_bytes()).hexdigest()!=raw["artifact"]["sha256"]: raise ContextRejected("ARTIFACT_SHA_MISMATCH")
    generated=_iso(raw["generated_at"]); _exact(raw["freshness"],_FRESH,"STRICT_FRESHNESS_FIELDS")
    ttl=raw["freshness"]["ttl_minutes"]
    if isinstance(ttl,bool) or not isinstance(ttl,int) or ttl<1 or raw["freshness"]["status"]!="FRESH": raise ContextRejected("INVALID_FRESHNESS")
    current=(now or datetime.now(timezone.utc)); current=current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    age=(current-generated).total_seconds()
    if age < -300: raise ContextRejected("FUTURE_GENERATED_AT")
    if age > ttl*60: raise ContextRejected("STALE_CONTEXT")
    _ids(raw["provenance"]["evidence_ids"])
    if not isinstance(raw["event_risks"],list): raise ContextRejected("INVALID_COLLECTION")
    referenced=set(); event_ids=set()
    for e in raw["event_risks"]:
        _exact(e,_EVENT,"STRICT_EVENT_FIELDS")
        if e["event_type"] not in {"NEWS","EARNINGS","MACRO_EVENT"} or e["importance"] not in {"UNKNOWN","LOW","MEDIUM","HIGH"}: raise ContextRejected("INVALID_EVENT_ENUM")
        if not isinstance(e["event_id"],str) or not e["event_id"].strip() or e["event_id"] in event_ids: raise ContextRejected("INVALID_OR_DUPLICATE_EVENT_ID")
        event_ids.add(e["event_id"]); _confidence(e["confidence"]); _ids(e["evidence_ids"]); referenced.update(e["evidence_ids"])
        if e["scheduled_event_time"] is not None: _iso(e["scheduled_event_time"])
    if raw["provenance"]["evidence_ids"]!=sorted(referenced): raise ContextRejected("EVIDENCE_CONFLICT")
    return raw

@dataclass(frozen=True)
class AtlasMacroContextV1:
    input_sha256:str; generated_at:str; macro_regime:str; event_risks:tuple; accepted_field_paths:tuple

@dataclass(frozen=True)
class ContextLoadResult:
    context:AtlasMacroContextV1|None; receipt:Mapping[str,Any]

def load_context(path:str|Path|None,*,now:datetime|None=None,authoritative_holdings:Iterable[str]|None=None,consumer="loader")->ContextLoadResult:
    base={"contract":"AtlasMacroContextV1","consumer":consumer,"input_sha256":None,"status":"NO_CONTEXT","accepted_field_paths":[],"consumed_field_paths":[],"ignored_field_paths":[],"rejected_field_paths":[],"mapped_holdings":[],"mapped_candidates":[],"existing_gates_evaluated":[],"deterministic_effect":"NONE"}
    if not path: return ContextLoadResult(None,MappingProxyType(base))
    p=Path(path)
    if not p.exists(): return ContextLoadResult(None,MappingProxyType(base))
    data=p.read_bytes(); base["input_sha256"]=sha256(data).hexdigest()
    try: raw=json.loads(data); validate_machine_context(raw,now=now,authoritative_holdings=authoritative_holdings)
    except Exception as e:
        base.update(status="REJECTED",rejected_field_paths=["$"],deterministic_effect="NONE",rejection_code=str(e))
        return ContextLoadResult(None,MappingProxyType(base))
    paths=tuple(sorted(_paths(raw)))
    ctx=AtlasMacroContextV1(base["input_sha256"],raw["generated_at"],raw["macro_regime"],tuple(_freeze(x) for x in raw["event_risks"]),paths)
    base.update(status="ACCEPTED",accepted_field_paths=list(paths),ignored_field_paths=list(paths))
    return ContextLoadResult(ctx,MappingProxyType(base))

def adapt_existing_gates(ctx:AtlasMacroContextV1|None,*,consumer:str,candidates:Iterable[str]=(),holdings:Iterable[str]=())->tuple[dict[str,Any],dict[str,Any]]:
    """Return legacy gate values plus a truthful deterministic consumption receipt."""
    r={"contract":"AtlasMacroContextV1","consumer":consumer,"input_sha256":getattr(ctx,"input_sha256",None),"status":"NO_CONTEXT","accepted_field_paths":[],"consumed_field_paths":[],"ignored_field_paths":[],"rejected_field_paths":[],"mapped_holdings":sorted({str(x).upper() for x in holdings}),"mapped_candidates":sorted({str(x).upper() for x in candidates}),"existing_gates_evaluated":[],"deterministic_effect":"NONE"}
    if ctx is None: return {},r
    r.update(status="ACCEPTED",accepted_field_paths=list(ctx.accepted_field_paths),ignored_field_paths=list(ctx.accepted_field_paths))
    legacy={}; consumed=[]; gates=[]
    # Exact enum mapping to existing regime gates. RISK_ON is intentionally neutral because existing gates do not define it.
    if ctx.macro_regime=="RISK_OFF":
        legacy.update(sentiment="RISK_OFF",perme_regime="RISK_OFF",cautious=True); consumed.append("$.macro_regime"); gates.append("regime")
    elif ctx.macro_regime=="NEUTRAL":
        legacy.update(sentiment="NEUTRAL",perme_regime="NEUTRAL",cautious=False); consumed.append("$.macro_regime"); gates.append("regime")
    # Existing event gate accepts only presence. Do not infer severity, ticker, or event policy.
    if ctx.event_risks:
        legacy["upcoming_events"]=[e["event_id"] for e in ctx.event_risks]; legacy["event_checked"]=True; legacy["event_risk"]=True
        consumed += ["$.event_risks",* [f"$.event_risks[{i}].event_id" for i in range(len(ctx.event_risks))]]; gates.append("event")
    else: legacy.update(upcoming_events=[],event_checked=True,event_risk=False); consumed.append("$.event_risks"); gates.append("event")
    # Holding identities map subjects only; annotation is not consumption.
    legacy["mapped_open_holdings"]=[]
    # Sector snapshots have measurements but no exact existing sector-state enum; ticker is an ETF, not an affected issuer.
    consumed=sorted(set(consumed)); r["consumed_field_paths"]=consumed; r["ignored_field_paths"]=sorted(set(r["accepted_field_paths"])-set(consumed)); r["existing_gates_evaluated"]=sorted(set(gates)); r["deterministic_effect"]="EXISTING_GATES_ONLY" if consumed else "NONE"
    return legacy,r

__all__=["AtlasMacroContextV1","ContextLoadResult","ContextRejected","validate_machine_context","load_context","adapt_existing_gates"]
