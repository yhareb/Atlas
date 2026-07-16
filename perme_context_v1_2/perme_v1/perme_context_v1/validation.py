from __future__ import annotations
import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
from .build import NUMERIC_KEYS, TRADE_WORDS, _freshness, _importance, _iso, _number, _scheduled, _source_timestamp, _tickers

ET=ZoneInfo("America/New_York")
TOP={"schema","generated_at","expires_at","freshness","mode","routine","sources","evidence","macro_regime","events","open_holdings","trading_instructions"}
SOURCE={"source_id","kind","locator","observed_at","read_only","status","completeness"}
EVIDENCE={"evidence_id","source_id","source_record_type","observed_at","source_timestamp","freshness_status","raw_record"}
EVENT={"event_id","evidence_ids","event_type","importance","headline","ticker","issuer","sector","industry","numeric_facts","scheduled_event_time","confidence","portfolio_relationship","causal_claims"}
FACT={"name","value","unit"}; FRESH={"ttl_minutes","status"}; HOLD={"evidence_ids","tickers"}
class ValidationError(ValueError): pass


def _exact(obj:Any, fields:set[str], where:str):
    if not isinstance(obj,dict) or set(obj)!=fields: raise ValidationError(f"{where}: strict fields")
def _finite(obj:Any):
    if isinstance(obj,float) and not math.isfinite(obj): raise ValidationError("non-finite JSON")
    if isinstance(obj,dict):
        for v in obj.values(): _finite(v)
    elif isinstance(obj,list):
        for v in obj: _finite(v)
def _contains(row:Any,value:Any)->bool:
    if value is None: return True
    if isinstance(row,dict): return any(_contains(v,value) for v in row.values())
    if isinstance(row,list): return any(_contains(v,value) for v in row)
    return str(row).upper().strip()==str(value).upper().strip()
def _text(obj:Any):
    if isinstance(obj,str): yield obj
    elif isinstance(obj,dict):
        for v in obj.values(): yield from _text(v)
    elif isinstance(obj,list):
        for v in obj: yield from _text(v)


def validate_context(packet:dict[str,Any],now:datetime|None=None)->dict[str,Any]:
    _finite(packet); _exact(packet,TOP,"packet")
    if packet["schema"]!="PermeContextV1" or packet["mode"] not in {"mock","live"}: raise ValidationError("schema/mode")
    _exact(packet["freshness"],FRESH,"freshness"); _exact(packet["open_holdings"],HOLD,"open_holdings")
    try: generated=datetime.fromisoformat(packet["generated_at"]); expires=datetime.fromisoformat(packet["expires_at"])
    except Exception as exc: raise ValidationError("invalid timestamps") from exc
    if generated.tzinfo is None or expires.tzinfo is None or expires<=generated: raise ValidationError("invalid time range")
    now=now or datetime.now(ET)
    if now.tzinfo is None: now=now.replace(tzinfo=ET)
    ttl=packet["freshness"]["ttl_minutes"]
    if not isinstance(ttl,int) or ttl<1: raise ValidationError("ttl")
    if now>expires or packet["freshness"]["status"]!="FRESH": raise ValidationError("stale packet")
    if packet["trading_instructions"]!=[] or any(TRADE_WORDS.search(t) for t in _text(packet)): raise ValidationError("trading instructions")
    sources={}
    for source in packet["sources"]:
        _exact(source,SOURCE,"source")
        if source["read_only"] is not True or not isinstance(source["status"],str) or not isinstance(source["completeness"],str): raise ValidationError("source metadata")
        sources[source["source_id"]]=source
    evidence={}
    type_map={"BENZINGA_NEWS":"NEWS","BENZINGA_EARNINGS":"EARNINGS","EODHD_CALENDAR":"MACRO_EVENT","MASSIVE_SECTOR":"SECTOR_SNAPSHOT"}
    for item in packet["evidence"]:
        _exact(item,EVIDENCE,"evidence")
        if item["source_id"] not in sources or item["evidence_id"] in evidence: raise ValidationError("evidence source/id")
        try: observed=datetime.fromisoformat(item["observed_at"]); source_ts=datetime.fromisoformat(item["source_timestamp"])
        except Exception as exc: raise ValidationError("evidence timestamp") from exc
        if observed.tzinfo is None or source_ts.tzinfo is None or observed!=generated: raise ValidationError("evidence observed time")
        if item["source_record_type"]=="OPEN_TRADES_SNAPSHOT": expected_ts=packet["generated_at"]; expected_fresh="FRESH"
        else:
            event_type=type_map.get(item["source_record_type"])
            if not event_type: raise ValidationError("record type")
            expected_ts=_source_timestamp(item["raw_record"],event_type,packet["generated_at"])
            expected_fresh=_freshness(expected_ts,event_type,packet["generated_at"],ttl)
        if item["source_timestamp"]!=expected_ts or item["freshness_status"]!=expected_fresh or expected_fresh=="STALE": raise ValidationError("stale/unsupported evidence freshness")
        evidence[item["evidence_id"]]=item
    port_eids=packet["open_holdings"]["evidence_ids"]
    if len(port_eids)!=1 or port_eids[0] not in evidence or evidence[port_eids[0]]["source_record_type"]!="OPEN_TRADES_SNAPSHOT": raise ValidationError("portfolio evidence")
    rows=evidence[port_eids[0]]["raw_record"]
    db_tickers=sorted({str(r["ticker"]).strip().upper() for r in rows if isinstance(r,dict) and r.get("status")=="OPEN" and r.get("ticker")})
    if packet["open_holdings"]["tickers"]!=db_tickers: raise ValidationError("unsupported portfolio claim")
    seen_pairs=set(); classifications={}
    for event in packet["events"]:
        _exact(event,EVENT,"event")
        if event["event_type"] not in set(type_map.values()) or event["importance"] not in {"UNKNOWN","LOW","MEDIUM","HIGH"}: raise ValidationError("classification")
        if not isinstance(event["confidence"],(int,float)) or isinstance(event["confidence"],bool) or not 0<=event["confidence"]<=1: raise ValidationError("confidence")
        if event["causal_claims"]!=[]: raise ValidationError("unsupported causality")
        source_items=[evidence[x] for x in event["evidence_ids"] if x in evidence and evidence[x]["source_record_type"]!="OPEN_TRADES_SNAPSHOT"]
        if len(source_items)!=1 or any(x not in evidence for x in event["evidence_ids"]): raise ValidationError("event evidence cardinality")
        item=source_items[0]; row=item["raw_record"]; expected_type=type_map[item["source_record_type"]]
        if event["event_type"]!=expected_type or event["importance"]!=_importance(row): raise ValidationError("unsupported classification")
        if event["ticker"] not in _tickers(row): raise ValidationError("unsupported ticker")
        pair=(item["evidence_id"],event["ticker"])
        if pair in seen_pairs: raise ValidationError("duplicate ticker event")
        seen_pairs.add(pair)
        for key in ("issuer","sector","industry"):
            if event[key] is not None and not _contains(row,event[key]): raise ValidationError(f"unsupported entity: {key}")
        if event["headline"] and not (_contains(row,event["headline"]) or event["headline"] in {event["sector"],event["ticker"],event["event_type"]}): raise ValidationError("unsupported headline")
        expected_facts={key:(_number(row.get(key)),unit) for key,unit in NUMERIC_KEYS.items() if _number(row.get(key)) is not None}
        if len(event["numeric_facts"])!=len(expected_facts): raise ValidationError("numeric support/cardinality")
        for fact in event["numeric_facts"]:
            _exact(fact,FACT,"numeric fact")
            if fact["name"] not in expected_facts or (fact["value"],fact["unit"])!=expected_facts[fact["name"]]: raise ValidationError("unsupported number/unit")
        if event["scheduled_event_time"]!=_scheduled(row,expected_type): raise ValidationError("unsupported scheduled time")
        expected_rel="OPEN_HOLDING" if event["ticker"] is not None and event["ticker"] in db_tickers else ("NOT_OPEN_HOLDING" if event["ticker"] is not None else "MARKET_WIDE")
        if event["portfolio_relationship"]!=expected_rel or (event["ticker"] is not None and port_eids[0] not in event["evidence_ids"]): raise ValidationError("unsupported portfolio relationship")
        if event["ticker"]:
            vals=(event["issuer"],event["sector"],event["industry"]); old=classifications.setdefault(event["ticker"],vals)
            if old!=vals and all(x is not None for x in old+vals): raise ValidationError("classification conflict")
    changes=[f["value"] for e in packet["events"] for f in e["numeric_facts"] if f["name"]=="change_pct"]
    expected_regime="RISK_OFF" if any(e["importance"]=="HIGH" for e in packet["events"]) or (changes and min(changes)<=-1.0) else ("RISK_ON" if changes and min(changes)>0 else "NEUTRAL")
    if packet["macro_regime"]!=expected_regime: raise ValidationError("unsupported macro regime")
    return packet
