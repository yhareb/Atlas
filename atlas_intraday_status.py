#!/usr/bin/env python3
"""Independent Atlas intraday heartbeat/status sender.

Runs separately from the heavy scan so launchd overlap or scan timeout cannot
silence Telegram status reports.
"""
import datetime
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")

from atlas_notify import send_telegram
import atlas_intraday

ET = ZoneInfo("America/New_York")
MARKET_OPEN_ET = datetime.time(9, 30)
MARKET_CLOSE_ET = datetime.time(16, 0)


def is_market_hours(now=None):
    now = now or datetime.datetime.now(ET)
    if now.weekday() >= 5:
        return False, f"weekend {now:%a %H:%M ET}"
    if not (MARKET_OPEN_ET <= now.time() <= MARKET_CLOSE_ET):
        return False, f"outside market hours {now:%H:%M ET}"
    return True, f"market hours {now:%H:%M ET}"


def main():
    now = datetime.datetime.now(ET)
    ok, detail = is_market_hours(now)
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] atlas_intraday_status: {detail}", flush=True)
    if not ok:
        return 0
    lock_note = ""
    try:
        if os.path.exists(atlas_intraday.LOCK_PATH):
            lock_note = "scan lock active"
    except Exception:
        pass
    reason = f"scheduled heartbeat {now:%H:%M ET}" + (f" — {lock_note}" if lock_note else "")
    msg = atlas_intraday._quick_status_report(reason)
    sent = send_telegram(msg, label="atlas_intraday_status", parse_mode="", print_fallback=True)
    print(f"[atlas_intraday_status] sent={sent}", flush=True)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
