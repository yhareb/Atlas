#!/usr/bin/env python3
"""Append-only three-complete-trading-session shadow acceptance analyzer."""
import argparse, datetime as dt, hashlib, json, random, sqlite3

def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def verify(db, session_date, prod_db, minimum=20):
    con=sqlite3.connect(db); con.row_factory=sqlite3.Row
    rows=con.execute("SELECT * FROM receipts WHERE session_date=? ORDER BY receipt_id",(session_date,)).fetchall()
    if not rows: return {"session":session_date,"recorded":False,"reason":"NO_RECEIPTS"}
    paths={r["path"] for r in rows}; required={"pending_pullback","ema_retry","existing_holding","discovered_signal","dynamic_sector_peer"}
    # Independently recompute structural truth from immutable receipt evidence.
    errors=[]; provider_stats={}; disagreements=0
    for r in rows:
        ps=json.loads(r["providers_json"]); cov=json.loads(r["coverage_json"]); conf=json.loads(r["conflicts_json"])
        available=sum(bool(p.get("available")) for p in ps)
        expected="WOULD_DEFER" if conf.get("disagreement") or available<2 else ("WOULD_BLOCK" if json.loads(r["normalized_event_json"]) else "WOULD_CLEAR")
        if expected!=r["outcome"]: errors.append(r["receipt_id"])
        disagreements+=int(bool(conf.get("disagreement")))
        for p in ps:
            s=provider_stats.setdefault(p["provider"],{"checks":0,"available":0,"events":0,"latency_ms":0})
            s["checks"]+=1; s["available"]+=int(bool(p.get("available"))); s["events"]+=len(p.get("events") or []); s["latency_ms"]+=int(p.get("latency_ms") or 0)
    block_defer=[r for r in rows if r["outcome"]!="WOULD_CLEAR"]
    clears=[r for r in rows if r["outcome"]=="WOULD_CLEAR"]
    rng=random.Random(int(hashlib.sha256(("atlas-ca-shadow:"+session_date).encode()).hexdigest()[:16],16)); clear_sample=rng.sample(clears,min(len(clears),max(minimum,min(len(clears),minimum)))) if clears else []
    timings=[r["latency_ms"] for r in rows]; limit=min(r["production_limit_ms"] for r in rows)
    prod_sha=hashlib.sha256(open(prod_db,"rb").read()).hexdigest()
    run_shas={r[0] for r in con.execute("SELECT DISTINCT prod_db_sha_before FROM runs WHERE substr(started_at,1,10)=?",(session_date,))}
    invariant=bool(run_shas) and run_shas=={prod_sha}
    # A session is complete only after local 16:15 and all durable paths observed.
    now=dt.datetime.now().astimezone(); complete=(now.date()>dt.date.fromisoformat(session_date) or (now.date()==dt.date.fromisoformat(session_date) and now.hour>=16 and now.minute>=15)) and required<=paths
    record={"session_date":session_date,"verified_at":dt.datetime.now(dt.timezone.utc).isoformat(),"complete":int(complete),"receipt_count":len(rows),"path_coverage_json":canon({"observed":sorted(paths),"required":sorted(required),"complete":required<=paths}),"provider_stats_json":canon(provider_stats),"disagreement_json":canon({"count":disagreements}),"block_defer_verified":int(not errors),"clear_sample_size":len(clear_sample),"false_clear_count":sum(1 for e in errors if any(r["receipt_id"]==e and r["outcome"]=="WOULD_CLEAR" for r in rows)),"false_block_count":sum(1 for e in errors if any(r["receipt_id"]==e and r["outcome"]=="WOULD_BLOCK" for r in rows)),"timing_json":canon({"max_ms":max(timings),"limit_ms":limit,"within_limit":max(timings)<=limit}),"invariance_json":canon({"production_db_sha":prod_sha,"matches_run_snapshots":invariant}),"accepted":0,"status":"PENDING_THREE_COMPLETE_SESSIONS"}
    try:
        con.execute("INSERT INTO session_acceptance(session_date,verified_at,complete,receipt_count,path_coverage_json,provider_stats_json,disagreement_json,block_defer_verified,clear_sample_size,false_clear_count,false_block_count,timing_json,invariance_json,accepted,status) VALUES(:session_date,:verified_at,:complete,:receipt_count,:path_coverage_json,:provider_stats_json,:disagreement_json,:block_defer_verified,:clear_sample_size,:false_clear_count,:false_block_count,:timing_json,:invariance_json,:accepted,:status)",record); con.commit(); recorded=True
    except sqlite3.IntegrityError: recorded=False
    complete_sessions=con.execute("SELECT count(*) FROM session_acceptance WHERE complete=1 AND block_defer_verified=1 AND clear_sample_size>=20").fetchone()[0]; con.close()
    return {"session":session_date,"recorded":recorded,"complete":complete,"receipt_count":len(rows),"clear_sample_size":len(clear_sample),"independent_errors":len(errors),"production_invariant":invariant,"complete_qualifying_sessions":complete_sessions,"status":"SHADOW_RELEASE_CANDIDATE","enforcement":"DISABLED","accepted":False}
def main():
 p=argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--production-db",default="/Users/yasser/scripts/atlas.db"); p.add_argument("--session-date",default=dt.datetime.now().astimezone().date().isoformat()); print(json.dumps(verify(p.parse_args().db,p.parse_args().session_date,p.parse_args().production_db),sort_keys=True))
if __name__=="__main__": main()
