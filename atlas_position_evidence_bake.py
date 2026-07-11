#!/usr/bin/env python3
"""Snapshot-only append-only evidence bake with nonregressing high-water state."""
import argparse, datetime as dt, hashlib, json, os, sqlite3
from pathlib import Path
SCHEMA="atlas-position-evidence-snapshot-v2";VERSION="evidence-bake-v2.1.0"
BUCKETS=("broker_confirmed_completed","anomalous_disputed","filled_pullbacks","signal_only_non_fills","current_open","shadow_policy_observations")
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(x):return hashlib.sha256(x if isinstance(x,bytes) else x.encode()).hexdigest()
def safe_json(x):
 try:return json.loads(x) if isinstance(x,str) and x else {}
 except Exception:return {"unparsed":x,"conflict":"invalid signal_json"}
def indicators(bars,entry=None):
 b=[x for x in bars if x.get("close") is not None];cl=[float(x["close"]) for x in b]
 def ema(n):
  if not cl:return None
  z=cl[0];a=2/(n+1)
  for v in cl[1:]:z=a*v+(1-a)*z
  return round(z,6)
 tr=[]
 for i,x in enumerate(b):
  h=x.get("high");l=x.get("low");pc=b[i-1].get("close") if i else None
  if h is not None and l is not None:tr.append(max(float(h)-float(l),abs(float(h)-float(pc)),abs(float(l)-float(pc))) if pc is not None else float(h)-float(l))
 highs=[float(x["high"]) for x in b if x.get("high") is not None];lows=[float(x["low"]) for x in b if x.get("low") is not None];cur=cl[-1] if cl else None;peak=max(highs) if highs else None;trough=min(lows) if lows else None
 mfe=(peak-entry) if peak is not None and entry is not None else None;mae=(trough-entry) if trough is not None and entry is not None else None;profit=(cur-entry) if cur is not None and entry is not None else None
 return {"price":cur,"high_close":max(cl) if cl else None,"high":peak,"low":trough,"atr14":round(sum(tr[-14:])/len(tr[-14:]),6) if tr else None,"ema10":ema(10),"ema20":ema(20),"ema50":ema(50),"confirmed_swing_low":min(lows[-10:]) if lows else None,"mfe":mfe,"mae":mae,"peak_profit":mfe,"current_profit":profit,"giveback":(mfe-profit) if mfe is not None and profit is not None else None}
def schema(c):
 c.executescript("""PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;PRAGMA foreign_keys=ON;
 CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY,snapshot_sha256 TEXT NOT NULL,captured_at TEXT NOT NULL,baked_at TEXT NOT NULL,inserted INTEGER NOT NULL,source_db_sha256_before TEXT NOT NULL,source_db_sha256_after TEXT NOT NULL,source_db_unchanged INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS evidence(event_id TEXT PRIMARY KEY,bucket TEXT NOT NULL CHECK(bucket IN ('broker_confirmed_completed','anomalous_disputed','filled_pullbacks','signal_only_non_fills','current_open','shadow_policy_observations')),entity_key TEXT NOT NULL,source_ts TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(bucket,entity_key,source_ts,payload_sha256));
 CREATE TABLE IF NOT EXISTS policy_observations(observation_id TEXT PRIMARY KEY,evidence_event_id TEXT NOT NULL,variant TEXT NOT NULL CHECK(variant IN ('A','B')),old_stop REAL,old_target REAL,new_stop REAL,new_target REAL,stop_method TEXT NOT NULL,target_method TEXT NOT NULL,action TEXT NOT NULL,rejected_alternatives_json TEXT NOT NULL,params_json TEXT NOT NULL,policy_digest TEXT NOT NULL,policy_version TEXT NOT NULL,observation_json TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(evidence_event_id) REFERENCES evidence(event_id));
 CREATE TABLE IF NOT EXISTS entity_state(bucket TEXT NOT NULL,entity_key TEXT NOT NULL,high_water_ts TEXT NOT NULL,last_event_id TEXT NOT NULL,stale_count INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(bucket,entity_key),FOREIGN KEY(last_event_id) REFERENCES evidence(event_id));
 CREATE TRIGGER IF NOT EXISTS ev_no_u BEFORE UPDATE ON evidence BEGIN SELECT RAISE(ABORT,'append-only');END;CREATE TRIGGER IF NOT EXISTS ev_no_d BEFORE DELETE ON evidence BEGIN SELECT RAISE(ABORT,'append-only');END;
 CREATE TRIGGER IF NOT EXISTS po_no_u BEFORE UPDATE ON policy_observations BEGIN SELECT RAISE(ABORT,'append-only');END;CREATE TRIGGER IF NOT EXISTS po_no_d BEFORE DELETE ON policy_observations BEGIN SELECT RAISE(ABORT,'append-only');END;CREATE TRIGGER IF NOT EXISTS run_no_u BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'append-only');END;CREATE TRIGGER IF NOT EXISTS run_no_d BEFORE DELETE ON runs BEGIN SELECT RAISE(ABORT,'append-only');END;
 CREATE TRIGGER IF NOT EXISTS hw_no_regress BEFORE UPDATE OF high_water_ts ON entity_state WHEN NEW.high_water_ts<OLD.high_water_ts BEGIN SELECT RAISE(ABORT,'high-water regression');END;""")
def build_payload(bucket,row,snap):
 symbol=str(row["ticker"]).upper();p=snap.get("provider",{}).get(symbol,{});bars=p.get("bars",[]);sig=safe_json(row.get("signal_json"));entry=row.get("entry_price",sig.get("entry_price"));market=indicators(bars,float(entry) if entry is not None else None);notes=row.get("notes") or ""
 catalyst=sig.get("catalyst_reason") or row.get("catalyst") or (notes if "catalyst" in notes.lower() else None);cats=sig.get("sentiment_info",{}).get("news",[]) if isinstance(sig.get("sentiment_info"),dict) else []
 return {"bucket":bucket,"record":row,"setup":sig.get("signal") or row.get("signal") or notes.split(";")[0],"entry":{"original":entry,"current":row.get("current_price") or market["price"]},"stop":{"original":row.get("stop_loss") or sig.get("risk_card",{}).get("stop_loss") if isinstance(sig.get("risk_card"),dict) else row.get("stop_loss"),"current":row.get("stop_loss")},"target":{"original":row.get("target_price"),"current":row.get("target_price")},"market":market,"catalyst":{"text":catalyst,"timestamp":cats[0].get("date") if cats and isinstance(cats[0],dict) else None},"earnings_proximity":sig.get("earnings_context"),"sector":sig.get("fundamentals",{}).get("sector") if isinstance(sig.get("fundamentals"),dict) else None,"regime":sig.get("regime"),"rvol":sig.get("rvol"),"momentum":sig.get("indicator_info"),"provider":{"name":p.get("provider"),"dataset":p.get("dataset"),"adjusted":p.get("adjusted"),"request_id":p.get("provider_request_id"),"last_timestamp":bars[-1].get("provider_timestamp") if bars else None,"snapshot_captured_at":snap["captured_at"]},"completeness":{"market_bars":bool(bars),"entry":entry is not None,"atr":market["atr14"] is not None,"ema_set":all(market[x] is not None for x in ("ema10","ema20","ema50"))},"conflicts":(["TSM anomaly/dispute"] if str(row.get("ticker","")).upper()=="TSM" else [])+(["provider missing"] if not bars else [])}
def policy_obs(payload,variant):
 m=payload["market"];old_stop=payload["stop"]["current"];old_target=payload["target"]["current"]
 price=m.get("price");atr=m.get("atr14");entry=payload["entry"].get("original");catalyst=payload["catalyst"].get("text")
 def candidate(name,value,method,params=None,reason=None):
  return {"name":name,"value":round(value,6) if isinstance(value,(int,float)) else "INCOMPLETE","method":method,"formula":method,"params":params or {},"rejected_reason":reason if value is None else None,"provenance":{"market_provider":payload["provider"],"snapshot_record":payload["record"].get("id")}}
 stop_specs=[("persisted_stop",old_stop,"record.stop.current",{}),("breakeven",entry,"entry.original",{}),("atr_chandelier_low",price-3*atr if price is not None and atr is not None else None,"price-3*ATR14",{"atr_multiple":3}),("atr_chandelier_high",price-1.5*atr if price is not None and atr is not None else None,"price-1.5*ATR14",{"atr_multiple":1.5}),("ema10_buffer",m.get("ema10")-.25*atr if m.get("ema10") is not None and atr is not None else None,"EMA10-0.25*ATR14",{}),("ema20_buffer",m.get("ema20")-.25*atr if m.get("ema20") is not None and atr is not None else None,"EMA20-0.25*ATR14",{}),("ema50_buffer",m.get("ema50")-.25*atr if m.get("ema50") is not None and atr is not None else None,"EMA50-0.25*ATR14",{}),("confirmed_swing_buffer",m.get("confirmed_swing_low")-.25*atr if m.get("confirmed_swing_low") is not None and atr is not None else None,"swing_low-0.25*ATR14",{}),("giveback",price-m.get("giveback") if price is not None and m.get("giveback") is not None else None,"price-giveback",{}),("hybrid",max([x for x in (price-1.5*atr if price is not None and atr is not None else None,m.get("ema20"),m.get("confirmed_swing_low")) if x is not None],default=None),"max(chandelier_high,EMA20,swing_low)",{})]
 target_specs=[("keep",old_target,"record.target.current",{}),("atr_zone_low",price+1.5*atr if price is not None and atr is not None else None,"price+1.5*ATR14",{}),("atr_zone_high",price+3*atr if price is not None and atr is not None else None,"price+3*ATR14",{}),("r_multiple_low",entry+2*(entry-old_stop) if entry is not None and old_stop is not None else None,"entry+2R",{}),("r_multiple_high",entry+3*(entry-old_stop) if entry is not None and old_stop is not None else None,"entry+3R",{}),("resistance_breakout",m.get("high"),"observed_180d_high",{}),("trend_extension",price+2*atr if price is not None and atr is not None else None,"price+2*ATR14",{}),("contraction_lowering",m.get("high_close"),"observed_high_close",{}),("partial_runner",[old_target,m.get("high")] if old_target is not None and m.get("high") is not None else None,"partial_at_persisted_target+runner_to_high",{})]
 stop_allowed=variant=="A"
 stops=[candidate(n,v if stop_allowed else None,f,p,"variant B blocks stops" if variant=="B" else "missing inputs") for n,v,f,p in stop_specs]
 targets=[candidate(n,None,f,p,"target advice blocked by variant policy" if variant=="A" else "variant B blocks targets") for n,v,f,p in target_specs]
 new_stop=None;new_target=None;sm="CANDIDATES_RECORDED_NO_SELECTION" if stop_allowed else "BLOCKED";tm="BLOCKED";action="OBSERVE_ONLY"
 params={"verified_inputs":{"price":price,"atr14":atr,"entry":entry,"catalyst":catalyst}};rejected=["select_candidate","recommendation","broker_action","production_mutation","invent_target"]
 core={"variant":variant,"old_stop":old_stop,"old_target":old_target,"new_stop":new_stop,"new_target":new_target,"stop_method":sm,"target_method":tm,"action":action,"stop_candidates":stops,"target_candidates":targets,"rejected_alternatives":rejected,"params":params,"policy_version":VERSION,"selection":None,"recommendation":None,"action_authority":False};core["policy_digest"]=sha(canon(core));return core
def bake(snapshot,shadow_db,baked_at=None):
 snap=json.loads(Path(snapshot).read_bytes());claimed=snap.pop("content_sha256",None)
 if snap.get("schema")!=SCHEMA or claimed!=sha(canon(snap)):raise ValueError("snapshot schema/content digest mismatch")
 snap["content_sha256"]=claimed
 if not snap.get("source",{}).get("db_unchanged") or snap["source"].get("db_sha256_before")!=snap["source"].get("db_sha256_after"):raise ValueError("source DB write proof failed")
 run_id=sha(claimed+"|"+VERSION);baked_at=baked_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z");db=Path(shadow_db);db.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(db);schema(c)
 if c.execute("SELECT 1 FROM runs WHERE run_id=?",(run_id,)).fetchone():c.close();return {"status":"IDEMPOTENT","run_id":run_id,"inserted":0}
 inserted=0;seen=set()
 try:
  c.execute("BEGIN IMMEDIATE")
  for bucket in BUCKETS:
   for row in snap.get("buckets",{}).get(bucket,[]):
    key=str(row["id"]);seen.add((bucket,key));source_ts=str(row.get("updated_at") or row.get("filled_at") or row.get("armed_at") or snap["captured_at"]).replace(" ","T");payload=build_payload(bucket,row,snap);pd=sha(canon(payload));eid=sha(f"{bucket}|{key}|{source_ts}|{pd}");before=c.total_changes;c.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?,?,?)",(eid,bucket,key,source_ts,claimed,canon(payload),pd,baked_at));was=c.total_changes-before;inserted+=was
    if was:
     for variant in ("A","B"):
      o=policy_obs(payload,variant);oid=sha(eid+"|"+variant+"|"+o["policy_digest"]);c.execute("INSERT INTO policy_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(oid,eid,variant,o["old_stop"],o["old_target"],o["new_stop"],o["new_target"],o["stop_method"],o["target_method"],o["action"],canon(o["rejected_alternatives"]),canon(o["params"]),o["policy_digest"],VERSION,canon(o),baked_at))
    st=c.execute("SELECT high_water_ts FROM entity_state WHERE bucket=? AND entity_key=?",(bucket,key)).fetchone()
    if not st:c.execute("INSERT INTO entity_state VALUES(?,?,?,?,0)",(bucket,key,source_ts,eid))
    elif source_ts>=st[0]:c.execute("UPDATE entity_state SET high_water_ts=?,last_event_id=?,stale_count=0 WHERE bucket=? AND entity_key=?",(source_ts,eid,bucket,key))
  for bucket,key in c.execute("SELECT bucket,entity_key FROM entity_state").fetchall():
   if (bucket,key) not in seen:c.execute("UPDATE entity_state SET stale_count=stale_count+1 WHERE bucket=? AND entity_key=?",(bucket,key))
  s=snap["source"];c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",(run_id,claimed,snap["captured_at"],baked_at,inserted,s["db_sha256_before"],s["db_sha256_after"],1));c.commit()
 except Exception:c.rollback();c.close();raise
 c.close();os.chmod(db,0o600);return {"status":"BAKED","run_id":run_id,"inserted":inserted,"snapshot_sha256":claimed}
def main():
 p=argparse.ArgumentParser();p.add_argument("--snapshot",required=True);p.add_argument("--shadow-db",default=os.environ.get("ATLAS_EVIDENCE_SHADOW_DB","/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/shadow/evidence.sqlite"));p.add_argument("--baked-at");a=p.parse_args();print(json.dumps(bake(a.snapshot,a.shadow_db,a.baked_at),sort_keys=True))
if __name__=="__main__":main()
