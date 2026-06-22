#!/usr/bin/env python3
"""
atlas_daily.py  —  Atlas v2 automated daily driver (launchd entry point)
============================================================================

This is what launchd runs every market day. It exists so the schedule has a
single, robust entry point that:

  1. Loads the Atlas .env (MASSIVE/BENZINGA/EODHD keys) the same way the engine
     does, so it works under launchd's bare environment.
  2. Skips weekends (US market closed) — no point scanning Sat/Sun.
  3. Runs the FULL live daily loop via atlas_manage (exits first, then sized,
     admitted, pullback-triggered entries) against the news-driven universe.
  4. Writes a clean, timestamped log to ~/scripts/atlas_daily.log and never
     raises out of launchd (so a transient API hiccup can't disable the job).

It deliberately reuses atlas_manage.run() rather than re-implementing logic, so
there is exactly ONE source of truth for the trading rules.

Manual use is identical to the scheduled use:
    python3 ~/scripts/atlas_daily.py            # live daily run (default)
    python3 ~/scripts/atlas_daily.py --dry-run  # show plan, write nothing
"""

import os
import sys
import argparse
import datetime
import traceback

SCRIPTS_DIR = "/Users/yasser/scripts"
sys.path.insert(0, SCRIPTS_DIR)

# --- Load Atlas .env (launchd has no shell env) ---------------------------- #
_ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

LOG_PATH = os.path.join(SCRIPTS_DIR, "atlas_daily.log")


def _log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_weekend():
    # Monday=0 ... Sunday=6 ; skip Saturday(5)/Sunday(6).
    return datetime.date.today().weekday() >= 5


def main():
    p = argparse.ArgumentParser(description="Atlas v2 automated daily driver")
    p.add_argument("--dry-run", action="store_true",
                   help="Show the plan but write nothing (default is LIVE).")
    p.add_argument("--force", action="store_true",
                   help="Run even on weekends.")
    p.add_argument("--file", help="Optional watchlist file override.")
    args = p.parse_args()

    _log("=" * 60)
    _log(f"Atlas daily driver starting (mode={'DRY-RUN' if args.dry_run else 'LIVE'})")

    if _is_weekend() and not args.force:
        _log("Weekend — US market closed. Skipping. (use --force to override)")
        _log("Atlas daily driver done.")
        return

    try:
        import atlas_account as acct
        acct.init_account()  # idempotent; ensures account table exists

        import atlas_manage as manage

        # Build the same args object atlas_manage.run() expects.
        ns = argparse.Namespace(
            tickers=[],
            file=args.file,
            live=not args.dry_run,
            exits_only=False,
            json=False,
        )
        manage.run(ns)
        _log("Daily loop completed successfully.")
    except Exception as e:  # never let launchd see a crash
        _log(f"ERROR in daily loop: {e}")
        _log(traceback.format_exc())
    finally:
        _log("Atlas daily driver done.")


if __name__ == "__main__":
    main()
