#!/usr/bin/env python3
"""Strict PermeAtlasContextV1 publisher using the immutable V1.2 validators."""
from __future__ import annotations
import datetime as dt, hashlib, json, math, os, re, sqlite3, tempfile
from pathlib import Path
from typing import Any
from atlas_macro_context_v1 import validate_machine_context
from perme_context_v1_2.perme_v1.perme_context_v1.build import build as canonical_build
from perme_context_v1_2.perme_v1.perme_context_v1.validation import validate_context as validate_canonical
from perme_context_v1_2.perme_v1.perme_context_v1.render import tfe_context, validate_tfe_context
TTL_MINUTES=240
DIRECT_OBSERVATION_CONFIDENCE=1.0
CONFIDENCE_ALIASES=("provider_confidence","source_confidence","confidence_score","confidence_pct","confidence_percent")
CONFIDENCE_NUMBER=re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")

def _canon(o): return json.dumps(o,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"
def _atomic(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix="."+path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f: f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
        d=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def _open_holdings(db_path:str)->list[str]:
    p=Path(db_path).resolve()
    if not p.is_file(): raise ValueError("INCOMPLETE_AUTHORITATIVE_HOLDINGS")
    con=sqlite3.connect(f"file:{p}?mode=ro&immutable=1",uri=True)
    try: return sorted({str(x[0]).upper() for x in con.execute("SELECT ticker FROM trades WHERE status='OPEN' ORDER BY ticker,id") if x[0]})
    finally: con.close()

def _confidence_value(value:Any)->tuple[float|int,str]:
    """Normalize explicit encodings, preserving already-valid numeric values."""
    if isinstance(value,bool): raise ValueError("PROVIDER_CONFIDENCE_INVALID")
    method="numeric"
    if isinstance(value,(int,float)):
        result=value
    elif isinstance(value,str):
        text=value.strip()
        if text.endswith("%") and CONFIDENCE_NUMBER.fullmatch(text[:-1].strip()):
            result=float(text[:-1].strip())/100.0; method="percent_string"
        elif CONFIDENCE_NUMBER.fullmatch(text):
            result=float(text); method="numeric_string"
        else: raise ValueError("PROVIDER_CONFIDENCE_INVALID")
    else: raise ValueError("PROVIDER_CONFIDENCE_INVALID")
    if not math.isfinite(result) or not 0<=result<=1: raise ValueError("PROVIDER_CONFIDENCE_INVALID")
    return result,method

def _nonempty(row:dict[str,Any],key:str)->bool:
    return isinstance(row.get(key),str) and bool(row[key].strip())

def _finite_field(row:dict[str,Any],key:str,required:bool=False)->bool:
    if key not in row: return not required
    value=row[key]
    if isinstance(value,bool): return False
    try: return math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError): return False

def _direct_observation_valid(source:str,row:dict[str,Any])->bool:
    if source=="benzinga_news": return _nonempty(row,"title") and _nonempty(row,"created")
    if source=="benzinga_earnings": return _nonempty(row,"ticker") and _nonempty(row,"date")
    if source=="eodhd_economic_calendar": return _nonempty(row,"date") and _nonempty(row,"type")
    if source=="massive_sector_etfs":
        return (_nonempty(row,"ticker") and _nonempty(row,"sector") and
                _finite_field(row,"change_pct",required=True) and
                _finite_field(row,"rsi") and _finite_field(row,"price"))
    return False

def _normalize_provider_confidence(provider:dict[str,Any])->tuple[dict[str,Any],dict[str,Any]]:
    """Copy rows and emit provenance separately from exact validator input schemas.

    Direct-observation 1.0 means a structurally valid provider record was
    available; it is not truth or predictive confidence. Prose/RAG is unused.
    """
    normalized=dict(provider); methods:dict[str,int]={}; by_source:dict[str,int]={}; total=0
    for source in ("benzinga_news","benzinga_earnings","eodhd_economic_calendar","massive_sector_etfs"):
        rows=provider.get(source) or []
        if not isinstance(rows,list): raise ValueError(f"PROVIDER_ROWS_INVALID:{source}")
        output=[]
        for index,original in enumerate(rows):
            if not isinstance(original,dict): raise ValueError(f"PROVIDER_ROW_INVALID:{source}:{index}")
            row=dict(original)
            if "confidence" in row:
                value,method=_confidence_value(row["confidence"])
            else:
                present=[key for key in CONFIDENCE_ALIASES if key in row]
                if present:
                    parsed=[]
                    for key in present:
                        raw=row[key]
                        if key in {"confidence_pct","confidence_percent"} and isinstance(raw,(int,float)) and not isinstance(raw,bool):
                            raw=f"{raw}%"
                        value,encoding=_confidence_value(raw);parsed.append((key,value,encoding))
                    if any(item[1]!=parsed[0][1] for item in parsed[1:]):
                        raise ValueError(f"AMBIGUOUS_CONFIDENCE_ALIASES:{source}:{index}")
                    key,value,encoding=parsed[0]; method=f"alias:{key}:{encoding}"
                    for alias in present: row.pop(alias,None)
                else:
                    if not _direct_observation_valid(source,row):
                        raise ValueError(f"CONFIDENCE_UNAVAILABLE_INVALID_SOURCE_RECORD:{source}:{index}")
                    value=DIRECT_OBSERVATION_CONFIDENCE; method="direct_observation"
            row["confidence"]=value; output.append(row);total+=1
            methods[method]=methods.get(method,0)+1;by_source[source]=by_source.get(source,0)+1
        normalized[source]=output
    receipt={"schema":"perme.confidence_normalization.v1","rows_normalized":total,
             "rows_by_source":dict(sorted(by_source.items())),"methods":dict(sorted(methods.items())),
             "direct_observation_value":DIRECT_OBSERVATION_CONFIDENCE,
             "direct_observation_meaning":"structurally valid direct provider record availability; not truth or prediction",
             "prose_or_rag_derivation":False}
    return normalized,receipt

def _build_tfe_with_provenance(provider:dict[str,Any], generated_at:str, holdings:list[str], db_path:str)->tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
    provider,normalization=_normalize_provider_confidence(provider)
    mode=str(provider.get("source_mode") or "").lower()
    if mode not in {"mock","live"}: raise ValueError("SOURCE_MODE_REQUIRED")
    open_rows=[{"id":i+1,"ticker":ticker,"status":"OPEN","entry_at":None,"exit_at":None} for i,ticker in enumerate(holdings)]
    keys=("benzinga_news","benzinga_earnings","eodhd_economic_calendar","massive_sector_etfs")
    bundle={"bundle_schema":"perme_raw_evidence_bundle_v1","mode":mode,"observed_at":generated_at,
      "provider_status":{"status":"SUCCESS_NONEMPTY" if any(provider.get(k) for k in keys) else "SUCCESS_EMPTY","completeness":"COMPLETE_RETURN"},
      "provider_collector":{"path":"atlas_perme_strict.py","function":"publish","read_only":True},
      "portfolio_source":{"path":str(db_path),"query":"OPEN trades read-only","read_only":True},
      "provider_context":{**provider,"routine":provider.get("routine") or "ORDER32_STRICT"},"open_trades":open_rows}
    canonical=canonical_build(bundle,ttl_minutes=TTL_MINUTES)
    validate_canonical(canonical,now=dt.datetime.fromisoformat(generated_at))
    return validate_tfe_context(tfe_context(canonical)),canonical,normalization

def build_tfe(provider:dict[str,Any], generated_at:str, holdings:list[str], db_path:str="staged-db")->tuple[dict[str,Any],dict[str,Any]]:
    tfe,canonical,_=_build_tfe_with_provenance(provider,generated_at,holdings,db_path)
    return tfe,canonical

def publish(provider:dict[str,Any],outbox:str|Path,db_path:str,generated_at:dt.datetime|None=None,provider_receipt:dict|None=None)->dict:
    if not provider_receipt or not provider_receipt.get("success"): raise ValueError("KIMI_RECEIPT_REQUIRED")
    now=generated_at or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None: raise ValueError("NAIVE_GENERATED_AT")
    stamp=now.astimezone(dt.timezone.utc).isoformat(); holdings=_open_holdings(db_path)
    root=Path(outbox); gid=now.strftime("%Y%m%dT%H%M%S.%fZ"); gen=root/"generations"/gid;gen.mkdir(parents=True,mode=0o700)
    tfe,canonical,normalization=_build_tfe_with_provenance(provider,stamp,holdings,db_path)
    canonical_bytes=_canon(canonical); _atomic(gen/"perme_context_v1.json",canonical_bytes)
    payload=_canon(tfe); payload_path=gen/"tfe_machine_context_v1.json";_atomic(payload_path,payload); digest=hashlib.sha256(payload).hexdigest()
    env={"schema":"PermeAtlasContextV1","source":{"producer":"perme","source_sha256":digest},"artifact":{"path":str(payload_path),"sha256":digest},"generated_at":stamp,"macro_regime":tfe["macro_regime"],"event_risks":tfe["event_risks"],"freshness":{"ttl_minutes":TTL_MINUTES,"status":"FRESH"},"provenance":{"evidence_ids":sorted({x for e in tfe["event_risks"] for x in e["evidence_ids"]})}}
    validate_machine_context(env,now=now,artifact_path=payload_path)
    envelope=_canon(env); envelope_path=gen/"perme_atlas_context_v1.json";_atomic(envelope_path,envelope)
    receipt={"schema":"perme.strict.publication.v1","generation_id":gid,"generated_at":stamp,"ttl_minutes":TTL_MINUTES,"provider":provider_receipt.get("provider"),"model":provider_receipt.get("model"),"kimi_success":True,"canonical_validation":"PASS","canonical_sha256":hashlib.sha256(canonical_bytes).hexdigest(),"tfe_validation":"PASS","envelope_validation":"PASS","payload_path":str(payload_path),"payload_sha256":digest,"envelope_path":str(envelope_path),"envelope_sha256":hashlib.sha256(envelope).hexdigest(),"holding_ids":holdings,"evidence_ids":tfe["evidence_ids"],"confidence_normalization":normalization}
    _atomic(gen/"producer_receipt.json",_canon(receipt))
    if provider_receipt.get("force_failure_after_generation"): raise RuntimeError("FORCED_FAILURE_AFTER_GENERATION")
    current=root/"current";current.mkdir(parents=True,exist_ok=True)
    _atomic(current/"tfe_machine_context_v1.json",payload)
    current_env=dict(env);current_env["artifact"]={"path":str(current/"tfe_machine_context_v1.json"),"sha256":digest}
    current_envelope=_canon(current_env);validate_machine_context(current_env,now=now,artifact_path=current/"tfe_machine_context_v1.json")
    current_receipt=dict(receipt);current_receipt.update(payload_path=str(current/"tfe_machine_context_v1.json"),envelope_path=str(current/"perme_atlas_context_v1.json"),envelope_sha256=hashlib.sha256(current_envelope).hexdigest())
    _atomic(current/"producer_receipt.json",_canon(current_receipt));_atomic(current/"perme_atlas_context_v1.json",current_envelope)
    return current_receipt
