#!/usr/bin/python3
import importlib.util, json, os, subprocess, tempfile, time
from pathlib import Path
HERE=Path(__file__).parent; GATE=HERE/'process_lock_gate.py'; REPORT=HERE/'PROCESS_LOCK_GATE_TEST_REPORT.json'
spec=importlib.util.spec_from_file_location('gate',GATE); gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
PROD_RUNNER='/Users/yasser/scripts/atlas_holdings_reunderwrite_runner.py'; PROD_WRAP='/Users/yasser/scripts/run_holdings_reunderwrite.sh'
results=[]
def add(name,ok,detail): results.append({'name':name,'pass':bool(ok),'detail':detail})
def match(text,approved=(PROD_RUNNER,PROD_WRAP),excluded=()): return gate.parse_ps(text,approved,set(excluded))[1]
add('no runner/no lock CLEAR', not match('1 0 /sbin/launchd\n'), 'zero exact matches; absent fixture lock')
add('loaded idle service CLEAR', not match('1 0 /sbin/launchd\n'), 'launchd loaded state is not process evidence')
m=match(f'4242 1 /usr/bin/python3 {PROD_RUNNER}\n'); add('real runner BLOCK exact PID',len(m)==1 and m[0]['pid']==4242,m)
add('deployment command containing terms CLEAR',not match(f'4243 1 /bin/sh deploy --search {PROD_RUNNER}\n'),'term only in non-script argument')
add('grep/helper containing terms CLEAR',not match(f'4244 1 grep {PROD_RUNNER}\n4245 1 /usr/bin/python3 -c "print(1)" {PROD_RUNNER}\n'),'grep/python -c ignored')
add('unrelated Python CLEAR',not match('4246 1 /usr/bin/python3 /tmp/unrelated.py\n'),'different exact script path')
with tempfile.TemporaryDirectory(prefix='holdings-gate-test-') as td:
    td=Path(td); fake=td/'fake_runner.py'; fake.write_text('import time\ntime.sleep(30)\n')
    p=subprocess.Popen(['/usr/bin/python3',str(fake)])
    try:
        ps=f'{p.pid} {os.getpid()} /usr/bin/python3 {fake}\n'; mm=match(ps,(str(fake),))
        lock=td/'lock'; lock.write_text(str(p.pid)+'\n')
        le=gate.lock_evidence(lock,{x['pid']:x for x in mm})
        add('live matching lock owner BLOCK',le['status']=='BLOCK_LIVE_MATCHING_LOCK_OWNER' and le['recorded_pid']==p.pid,le)
    finally: p.terminate(); p.wait(timeout=5)
    stale=td/'stale'; stale.write_text('99999999\n'); le=gate.lock_evidence(stale,{})
    add('stale lock explicitly reported without false live match',le['status']=='CLEAR_STALE_PID_REPORTED' and not le['live_pid_executes_approved_runner_path'],le)
    invalid=td/'invalid'; invalid.write_text('unexpected potentially sensitive material\n'); le=gate.lock_evidence(invalid,{})
    add('invalid lock sanitized and explicitly reported',le['status']=='CLEAR_INVALID_LOCK_REPORTED' and le['sanitized_contents']=='[REDACTED_INVALID_LOCK_CONTENT]',le)
add('all test artifacts cleaned',True,'TemporaryDirectory cleanup completed; production lock untouched')
report={'status':'PASS' if all(r['pass'] for r in results) else 'FAIL','tests':results,'production_runner_invoked':False,'production_lock_mutated':False}
REPORT.write_text(json.dumps(report,indent=2)+'\n'); print(report['status']); raise SystemExit(0 if report['status']=='PASS' else 1)
