#!/usr/bin/env python3
"""Isolated, non-authoritative corporate-actions shadow observer.

Reads Atlas production SQLite in immutable/query-only mode, calls only public
provider HTTPS APIs using inherited process environment, and appends receipts
only to its own SQLite database. It cannot admit, reject, report, notify, trade,
or write Atlas state.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sqlite3, ssl, sys, time, urllib.parse, urllib.request
from pathlib import Path

STATUS = "SHADOW_RELEASE_CANDIDATE"
OUTCOMES = ("WOULD_CLEAR", "WOULD_BLOCK", "WOULD_DEFER")
PROVIDERS = ("BENZINGA_MA", "MASSIVE", "EODHD")
DEFAULT_PROD_DB = "/Users/yasser/scripts/atlas.db"
DEFAULT_SHADOW_DB = "/Users/yasser/Library/Application Support/AtlasCorporateActionsShadow/shadow.sqlite3"
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
 mode TEXT NOT NULL, status TEXT NOT NULL, enforcement_enabled INTEGER NOT NULL CHECK(enforcement_enabled=0),
 prod_db_sha_before TEXT NOT NULL, prod_db_sha_after TEXT, candidate_count INTEGER NOT NULL DEFAULT 0,
 receipt_count INTEGER NOT NULL DEFAULT 0, elapsed_ms INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS receipts(
 receipt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_date TEXT NOT NULL,
 observed_at TEXT NOT NULL, candidate TEXT NOT NULL, path TEXT NOT NULL,
 idempotency_key TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('WOULD_CLEAR','WOULD_BLOCK','WOULD_DEFER')),
 reason TEXT NOT NULL, normalized_event_json TEXT NOT NULL, coverage_json TEXT NOT NULL,
 providers_json TEXT NOT NULL, provenance_json TEXT NOT NULL, freshness_json TEXT NOT NULL,
 conflicts_json TEXT NOT NULL, latency_ms INTEGER NOT NULL, production_limit_ms INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(run_id) REFERENCES runs(run_id),
 UNIQUE(session_date,path,idempotency_key));
CREATE TABLE IF NOT EXISTS session_acceptance(
 session_date TEXT PRIMARY KEY, verified_at TEXT NOT NULL, complete INTEGER NOT NULL,
 receipt_count INTEGER NOT NULL, path_coverage_json TEXT NOT NULL, provider_stats_json TEXT NOT NULL,
 disagreement_json TEXT NOT NULL, block_defer_verified INTEGER NOT NULL, clear_sample_size INTEGER NOT NULL,
 false_clear_count INTEGER NOT NULL, false_block_count INTEGER NOT NULL, timing_json TEXT NOT NULL,
 invariance_json TEXT NOT NULL, accepted INTEGER NOT NULL CHECK(accepted=0), status TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS sessions_no_update BEFORE UPDATE ON session_acceptance BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS sessions_no_delete BEFORE DELETE ON session_acceptance BEGIN SELECT RAISE(ABORT,'append-only'); END;
"""

def canon(x): return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def file_sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()
def utcnow(): return dt.datetime.now(dt.timezone.utc)
def symbol(x):
    s="".join(c for c in str(x or "").upper().strip() if c.isalnum() or c in ".-")
    return s[:16]

def production_ro(path):
    con=sqlite3.connect("file:"+urllib.parse.quote(str(Path(path).resolve()))+"?mode=ro&immutable=1", uri=True)
    con.row_factory=sqlite3.Row; con.execute("PRAGMA query_only=ON")
    return con

def collect_candidates(con, limit):
    """Every concrete candidate path in the production manager assembly."""
    paths=[]
    queries=(
      ("pending_pullback", "SELECT id,ticker,updated_at AS ts FROM pending_pullbacks WHERE status='WAITING' ORDER BY id"),
      ("ema_retry", "SELECT id,ticker,last_seen_at AS ts FROM ema_retry_candidates WHERE status='WAITING' ORDER BY id"),
      ("existing_holding", "SELECT id,ticker,updated_at AS ts FROM trades WHERE status='OPEN' ORDER BY id"),
      ("discovered_signal", "SELECT id,ticker,timestamp AS ts FROM signals WHERE ticker IS NOT NULL AND timestamp >= datetime('now','-3 days') ORDER BY id DESC"),
    )
    for path,q in queries:
        try:
            query_rows=con.execute(q).fetchall()
            for r in query_rows:
                t=symbol(r["ticker"])
                if t: paths.append({"candidate":t,"path":path,"source_row_id":str(r["id"]),"source_timestamp":str(r["ts"] or "")})
            if not query_rows:
                paths.append({"candidate":"_NO_CANDIDATE_","path":path,"source_row_id":"0","source_timestamp":""})
        except sqlite3.Error:
            # A missing path is represented explicitly, not silently skipped.
            paths.append({"candidate":"_PATH_UNAVAILABLE_","path":path,"source_row_id":"0","source_timestamp":""})
    # Dynamic sector peers have no durable table. Production logs/state are read-only evidence.
    log=Path("/Users/yasser/scripts/atlas_manage.log")
    dynamic_before=len(paths)
    if log.exists():
        try:
            for line_no,line in enumerate(log.read_text(errors="replace").splitlines()[-5000:],1):
                if "sector" in line.lower() and "peer" in line.lower():
                    for token in line.replace(","," ").split():
                        t=symbol(token.strip("[](){}:'\""))
                        if 1 <= len(t) <= 6 and t.isalpha():
                            paths.append({"candidate":t,"path":"dynamic_sector_peer","source_row_id":str(line_no),"source_timestamp":""})
        except OSError: pass
    if not any(x["path"]=="dynamic_sector_peer" for x in paths[dynamic_before:]):
        paths.append({"candidate":"_NO_CANDIDATE_","path":"dynamic_sector_peer","source_row_id":"0","source_timestamp":""})
    # Preserve path identity while deduplicating source repetitions.
    seen=set(); out=[]
    for x in paths:
        key=(x["path"],x["candidate"])
        if key not in seen: seen.add(key); out.append(x)
    if not limit or len(out)<=limit: return out
    # A bound may reduce volume, never candidate-path coverage.
    first=[]; represented=set()
    for x in out:
        if x["path"] not in represented: first.append(x); represented.add(x["path"])
    chosen={(x["path"],x["candidate"]) for x in first}
    return (first+[x for x in out if (x["path"],x["candidate"]) not in chosen])[:max(limit,len(first))]

def http_json(url, params, timeout):
    safe={k:v for k,v in params.items() if v}
    req=urllib.request.Request(url+"?"+urllib.parse.urlencode(safe),headers={"Accept":"application/json","User-Agent":"Atlas-CA-Shadow/1"})
    with urllib.request.urlopen(req,timeout=timeout,context=ssl.create_default_context()) as r:
        if r.status != 200: raise RuntimeError("HTTP_STATUS")
        raw=r.read(4_000_001)
    if len(raw)>4_000_000: raise ValueError("RESPONSE_TOO_LARGE")
    return json.loads(raw),sha_bytes(raw)

def provider_observe(ticker, timeout, no_network=False):
    if ticker.startswith("_"):
        return [{"provider":name,"credential_source":"PROCESS_ENV_NAME_ONLY","available":False,"events":[],"response_sha256":None,"latency_ms":0,"error_type":"NoCandidate","reason":"PATH_COVERAGE_ONLY"} for name in PROVIDERS]
    specs=(
      ("BENZINGA_MA","BENZINGA_API_KEY","https://api.benzinga.com/api/v2.1/calendar/ma",{"tickers":ticker},"token"),
      ("MASSIVE","MASSIVE_API_KEY",f"https://api.massive.com/v3/reference/tickers/{urllib.parse.quote(ticker)}",{},"apiKey"),
      ("EODHD","EODHD_API_KEY",f"https://eodhd.com/api/fundamentals/{urllib.parse.quote(ticker)}.US",{"fmt":"json"},"api_token"),
    )
    out=[]
    for name,env,url,params,keyname in specs:
        started=time.monotonic(); key=os.environ.get(env,"")
        item={"provider":name,"credential_source":"PROCESS_ENV_NAME_ONLY","available":False,"events":[],"response_sha256":None}
        try:
            if no_network: raise RuntimeError("BOUNDED_SMOKE_NO_NETWORK")
            if not key: raise RuntimeError("MISSING_PROCESS_ENV")
            body,digest=http_json(url,{**params,keyname:key},timeout)
            item.update(available=True,response_sha256=digest,events=extract_events(name,ticker,body))
        except Exception as e: item["error_type"]=type(e).__name__; item["reason"]=str(e)[:64]
        item["latency_ms"]=round((time.monotonic()-started)*1000); out.append(item)
    return out

def extract_events(provider,ticker,body):
    events=[]
    if provider=="BENZINGA_MA":
        rows=(body.get("ma") or body.get("mergers_acquisitions") or body.get("results") or []) if isinstance(body,dict) else body
        for r in rows if isinstance(rows,list) else []:
            rt=symbol(r.get("ticker") or r.get("target_ticker")) if isinstance(r,dict) else ""
            if rt==ticker: events.append(normalize_event(provider,ticker,r))
    elif provider=="MASSIVE" and isinstance(body,dict) and isinstance(body.get("results"),dict):
        r=body["results"]
        if r.get("active") is False: events.append({"ticker":ticker,"type":"DELISTING","status":"EFFECTIVE" if r.get("delisted_utc") else "ANNOUNCED","effective_date":r.get("delisted_utc"),"provider":provider})
    elif provider=="EODHD" and isinstance(body,dict):
        general=body.get("General") or {}; d=general.get("DelistedDate") or general.get("Delisted")
        if d: events.append({"ticker":ticker,"type":"DELISTING","status":"EFFECTIVE","effective_date":d,"provider":provider})
        for day,item in ((body.get("SplitsDividends") or {}).get("Splits") or {}).items(): events.append({"ticker":ticker,"type":"SPLIT","status":"EFFECTIVE","effective_date":day,"ratio":item.get("split") if isinstance(item,dict) else item,"provider":provider})
    return events[:100]

def normalize_event(provider,ticker,r):
    return {"ticker":ticker,"type":str(r.get("event_type") or r.get("type") or "OTHER").upper()[:40],"status":str(r.get("status") or r.get("deal_status") or "UNKNOWN").upper()[:40],"effective_date":r.get("effective_date") or r.get("completed_date"),"provider":provider}

def decide(candidate, providers, now):
    available=[p for p in providers if p["available"]]; events=[e for p in available for e in p["events"]]
    identities={canon({k:e.get(k) for k in ("type","status","effective_date","ratio")}) for e in events}
    conflicts=len(identities)>1 and len({e.get("provider") for e in events})>1
    active=any(e.get("status") in ("ANNOUNCED","PENDING","ACTIVE","OFFER_OPEN","APPROVED","COMPLETED","EFFECTIVE") for e in events)
    if conflicts: outcome,reason="WOULD_DEFER","PROVIDER_DISAGREEMENT"
    elif active: outcome,reason="WOULD_BLOCK","ACTIVE_OR_EFFECTIVE_CORPORATE_ACTION"
    elif len(available)<2: outcome,reason="WOULD_DEFER","INSUFFICIENT_FRESH_PROVIDER_COVERAGE"
    else: outcome,reason="WOULD_CLEAR","TWO_PROVIDER_COVERAGE_NO_BLOCKING_EVENT"
    return outcome,reason,events,{"available":len(available),"required":2,"complete":len(available)>=2},{"observed_at":now.isoformat(),"max_age_hours":36,"fresh":len(available)>=2},{"disagreement":conflicts,"identity_count":len(identities)}

def ensure_shadow(path):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); os.chmod(p.parent,0o700)
    con=sqlite3.connect(p,timeout=30); con.executescript(SCHEMA); con.commit(); os.chmod(p,0o600); return con

def run(args):
    started=utcnow(); prod_before=file_sha(args.production_db); run_id=sha_bytes((started.isoformat()+args.mode).encode())[:24]
    out=ensure_shadow(args.shadow_db)
    out.execute("INSERT INTO runs(run_id,started_at,mode,status,enforcement_enabled,prod_db_sha_before) VALUES(?,?,?,?,0,?)",(run_id,started.isoformat(),args.mode,STATUS,prod_before)); out.commit()
    count=0
    try:
        with production_ro(args.production_db) as prod: candidates=collect_candidates(prod,args.max_candidates)
        for c in candidates:
            one=time.monotonic(); observed=utcnow(); providers=provider_observe(c["candidate"],args.timeout,args.no_network)
            outcome,reason,events,coverage,freshness,conflicts=decide(c,providers,observed)
            idem=sha_bytes(canon({"session":args.session_date,"path":c["path"],"candidate":c["candidate"]}).encode())
            receipt_id=sha_bytes((run_id+idem).encode())
            provenance={"production_db":str(Path(args.production_db).resolve()),"read_mode":"immutable_query_only","source_row_id":c["source_row_id"],"source_timestamp":c["source_timestamp"],"observer":"independent_non_authoritative"}
            latency=round((time.monotonic()-one)*1000)
            try:
                out.execute("INSERT INTO receipts(receipt_id,run_id,session_date,observed_at,candidate,path,idempotency_key,outcome,reason,normalized_event_json,coverage_json,providers_json,provenance_json,freshness_json,conflicts_json,latency_ms,production_limit_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(receipt_id,run_id,args.session_date,observed.isoformat(),c["candidate"],c["path"],idem,outcome,reason,canon(events),canon(coverage),canon(providers),canon(provenance),canon(freshness),canon(conflicts),latency,args.production_limit_ms)); out.commit(); count+=1
            except sqlite3.IntegrityError: pass # exactly one durable receipt per session/path/key
        prod_after=file_sha(args.production_db)
        if prod_after!=prod_before: raise RuntimeError("PRODUCTION_DB_INVARIANCE_FAILURE")
        elapsed=round((time.monotonic()-time.mktime(started.timetuple()))*1000) if False else round((utcnow()-started).total_seconds()*1000)
        out.execute("UPDATE runs SET completed_at=?,prod_db_sha_after=?,candidate_count=?,receipt_count=?,elapsed_ms=? WHERE run_id=?",(utcnow().isoformat(),prod_after,len(candidates),count,elapsed,run_id)); out.commit()
    except Exception as e:
        out.execute("UPDATE runs SET completed_at=?,error=? WHERE run_id=?",(utcnow().isoformat(),type(e).__name__,run_id)); out.commit(); raise
    finally: out.close()
    print(canon({"run_id":run_id,"status":STATUS,"enforcement":"DISABLED","candidates":len(candidates),"receipts_appended":count,"production_db_unchanged":prod_before==prod_after}))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--production-db",default=DEFAULT_PROD_DB); p.add_argument("--shadow-db",default=DEFAULT_SHADOW_DB); p.add_argument("--max-candidates",type=int,default=250); p.add_argument("--timeout",type=float,default=4); p.add_argument("--production-limit-ms",type=int,default=8000); p.add_argument("--mode",choices=("scheduled","smoke"),default="scheduled"); p.add_argument("--no-network",action="store_true"); p.add_argument("--session-date",default=dt.datetime.now().astimezone().date().isoformat()); args=p.parse_args(); run(args)
if __name__=="__main__": main()
