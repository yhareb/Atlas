#!/usr/bin/env python3
"""Stdout-only shadow health: recency, integrity/FK, buckets, A/B, source write proof."""
import argparse, datetime as dt, json, sqlite3
from pathlib import Path
BUCKETS=("broker_confirmed_completed","anomalous_disputed","filled_pullbacks","signal_only_non_fills","current_open","shadow_policy_observations")
def main():
 p=argparse.ArgumentParser();p.add_argument("--shadow-db",default="/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/shadow/evidence.sqlite");p.add_argument("--max-age-hours",type=float,default=72);a=p.parse_args();out={"schema":"atlas-position-evidence-health-v2","ok":False,"db":a.shadow_db}
 try:
  c=sqlite3.connect(f"file:{Path(a.shadow_db).resolve()}?mode=ro",uri=True);quick=c.execute("PRAGMA quick_check").fetchone()[0];integrity=c.execute("PRAGMA integrity_check").fetchone()[0];fk=c.execute("PRAGMA foreign_key_check").fetchall();last=c.execute("SELECT max(baked_at) FROM runs").fetchone()[0];proof=c.execute("SELECT source_db_sha256_before,source_db_sha256_after,source_db_unchanged FROM runs ORDER BY baked_at DESC LIMIT 1").fetchone();counts={b:c.execute("SELECT count(*) FROM evidence WHERE bucket=?",(b,)).fetchone()[0] for b in BUCKETS};n=c.execute("SELECT count(*) FROM evidence").fetchone()[0];counts.update({"runs":c.execute("SELECT count(*) FROM runs").fetchone()[0],"evidence":n,"policy_A":c.execute("SELECT count(*) FROM policy_observations WHERE variant='A'").fetchone()[0],"policy_B":c.execute("SELECT count(*) FROM policy_observations WHERE variant='B'").fetchone()[0]});c.close();age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(last.replace("Z","+00:00"))).total_seconds()/3600 if last else None;write_ok=bool(proof and proof[2] and proof[0]==proof[1]);out.update({"quick_check":quick,"integrity_check":integrity,"foreign_key_violations":len(fk),"last_success_at":last,"age_hours":age,"counts":counts,"source_db_write_proof":{"before":proof[0] if proof else None,"after":proof[1] if proof else None,"unchanged":write_ok}});out["ok"]=quick==integrity=="ok" and not fk and last is not None and age<=a.max_age_hours and counts["policy_A"]==n==counts["policy_B"] and all(counts[b]>0 for b in BUCKETS) and write_ok
 except Exception as e:out["error"]=f"{type(e).__name__}: {e}"
 print(json.dumps(out,sort_keys=True));raise SystemExit(0 if out["ok"] else 1)
if __name__=="__main__":main()
