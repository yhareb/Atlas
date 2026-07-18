"""Image-only auditor boundary and deterministic comparison orchestration."""
from __future__ import annotations
import json,subprocess,os
from pathlib import Path
PROFILE='atlas-registration-auditor'; MODEL='openai/gpt-5.6-sol'; PROVIDER='openrouter'; TIMEOUT_SECONDS=90
SCHEMA={'schema':'BrokerVisionAuditV1','observed':['ticker','side','quantity_text','price_text','execution_date','broker'],'field_certainty':'per field [0,1]','doubt':'boolean','doubt_reasons':'array'}
PROMPT='Inspect only the attached original broker image. Return strict JSON only matching: '+json.dumps(SCHEMA,sort_keys=True)+'. Do not use or request tools, OCR text, DB values, or external context.'
def audit_image(image_path, runner=None):
    """Hard-wall-clock one-turn boundary. runner is mandatory in staged tests and may invoke exact Hermes CLI in deployment."""
    path=Path(image_path)
    if not path.is_file(): return {'error_code':'IMAGE_UNAVAILABLE'}
    if runner is None: runner=hermes_cli_runner
    try:
        raw=runner(path,PROMPT,PROFILE,MODEL,TIMEOUT_SECONDS)
        out=json.loads(raw) if isinstance(raw,str) else raw
        if not isinstance(out,dict) or out.get('schema')!='BrokerVisionAuditV1' or not isinstance(out.get('observed'),dict): return {'error_code':'MALFORMED_OUTPUT'}
        return out
    except subprocess.TimeoutExpired:return {'error_code':'TIMEOUT_90S'}
    except json.JSONDecodeError:return {'error_code':'MALFORMED_OUTPUT'}
    except Exception as exc:return {'error_code':'PROVIDER_ERROR','error_type':type(exc).__name__}

def hermes_cli_runner(path,prompt,profile,model,timeout):
    """Exact staged Hermes CLI: staged home, image, provider/model, 90s, no tools."""
    home=str(Path(__file__).parents[1]/'config'/profile)
    cmd=['hermes','chat','-Q','--provider',PROVIDER,'-m',model,'--image',str(path),'-q',prompt]
    env={**os.environ,'HERMES_HOME':home,'HERMES_TOOLS':'none'}
    cp=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout,env=env,check=False)
    if cp.returncode: raise RuntimeError('hermes_exit_'+str(cp.returncode))
    return cp.stdout.strip()
