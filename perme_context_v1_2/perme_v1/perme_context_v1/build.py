from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
EVENT_KEYS=("event","name","type","title")
NUMERIC_KEYS={"price":"USD/share","change_pct":"percent","rsi":"index_points","eps":"USD/share","eps_est":"USD/share","revenue":"USD","revenue_est":"USD","actual":"provider_unit","estimate":"provider_unit","forecast":"provider_unit","previous":"provider_unit"}
DECIMAL_RE=re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
TRADE_WORDS=re.compile(r"\b(buy|sell|short|cover|enter|exit|stop[- ]?loss|take[- ]?profit|target price|position size|increase position|reduce position)\b",re.I)


def _id(prefix:str, value:Any)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode()
    return prefix+hashlib.sha256(raw).hexdigest()[:20]


def _iso(value:Any, fallback:str|None=None)->str|None:
    if value in (None,""): return fallback
    text=str(value).strip().replace("Z","+00:00")
    m=re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::(\d{2}))? ET",text)
    if m:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}").replace(tzinfo=ET).isoformat()
    try:
        dt=datetime.fromisoformat(text)
    except ValueError:
        try: dt=parsedate_to_datetime(text)
        except (TypeError,ValueError,OverflowError): return None
    if dt.tzinfo is None: dt=dt.replace(tzinfo=ET)
    return dt.astimezone(ET).isoformat(timespec="seconds")


def _scheduled(row:dict[str,Any], event_type:str)->str|None:
    if event_type=="MACRO_EVENT": return _iso(row.get("datetime") or row.get("date") or row.get("time"))
    if event_type!="EARNINGS": return None
    date=row.get("date"); timing=str(row.get("time") or "").strip()
    if date and timing.upper() in {"BMO","AMC"}:
        timing="08:00:00" if timing.upper()=="BMO" else "16:00:00"
    if date and re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?",timing):
        return _iso(f"{date} {timing} ET")
    return _iso(date or timing)


def _source_timestamp(row:dict[str,Any], event_type:str, observed:str)->str:
    if event_type=="NEWS": return _iso(row.get("created"),observed) or observed
    return _scheduled(row,event_type) or _iso(row.get("created"),observed) or observed


def _freshness(source_timestamp:str,event_type:str,observed:str,ttl_minutes:int)->str:
    source=datetime.fromisoformat(source_timestamp); obs=datetime.fromisoformat(observed)
    if event_type in {"EARNINGS","MACRO_EVENT"} and source>=obs: return "FUTURE_SCHEDULED"
    return "FRESH" if source+timedelta(minutes=ttl_minutes)>=obs else "STALE"


def _event_name(row:dict[str,Any], fallback:str)->str:
    return next((str(row[k]).strip() for k in EVENT_KEYS if row.get(k)),fallback)


def _importance(row:dict[str,Any])->str:
    value=row.get("impact") if row.get("impact") not in (None,"") else row.get("importance")
    if value is None: return "UNKNOWN"
    val=str(value).upper().strip()
    return val if val in {"LOW","MEDIUM","HIGH"} else "UNKNOWN"


def _confidence(row:dict[str,Any])->float:
    value=row.get("confidence")
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not 0<=float(value)<=1:
        raise ValueError("provider confidence missing/invalid")
    return float(value)


def _number(value:Any)->float|None:
    if isinstance(value,bool) or value is None: return None
    if isinstance(value,(int,float)):
        try: d=Decimal(str(value))
        except InvalidOperation: return None
    elif isinstance(value,str) and DECIMAL_RE.fullmatch(value.strip()):
        try: d=Decimal(value.strip())
        except InvalidOperation: return None
    else: return None
    return float(d) if d.is_finite() else None


def _tickers(row:dict[str,Any])->list[str|None]:
    values=[]
    if row.get("ticker") not in (None,""): values.append(row["ticker"])
    nested=row.get("tickers")
    if isinstance(nested,list):
        for item in nested:
            value=item.get("name") if isinstance(item,dict) else item
            if value not in (None,""): values.append(value)
    clean=[]
    for value in values:
        ticker=str(value).strip().upper()
        if ticker and ticker not in clean: clean.append(ticker)
    return clean or [None]


def build(bundle:dict[str,Any], ttl_minutes:int=240)->dict[str,Any]:
    observed=bundle["observed_at"]; expires=(datetime.fromisoformat(observed)+timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds")
    p=bundle["provider_context"]
    status=bundle.get("provider_status") or {"status":"NOT_REPORTED","completeness":"UNKNOWN"}
    sources=[
      {"source_id":"SRC-PROVIDER-COLLECTOR","kind":"PROVIDER_COLLECTION","locator":bundle["provider_collector"]["path"]+"#collect_context","observed_at":observed,"read_only":True,"status":status.get("status","NOT_REPORTED"),"completeness":status.get("completeness","UNKNOWN")},
      {"source_id":"SRC-PORTFOLIO-DB","kind":"PORTFOLIO_DB_SNAPSHOT","locator":bundle["portfolio_source"]["path"],"observed_at":observed,"read_only":True,"status":"SUCCESS_NONEMPTY" if bundle["open_trades"] else "SUCCESS_EMPTY","completeness":"COMPLETE_QUERY_RESULT"},
    ]
    evidence=[]
    type_map={"benzinga_news":("BENZINGA_NEWS","NEWS"),"benzinga_earnings":("BENZINGA_EARNINGS","EARNINGS"),"eodhd_economic_calendar":("EODHD_CALENDAR","MACRO_EVENT"),"massive_sector_etfs":("MASSIVE_SECTOR","SECTOR_SNAPSHOT")}
    for key,(source_name,event_type) in type_map.items():
        for idx,row in enumerate(p.get(key) or []):
            if not isinstance(row,dict): continue
            source_ts=_source_timestamp(row,event_type,observed); freshness=_freshness(source_ts,event_type,observed,ttl_minutes)
            # Historical stale feed items are not canonical evidence; scheduled future items remain usable.
            if freshness=="STALE": continue
            evidence.append({"evidence_id":_id("EV-",[key,idx,row]),"source_id":"SRC-PROVIDER-COLLECTOR","source_record_type":source_name,"observed_at":observed,"source_timestamp":source_ts,"freshness_status":freshness,"raw_record":row})
    open_tickers={str(r["ticker"]).strip().upper() for r in bundle["open_trades"] if isinstance(r,dict) and r.get("status")=="OPEN" and r.get("ticker")}
    portfolio_eid=_id("EV-",["open_trades",bundle["open_trades"]])
    evidence.append({"evidence_id":portfolio_eid,"source_id":"SRC-PORTFOLIO-DB","source_record_type":"OPEN_TRADES_SNAPSHOT","observed_at":observed,"source_timestamp":observed,"freshness_status":"FRESH","raw_record":bundle["open_trades"]})
    events=[]
    reverse={v[0]:v[1] for v in type_map.values()}
    for ev in evidence:
        if ev["source_record_type"]=="OPEN_TRADES_SNAPSHOT": continue
        row=ev["raw_record"]; event_type=reverse[ev["source_record_type"]]
        sector=str(row.get("sector") or "").upper() or None
        facts=[]
        for key,unit in NUMERIC_KEYS.items():
            value=_number(row.get(key))
            if value is not None: facts.append({"name":key,"value":value,"unit":unit})
        for ticker in _tickers(row):
            relationship="OPEN_HOLDING" if ticker is not None and ticker in open_tickers else ("NOT_OPEN_HOLDING" if ticker is not None else "MARKET_WIDE")
            events.append({"event_id":_id("EVENT-",[ev["evidence_id"],event_type,ticker]),"evidence_ids":[ev["evidence_id"]]+([portfolio_eid] if ticker else []),"event_type":event_type,"importance":_importance(row),"headline":_event_name(row,sector or ticker or event_type),"ticker":ticker,"issuer":None,"sector":sector,"industry":None,"numeric_facts":facts,"scheduled_event_time":_scheduled(row,event_type),"confidence":_confidence(row),"portfolio_relationship":relationship,"causal_claims":[]})
    changes=[f["value"] for e in events for f in e["numeric_facts"] if f["name"]=="change_pct"]
    regime="RISK_OFF" if any(e["importance"]=="HIGH" for e in events) or (changes and min(changes)<=-1.0) else ("RISK_ON" if changes and min(changes)>0 else "NEUTRAL")
    return {"schema":"PermeContextV1","generated_at":observed,"expires_at":expires,"freshness":{"ttl_minutes":ttl_minutes,"status":"FRESH"},"mode":bundle["mode"],"routine":p["routine"],"sources":sources,"evidence":evidence,"macro_regime":regime,"events":events,"open_holdings":{"evidence_ids":[portfolio_eid],"tickers":sorted(open_tickers)},"trading_instructions":[]}
