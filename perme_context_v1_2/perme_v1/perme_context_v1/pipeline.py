from __future__ import annotations
import hashlib, importlib.util, json, sys
from datetime import datetime
from pathlib import Path
from typing import Any
from .build import build
from .collect import collect
from .io import atomic_write, dumps
from .render import compatibility_packet, owner_report, tfe_context, validate_tfe_context
from .validation import validate_context

def _consumer():
    path="/Users/yasser/scripts/atlas_perme_engine_packet.py"
    spec=importlib.util.spec_from_file_location("deployed_atlas_perme_engine_packet",path)
    if not spec or not spec.loader: raise RuntimeError("deployed consumer unavailable")
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
    return module,path

def run_pipeline(mode:str,routine:str,outbox:Path,raw_bundle:dict[str,Any]|None=None)->dict[str,Any]:
    requested=str(outbox.absolute())
    outbox=outbox.resolve()
    if not (requested.startswith("/tmp/") and str(outbox).startswith(("/tmp/","/private/tmp/"))): raise ValueError("outbox must be under /tmp")
    if mode not in {"mock","live"}: raise ValueError("mode")
    raw=raw_bundle if raw_bundle is not None else collect(routine,mode)
    # Raw acceptance artifact is retained even if canonical validation later fails.
    atomic_write(outbox/"raw_evidence_bundle.json",dumps(raw))
    packet=build(raw); validate_context(packet,now=datetime.fromisoformat(packet["generated_at"]))
    owner=owner_report(packet); tfe=validate_tfe_context(tfe_context(packet)); compat=compatibility_packet(packet)
    canonical_bytes=dumps(packet).encode(); tfe_bytes=dumps(tfe).encode(); compat_line=json_line(compat); compat_bytes=compat_line.encode()
    consumer,path=_consumer()
    compat_path=outbox/"compatibility_packet.jsonl"; atomic_write(compat_path,compat_line)
    accepted,errors=consumer.load_valid_packets(compat_path,now_et=datetime.fromisoformat(packet["generated_at"]))
    if len(accepted)!=1 or errors: raise RuntimeError(f"deployed compatibility consumer rejected: {errors}")
    receipt={"schema":"PermeContextV1CompatibilityReceipt","canonical_schema":packet["schema"],"consumer_path":path,"consumer_function":"load_valid_packets","accepted_count":len(accepted),"errors":errors,"submitted_payload":compat,"accepted_payload":accepted[0],"normalized_payload":accepted[0],"accepted_payload_exact_match":accepted[0]==compat,"hashes":{"canonical_sha256":hashlib.sha256(canonical_bytes).hexdigest(),"tfe_sha256":hashlib.sha256(tfe_bytes).hexdigest(),"submitted_compatibility_sha256":hashlib.sha256(compat_bytes).hexdigest(),"accepted_payload_sha256":hashlib.sha256(json.dumps(accepted[0],sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()},"tfe_validation":"STRICT_ACCEPTED","note":"Compatibility/annotation consumer only; no direct TFE execution consumer exists or is claimed. The submitted payload and exact normalized accepted payload are both retained with hashes."}
    # Outputs are rendered only after validation and compatibility acceptance.
    for name,data in (("perme_context_v1.json",canonical_bytes.decode()),("owner_report.md",owner),("tfe_machine_context_v1.json",tfe_bytes.decode()),("compatibility_receipt.json",dumps(receipt))): atomic_write(outbox/name,data)
    return {"outbox":str(outbox),"artifacts":[str(outbox/x) for x in ("raw_evidence_bundle.json","perme_context_v1.json","owner_report.md","tfe_machine_context_v1.json","compatibility_packet.jsonl","compatibility_receipt.json")],"compatibility_accepted":1}

def json_line(value:Any)->str:
    import json
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n"
