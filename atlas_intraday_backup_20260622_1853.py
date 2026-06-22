import os, sys, datetime, subprocess
SCRIPTS_DIR = "/Users/yasser/scripts"
sys.path.insert(0, SCRIPTS_DIR)

_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

def run_intraday():
    now = datetime.datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Atlas intraday loop starting...")
    # dry-run is the DEFAULT for atlas_manage.py (omit --live). No --dry-run flag exists.
    cmd = ["/usr/bin/python3", os.path.join(SCRIPTS_DIR, "atlas_manage.py")]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Fail loudly if the scan itself errored - never fake an action.
    if result.returncode != 0:
        print(f"ERROR: atlas_manage.py exited {result.returncode}. Scan did NOT run.")
        print("STDOUT:", result.stdout[-1000:])
        print("STDERR:", result.stderr[-1000:])
        sys.exit(1)

    out = result.stdout
    buys = sells = None
    for line in out.splitlines():
        if "Buys planned" in line:
            try: buys = int(line.split(":")[1].strip())
            except: pass
        if "Sells planned" in line:
            try: sells = int(line.split(":")[1].strip())
            except: pass
    if buys is None or sells is None:
        print("WARNING: Could not parse decision counts; not asserting an action.")
        print(out[-1200:])
    elif buys == 0 and sells == 0:
        print("Result: DO NOTHING. No new buys, no exits this cycle.")
    else:
        print(f"Result: ACTION - {buys} BUY(S), {sells} SELL(S). See Vault.")
        print(out)

    if result.stderr:
        print("Errors/Warnings:", result.stderr)

if __name__ == "__main__":
    run_intraday()
