from __future__ import annotations
import json
from datetime import datetime
from typing import Any

IMPORTANCE_ORDER={"HIGH":0,"MEDIUM":1,"UNKNOWN":2,"LOW":3}
REPORT_CAP=6


def _facts(event:dict[str,Any])->str:
    values=[]
    for fact in event["numeric_facts"]:
        label=fact["name"].replace("_"," ")
        values.append(f"{label} {fact['value']:g} {fact['unit'].replace('_',' ')}")
    return ", ".join(values)


def _sentence(event:dict[str,Any])->str:
    subject=event["ticker"] or event["sector"] or event["headline"]
    parts=[]
    if event["headline"]!=subject: parts.append(event["headline"].rstrip("."))
    facts=_facts(event)
    if facts: parts.append(facts)
    if event["scheduled_event_time"]:
        when=datetime.fromisoformat(event["scheduled_event_time"])
        parts.append(f"scheduled for {when.strftime('%Y-%m-%d %H:%M')} ET")
    detail="; ".join(parts) or event["event_type"].lower().replace("_"," ")
    return f"{subject}: {detail} [{event['importance'].lower()} importance]."


def _rank(event:dict[str,Any])->tuple[Any,...]:
    scheduled=event["scheduled_event_time"] or "9999"
    return (IMPORTANCE_ORDER[event["importance"]],scheduled,event["event_type"],event["ticker"] or "",event["headline"],event["event_id"])


def owner_report(packet:dict[str,Any])->str:
    holdings=packet["open_holdings"]["tickers"]
    direct=sorted((e for e in packet["events"] if e["portfolio_relationship"]=="OPEN_HOLDING"),key=_rank)[:REPORT_CAP]
    external=sorted((e for e in packet["events"] if e["portfolio_relationship"]!="OPEN_HOLDING"),key=_rank)[:REPORT_CAP]
    lines=["# Perme Owner Brief",f"Validated {packet['macro_regime'].replace('_',' ').lower()} context as of {packet['generated_at']}; packet expires {packet['expires_at']}.","","## Direct portfolio relevance"]
    lines.extend(f"- {_sentence(e)}" for e in direct)
    if not direct: lines.append(f"- No validated catalyst names an open holding ({', '.join(holdings) or 'none'}).")
    lines.extend(["","## External catalysts"])
    lines.extend(f"- {_sentence(e)}" for e in external)
    if not external: lines.append("- No validated external catalyst is present.")
    omitted=max(0,len(packet["events"])-len(direct)-len(external))
    if omitted: lines.append(f"- {omitted} lower-priority validated event(s) omitted by the deterministic briefing cap.")
    lines.extend(["","Context only; no trading instruction."])
    return "\n".join(lines)+"\n"


TFE_FIELDS={"schema","generated_at","macro_regime","event_risks","sector_conditions","holding_context","freshness","confidence","evidence_ids"}
EVENT_RISK={"event_id","event_type","importance","scheduled_event_time","confidence","evidence_ids"}
SECTOR={"event_id","sector","ticker","numeric_facts","confidence","evidence_ids"}
HOLDING={"ticker","relationship","evidence_ids"}

def validate_tfe_context(value:dict[str,Any])->dict[str,Any]:
    if not isinstance(value,dict) or set(value)!=TFE_FIELDS: raise ValueError("TFE strict fields")
    if value["schema"]!="TFEMachineContextV1" or value["macro_regime"] not in {"RISK_OFF","RISK_ON","NEUTRAL"}: raise ValueError("TFE schema/classification")
    datetime.fromisoformat(value["generated_at"])
    if not isinstance(value["confidence"],(int,float)) or isinstance(value["confidence"],bool) or not 0<=value["confidence"]<=1: raise ValueError("TFE confidence")
    if not isinstance(value["event_risks"],list) or not isinstance(value["sector_conditions"],list) or not isinstance(value["holding_context"],list): raise ValueError("TFE collections")
    for event in value["event_risks"]:
        if not isinstance(event,dict) or set(event)!=EVENT_RISK or event["importance"] not in IMPORTANCE_ORDER: raise ValueError("TFE event risk")
    for sector in value["sector_conditions"]:
        if not isinstance(sector,dict) or set(sector)!=SECTOR: raise ValueError("TFE sector")
    for holding in value["holding_context"]:
        if not isinstance(holding,dict) or set(holding)!=HOLDING or holding["relationship"]!="OPEN_HOLDING": raise ValueError("TFE holding")
    all_ids={x for event in value["event_risks"]+value["sector_conditions"] for x in event["evidence_ids"]}|{x for holding in value["holding_context"] for x in holding["evidence_ids"]}
    if value["evidence_ids"]!=sorted(all_ids): raise ValueError("TFE evidence proof")
    raw=json.dumps(value,sort_keys=True,allow_nan=False).lower()
    if any(word in raw for word in ("buy","sell","short","cover","stop-loss","target price","position size")): raise ValueError("TFE trading instruction")
    return value


def tfe_context(packet:dict[str,Any])->dict[str,Any]:
    events=[{"event_id":e["event_id"],"event_type":e["event_type"],"importance":e["importance"],"scheduled_event_time":e["scheduled_event_time"],"confidence":e["confidence"],"evidence_ids":e["evidence_ids"]} for e in packet["events"] if e["event_type"] in {"NEWS","EARNINGS","MACRO_EVENT"}]
    sectors=[{"event_id":e["event_id"],"sector":e["sector"],"ticker":e["ticker"],"numeric_facts":e["numeric_facts"],"confidence":e["confidence"],"evidence_ids":e["evidence_ids"]} for e in packet["events"] if e["event_type"]=="SECTOR_SNAPSHOT"]
    holdings=[{"ticker":ticker,"relationship":"OPEN_HOLDING","evidence_ids":packet["open_holdings"]["evidence_ids"]} for ticker in packet["open_holdings"]["tickers"]]
    all_ids=sorted({x for e in events+sectors for x in e["evidence_ids"]}|{x for h in holdings for x in h["evidence_ids"]})
    return {"schema":"TFEMachineContextV1","generated_at":packet["generated_at"],"macro_regime":packet["macro_regime"],"event_risks":events,"sector_conditions":sectors,"holding_context":holdings,"freshness":packet["freshness"],"confidence":min([e["confidence"] for e in packet["events"]] or [1.0]),"evidence_ids":all_ids}


def compatibility_packet(packet:dict[str,Any])->dict[str,Any]:
    severity="HIGH" if any(e["importance"]=="HIGH" for e in packet["events"]) else ("MEDIUM" if any(e["importance"]=="MEDIUM" for e in packet["events"]) else "LOW")
    tickers=sorted({e["ticker"] for e in packet["events"] if e["ticker"]}); sectors=sorted({e["sector"] for e in packet["events"] if e["sector"]})
    return {"schema":"perme_engine_packet_v1","generated_at_et":packet["generated_at"],"ttl_minutes":packet["freshness"]["ttl_minutes"],"severity":severity,"confidence":min([e["confidence"] for e in packet["events"]] or [1.0]),"scope":"PORTFOLIO" if tickers else "MARKET","sector":sectors[0] if len(sectors)==1 else "","tickers":tickers,"event_type":"PERME_CONTEXT_V1","direction":packet["macro_regime"],"evidence_count":len(packet["evidence"]),"reason_code":"VALIDATED_PERME_CONTEXT_V1","allowed_actions":["ANNOTATE"],"forbidden_actions":["BUY","SELL","CHANGE_STOP","CHANGE_TARGET"]}
