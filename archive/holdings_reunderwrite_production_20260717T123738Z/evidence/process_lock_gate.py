#!/usr/bin/python3
"""PID-aware holdings deployment preflight. Read-only: never kills or removes locks."""
import argparse, datetime as dt, json, os, shlex, subprocess, sys, time
from pathlib import Path

DEFAULT_APPROVED = [
    "/Users/yasser/scripts/atlas_holdings_reunderwrite_runner.py",
    "/Users/yasser/scripts/run_holdings_reunderwrite.sh",
]
DEFAULT_LOCK = "/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/run/daily_holdings_reunderwrite.lock"
INTERPRETERS = {"python", "python3", "python3.9", "python3.11", "sh", "bash", "zsh", "dash", "ksh"}

def argv_from_command(command):
    try: return shlex.split(command, posix=True)
    except ValueError: return []

def executed_script(argv):
    if not argv: return None, "empty argv"
    a0 = argv[0]
    base = os.path.basename(a0)
    if a0.startswith("/") and a0.endswith((".py", ".sh")):
        return a0, "direct script argv[0]"
    if base not in INTERPRETERS and not base.startswith("python"):
        return None, "non-script executable"
    is_python = base.startswith("python")
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            i += 1
            return (argv[i], "interpreter script after --") if i < len(argv) else (None, "no script")
        if is_python and token in ("-c", "-m"):
            return None, "python helper/module, not script execution"
        if token.startswith("-"):
            i += 1
            continue
        return token, "interpreter script argv"
    return None, "no script argv"

def parse_ps(text, approved, excluded):
    rows, matches = [], []
    approved = set(approved)
    for raw in text.splitlines():
        parts = raw.strip().split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit(): continue
        pid, ppid, cmd = int(parts[0]), int(parts[1]), parts[2]
        script, reason = executed_script(argv_from_command(cmd))
        row = {"pid": pid, "ppid": ppid, "command": cmd, "parsed_script": script, "parse_reason": reason}
        rows.append(row)
        if pid not in excluded and script in approved:
            row = dict(row); row["match_reason"] = "exact approved execution path in script position"
            matches.append(row)
    return rows, matches

def ancestry(ps_rows, pid):
    by_pid = {r["pid"]: r for r in ps_rows}; out=[]; seen=set()
    while pid and pid not in seen:
        seen.add(pid); row=by_pid.get(pid)
        if not row: break
        out.append(row); pid=row["ppid"]
    return out

def start_time(pid):
    cp=subprocess.run(["/bin/ps","-p",str(pid),"-o","lstart="],text=True,capture_output=True)
    return cp.stdout.strip() or None

def pid_alive(pid):
    if not isinstance(pid,int) or pid <= 0: return False
    try: os.kill(pid,0); return True
    except (ProcessLookupError, PermissionError): return False

def lock_evidence(path, matches_by_pid):
    p=Path(path); ev={"path":str(p),"exists":p.exists()}
    if not p.exists(): return ev | {"status":"CLEAR_ABSENT"}
    st=p.stat(); ev["age_seconds"]=max(0,time.time()-st.st_mtime)
    try: raw=p.read_text(errors="replace")[:4096]
    except Exception as e: raw=""; ev["read_error"]=type(e).__name__
    # Lock format is expected to contain only a decimal PID. Anything else is redacted.
    clean=raw.strip(); ev["sanitized_contents"] = clean if clean.isdigit() else "[REDACTED_INVALID_LOCK_CONTENT]"
    try: rec=int(clean) if clean.isdigit() else None
    except Exception: rec=None
    ev["recorded_pid"]=rec; ev["pid_liveness"]=pid_alive(rec)
    ev["live_pid_executes_approved_runner_path"] = bool(rec and rec in matches_by_pid)
    if ev["live_pid_executes_approved_runner_path"]:
        ev["status"]="BLOCK_LIVE_MATCHING_LOCK_OWNER"
    elif rec is None:
        ev["status"]="CLEAR_INVALID_LOCK_REPORTED"
    elif ev["pid_liveness"]:
        ev["status"]="CLEAR_LIVE_UNRELATED_PID_REPORTED"
    else:
        ev["status"]="CLEAR_STALE_PID_REPORTED"
    return ev

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True); ap.add_argument("--lock",default=DEFAULT_LOCK)
    ap.add_argument("--approved",action="append",default=[]); ap.add_argument("--ps-fixture")
    ap.add_argument("--launchd-fixture")
    ns=ap.parse_args(); approved=ns.approved or DEFAULT_APPROVED
    deployment_pid=os.getpid(); deployment_ppid=os.getppid()
    if ns.ps_fixture: ps_text=Path(ns.ps_fixture).read_text()
    else: ps_text=subprocess.run(["/bin/ps","-axo","pid=,ppid=,command="],text=True,capture_output=True,check=True).stdout
    rows,_=parse_ps(ps_text,approved,set())
    ancestors=ancestry(rows,deployment_pid); excluded={r["pid"] for r in ancestors}
    _,matches=parse_ps(ps_text,approved,excluded)
    for m in matches: m["start_time"]=start_time(m["pid"]) if not ns.ps_fixture else "fixture"
    label="com.atlas.holdings_reunderwrite"
    if ns.launchd_fixture is not None: launch_state=ns.launchd_fixture
    else:
        cp=subprocess.run(["/bin/launchctl","print",f"gui/{os.getuid()}/{label}"],text=True,capture_output=True)
        launch_state=(cp.stdout+cp.stderr)
    service_pid=None
    for line in launch_state.splitlines():
        s=line.strip()
        if s.startswith("pid ="):
            try: service_pid=int(s.split("=",1)[1])
            except ValueError: pass
    lock=lock_evidence(ns.lock,{m["pid"]:m for m in matches})
    status="BLOCK" if matches or lock["status"].startswith("BLOCK") else "CLEAR"
    ev={"timestamp_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"status":status,
        "deployment_pid":deployment_pid,"deployment_ppid":deployment_ppid,"ancestry":ancestors,
        "approved_exact_paths":approved,"ps_command":"/bin/ps -axo pid=,ppid=,command=",
        "ps_output":ps_text,"matched_processes":matches,"launchd_label":label,
        "launchd_state":launch_state,"service_pid":service_pid,"lock":lock}
    Path(ns.evidence).parent.mkdir(parents=True,exist_ok=True); Path(ns.evidence).write_text(json.dumps(ev,indent=2)+"\n")
    print(status); return 3 if status=="BLOCK" else 0
if __name__=="__main__": sys.exit(main())
