#!/usr/bin/env python3
"""Deterministic SEC-EDGAR corporate-action authority (CLEAR/BLOCK/DEFER only)."""
from __future__ import annotations
import datetime as dt, hashlib, json, os, re, threading, time, urllib.request
from pathlib import Path

CLEAR, BLOCK, DEFER = "CLEAR", "BLOCK", "DEFER"
FORMS = {"8-K","8-K/A","SC TO-I","SC TO-I/A","SC TO-T","SC TO-T/A","SC TO-C","SC TO-C/A","SC 14D9","SC 14D9/A","S-4","S-4/A","F-4","F-4/A","DEFM14A","25","25-NSE","15","15-12B","15-12G","15-15D"}
BLOCK_FORMS = {"SC TO-I","SC TO-I/A","SC TO-T","SC TO-T/A","SC TO-C","SC TO-C/A","SC 14D9","SC 14D9/A","S-4","S-4/A","F-4","F-4/A","DEFM14A","25","25-NSE","15","15-12B","15-12G","15-15D"}
BLOCK_8K_ITEMS = {"1.01":"MERGER_ACQUISITION","1.02":"TERMINAL_AGREEMENT","1.03":"BANKRUPTCY","3.01":"DELISTING","5.07":"BINDING_VOTE","8.01":"EXPLICIT_EVENT"}
MAX_AGE_DAYS = 45
_LOCK=threading.Lock(); _LAST=0.0

def _canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def _sha(x): return hashlib.sha256(x if isinstance(x,bytes) else str(x).encode()).hexdigest()
def _now(now=None): return now or dt.datetime.now(dt.timezone.utc)
def _enforcement_mode(observed=None):
    """Acceptance state is authoritative and never expires by clock; malformed state fails closed."""
    fallback=os.environ.get("ATLAS_CA_ENFORCEMENT","ENFORCE").upper()
    path=Path(os.environ.get("ATLAS_CA_ENFORCEMENT_STATE","/Users/yasser/scripts/.atlas_ca_enforcement_state.json"))
    if not path.exists(): return fallback
    try:
        state=json.loads(path.read_text())
        required={"schema_version","deployment_id","mode","created_at","unlock_receipt_sha256"}
        if set(state)!=required or state["schema_version"]!=1 or not isinstance(state["deployment_id"],str) or not state["deployment_id"]:
            return "BLOCK_NEW_TRADES"
        if state["mode"]=="BLOCK_NEW_TRADES" and state["unlock_receipt_sha256"] is None: return "BLOCK_NEW_TRADES"
        if state["mode"]=="UNBLOCKED" and isinstance(state["unlock_receipt_sha256"],str) and re.fullmatch(r"[0-9a-f]{64}",state["unlock_receipt_sha256"]): return "ENFORCE"
        return "BLOCK_NEW_TRADES"
    except Exception: return "BLOCK_NEW_TRADES"
def _date(x):
    try: return dt.date.fromisoformat(str(x)[:10])
    except Exception: return None

def normalize_submission(payload, ticker, now=None):
    if not isinstance(payload,dict): raise ValueError("MALFORMED_SUBMISSION")
    cik=str(payload.get("cik") or "").lstrip("0"); tickers=[str(x).upper() for x in payload.get("tickers",[]) if isinstance(x,str)]
    if not cik or not tickers: raise ValueError("INCOMPLETE_ISSUER_IDENTITY")
    recent=((payload.get("filings") or {}).get("recent") or {}); required=("accessionNumber","filingDate","form","items")
    if not all(isinstance(recent.get(k),list) for k in required): raise ValueError("MALFORMED_FILING_METADATA")
    if len({len(recent[k]) for k in required})!=1: raise ValueError("MALFORMED_PARALLEL_ARRAYS")
    events=[]; metadata_dates=[]
    for acc,day,form,items in zip(*(recent[k] for k in required)):
        form=str(form or "").upper().strip(); day=_date(day)
        if day: metadata_dates.append(day)
        if form not in FORMS: continue
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}",str(acc or "")) or not day: raise ValueError("MALFORMED_FILING")
        classes=[]
        if form in BLOCK_FORMS: classes=["TENDER_OFFER" if form.startswith("SC TO") or form.startswith("SC 14D9") else "MERGER_ACQUISITION" if form.startswith(("S-4","F-4","DEFM14A")) else "DELISTING_TERMINAL"]
        elif form.startswith("8-K"): classes=[BLOCK_8K_ITEMS[x] for x in sorted({x.strip() for x in str(items or "").split(",")} & set(BLOCK_8K_ITEMS))]
        events.append({"accession":acc,"filing_date":day.isoformat(),"form":form,"items":str(items or ""),"classes":classes})
    accessions={e["accession"] for e in events}; allowed={"MAJOR_SPLIT","LIQUIDATION_CANCELLATION","BANKRUPTCY","DELISTING","MERGER_ACQUISITION","TENDER_OFFER"}
    for fact in payload.get("structuredFilingFacts",[]):
        if not isinstance(fact,dict) or fact.get("accession") not in accessions or fact.get("event_class") not in allowed or fact.get("state") not in {"BINDING","EFFECTIVE","TERMINAL"}: raise ValueError("MALFORMED_STRUCTURED_FILING_FACT")
        for event in events:
            if event["accession"]==fact["accession"]:
                event["classes"].append(fact["event_class"]); event["explicit_state"]=fact["state"]
                if fact["event_class"]=="MAJOR_SPLIT":
                    ratio=fact.get("ratio")
                    if not isinstance(ratio,list) or len(ratio)!=2 or not all(isinstance(x,int) and x>0 for x in ratio) or max(ratio)/min(ratio)<4: raise ValueError("MALFORMED_OR_NONMAJOR_SPLIT_FACT")
    return {"cik":cik,"tickers":sorted(set(tickers)),"events":events,"metadata_latest":max(metadata_dates).isoformat() if metadata_dates else None,"source_sha256":_sha(_canon(payload))}

def reconcile(ticker, normalized, now=None):
    now=_now(now); ticker=str(ticker or "").upper()
    if ticker not in normalized["tickers"]: return DEFER,"ISSUER_IDENTITY_MISMATCH",[]
    latest=_date(normalized.get("metadata_latest"))
    if not latest or (now.date()-latest).days>MAX_AGE_DAYS: return DEFER,"SEC_EVIDENCE_STALE",[]
    fresh=[]; stale=False
    for e in normalized["events"]:
        age=(now.date()-_date(e["filing_date"])).days
        if age<0: return DEFER,"FUTURE_DATED_FILING",[]
        if age>MAX_AGE_DAYS: stale=True
        else: fresh.append(e)
    signatures={(e["filing_date"],tuple(e["classes"])) for e in fresh if e["classes"]}
    if any(not e["classes"] for e in fresh) and signatures: return DEFER,"CONFLICTING_FRESH_FILING_STATE",fresh
    binding=[e for e in fresh if e["classes"]]
    if binding: return BLOCK,"FRESH_BINDING_OR_TERMINAL_SEC_EVIDENCE",binding
    if stale and not fresh: return DEFER,"SEC_EVIDENCE_STALE",[]
    return CLEAR,"FRESH_SEC_CHECK_NO_ACTIVE_BINDING_EVENT",fresh

class Authority:
    def __init__(self, fixture_dir=None, cache_dir=None, now=None):
        self.fixture_dir=Path(fixture_dir or os.environ.get("ATLAS_CA_FIXTURE_DIR","")) if (fixture_dir or os.environ.get("ATLAS_CA_FIXTURE_DIR")) else None
        self.cache_dir=Path(cache_dir or os.environ.get("ATLAS_CA_CACHE_DIR","/tmp/atlas_ca_cache")); self.cache_dir.mkdir(parents=True,exist_ok=True); self.now=now
    def _fetch(self,ticker):
        if self.fixture_dir:
            p=self.fixture_dir/(ticker.upper()+".json")
            if not p.exists(): raise LookupError("UNKNOWN_ISSUER")
            return json.loads(p.read_text())
        contact=os.environ.get("ATLAS_SEC_CONTACT_ID");
        if not contact: raise RuntimeError("SEC_CONTACT_IDENTIFIER_UNAVAILABLE")
        mapping=json.loads((self.cache_dir/"company_tickers.json").read_text()) if (self.cache_dir/"company_tickers.json").exists() else None
        if mapping is None: mapping=self._http("https://www.sec.gov/files/company_tickers.json",contact); (self.cache_dir/"company_tickers.json").write_text(_canon(mapping))
        matches=[v for v in mapping.values() if str(v.get("ticker","")).upper()==ticker.upper()]
        if len(matches)!=1: raise LookupError("UNKNOWN_OR_AMBIGUOUS_ISSUER")
        return self._http(f"https://data.sec.gov/submissions/CIK{str(matches[0]['cik_str']).zfill(10)}.json",contact)
    def _http(self,url,contact):
        global _LAST
        with _LOCK:
            wait=max(0,.11-(time.monotonic()-_LAST))
            if wait: time.sleep(wait)
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":f"AtlasCorporateActionGate/1.0 {contact}","Accept-Encoding":"identity"}),timeout=8) as r: raw=r.read(8_000_001)
            _LAST=time.monotonic()
        if len(raw)>8_000_000: raise ValueError("SEC_RESPONSE_TOO_LARGE")
        return json.loads(raw)
    def decide(self,ticker,path="candidate",now=None):
        observed=_now(now or self.now); ticker=str(ticker or "").upper(); mode=_enforcement_mode(observed)
        if mode=="BLOCK_NEW_TRADES": outcome,reason,evidence=BLOCK,"ACCEPTANCE_NEW_TRADE_FREEZE",[]
        else:
            try: outcome,reason,evidence=reconcile(ticker,normalize_submission(self._fetch(ticker),ticker,observed),observed)
            except LookupError as e: outcome,reason,evidence=DEFER,str(e),[]
            except Exception as e: outcome,reason,evidence=DEFER,type(e).__name__+":"+str(e)[:80],[]
        body={"version":1,"ticker":ticker,"path":path,"outcome":outcome,"reason":reason,"observed_at":observed.isoformat(),"evidence":evidence}; body["receipt_sha256"]=_sha(_canon(body)); return body

def admission(ticker,path="candidate"):
    r=Authority().decide(ticker,path); return r["outcome"]==CLEAR,r
def enforce_automatic_write(ticker):
    ok,r=admission(ticker,"final_automatic_trade_write")
    if not ok: raise PermissionError(f"CORPORATE_ACTION_{r['outcome']}:{r['reason']}")
    return r
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("ticker"); p.add_argument("--path",default="cli"); print(_canon(Authority().decide(**vars(p.parse_args()))))
