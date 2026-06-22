# Market Scout scheduled job timeout investigation

Read-only investigation. No changes were made.

## Target job

Name: Market Scout — market hours

Script path:
`/Users/yasser/.hermes/profiles/atlas/scripts/market_scout_market_hours.sh`

Reported issue:
- Scheduled job keeps timing out after 120s.

## 1. Full script content

File: `/Users/yasser/.hermes/profiles/atlas/scripts/market_scout_market_hours.sh`

```text
1|#!/usr/bin/env bash
2|set -euo pipefail
3|python3 - <<'PY'
4|from datetime import datetime, time, date
5|from zoneinfo import ZoneInfo
6|import subprocess
7|import sys
8|
9|NYSE_HOLIDAYS_2026 = {
10|    date(2026, 1, 1),   # New Year's Day
11|    date(2026, 1, 19),  # MLK Day
12|    date(2026, 2, 16),  # Presidents Day
13|    date(2026, 4, 3),   # Good Friday
14|    date(2026, 5, 25),  # Memorial Day
15|    date(2026, 6, 19),  # Juneteenth
16|    date(2026, 7, 3),   # Independence Day (observed)
17|    date(2026, 9, 7),   # Labor Day
18|    date(2026, 11, 26), # Thanksgiving
19|    date(2026, 11, 27), # Black Friday (early close — treated as closed)
20|    date(2026, 12, 25), # Christmas
21|}
22|
23|now = datetime.now(ZoneInfo('America/New_York'))
24|today = now.date()
25|market_open = time(9, 30)
26|market_close = time(16, 0)
27|
28|if today in NYSE_HOLIDAYS_2026:
29|    sys.exit(0)
30|
31|if now.weekday() >= 5:
32|    sys.exit(0)
33|
34|if not (market_open <= now.time().replace(second=0, microsecond=0) <= market_close):
35|    sys.exit(0)
36|
37|result = subprocess.run(
38|    ['python3', '/Users/yasser/scripts/market_scout.py'],
39|    text=True,
40|    stdout=subprocess.PIPE,
41|    stderr=subprocess.STDOUT,
42|)
43|if result.stdout:
44|    print(result.stdout, end='')
45|sys.exit(result.returncode)
46|PY
```

## 2. Atlas scheduler entries

### launchctl list | grep -i atlas

```text
-	0	com.atlas.vaultsync
-	0	com.atlas.intraday
22067	1	ai.hermes.gateway-atlasops
5784	-15	ai.hermes.gateway-atlas
-	0	com.atlas.daily
```

### /Users/yasser/Library/LaunchAgents/ Atlas entries

```text
-rw-r--r--   1 yasser  staff  2010 Jun 19 18:03 ai.hermes.gateway-atlas.plist
-rw-r--r--   1 yasser  staff  2044 Jun 22 15:11 ai.hermes.gateway-atlasops.plist
-rw-r--r--   1 yasser  staff  1547 Jun 22 02:50 com.atlas.daily.plist
-rw-------   1 yasser  staff  1026 Jun 22 16:20 com.atlas.intraday.plist
-rw-r--r--   1 yasser  staff   832 Jun 20 18:47 com.atlas.vaultsync.plist
```

### crontab -l

```text
No user crontab output.
```

### Hermes scheduler entries from /Users/yasser/.hermes/profiles/atlas/cron/jobs.json

```text
e387894093fe | Market Scout — market hours | script=market_scout_market_hours.sh | schedule=*/5 * * * 1-5 | enabled=True | state=scheduled | last_status=error
8fef4a1e57c4 | Morning Briefing | script=morning_briefing.sh | schedule=0 17 * * 1-5 | enabled=True | state=scheduled | last_status=ok
bfcc04221d23 | EOD Handoff Writer | script=eod_writer.sh | schedule=5 0 * * 2-6 | enabled=True | state=scheduled | last_status=ok
c9b363a88dd4 | Pre-Market Report | script=pre_market_report.sh | schedule=30 13 * * 1-5 | enabled=True | state=scheduled | last_status=ok
d7f4514dfbd5 | Post-Market Report | script=post_market_report.sh | schedule=15 20 * * 1-5 | enabled=True | state=scheduled | last_status=ok
5486d8b1d4b0 | Daily Atlas V2 Backup | script=atlas_backup.sh | schedule=30 0 * * * | enabled=True | state=scheduled | last_status=ok
```

## 3. Other scripts in profile scripts directory

Directory: `/Users/yasser/.hermes/profiles/atlas/scripts/`

```text
atlas_backup.sh
eod_writer.sh
market_scout_market_hours.sh
morning_briefing.sh
post_market_report.sh
pre_market_report.sh
```

Full listing observed:

```text
total 48
drwxr-xr-x   8 yasser  staff   256 Jun 20 16:05 .
drwx------  32 yasser  staff  1024 Jun 22 17:34 ..
-rwxr-xr-x   1 yasser  staff   119 Jun 20 16:05 atlas_backup.sh
-rwxr-xr-x   1 yasser  staff   117 Jun 19 19:37 eod_writer.sh
-rwx--x--x   1 yasser  staff  1206 Jun 19 19:55 market_scout_market_hours.sh
-rwxr-xr-x   1 yasser  staff   123 Jun 19 19:37 morning_briefing.sh
-rwxr-xr-x   1 yasser  staff   125 Jun 19 20:11 post_market_report.sh
-rwxr-xr-x   1 yasser  staff   124 Jun 19 20:11 pre_market_report.sh
```

## 4. Logs / outputs found

### Profile script logs

No `*.log` files found in:
`/Users/yasser/.hermes/profiles/atlas/scripts/`

### /Users/yasser/scripts logs

```text
-rw-r--r--  1 yasser  staff    2016 Jun 22 17:32 /Users/yasser/scripts/atlas_daily.log
-rw-r--r--  1 yasser  staff    2545 Jun 22 17:32 /Users/yasser/scripts/atlas_daily.out.log
-rw-r--r--  1 yasser  staff    3468 Jun 22 17:32 /Users/yasser/scripts/atlas_daily.err.log
-rw-r--r--  1 yasser  staff   25457 Jun 22 17:32 /Users/yasser/scripts/atlas_intraday.log
-rw-r--r--  1 yasser  staff  124327 Jun 22 17:31 /Users/yasser/scripts/vault_sync.log
-rw-r--r--  1 yasser  staff       0 Jun 22 16:30 /Users/yasser/scripts/atlas_intraday.err.log
-rw-r--r--  1 yasser  staff    5607 Jun 22 13:02 /Users/yasser/scripts/vault_sync.err.log
```

### Latest Hermes cron output for Market Scout

File:
`/Users/yasser/.hermes/profiles/atlas/cron/output/e387894093fe/2026-06-22_17-32-51.md`

Content:

```text
# Cron Job: Market Scout — market hours

Job ID: e387894093fe
Run Time: 2026-06-22 17:32:51
Mode: no_agent (script)
Status: script failed

Script timed out after 120s: /Users/yasser/.hermes/profiles/atlas/scripts/market_scout_market_hours.sh
```

### Newer jobs.json last_error for same job

From `/Users/yasser/.hermes/profiles/atlas/cron/jobs.json`:

```text
Script exited with code 1
stdout:
Traceback (most recent call last):
  File "/Users/yasser/scripts/market_scout.py", line 108, in <module>
    run_scout()
  File "/Users/yasser/scripts/market_scout.py", line 73, in run_scout
    score_val = int(score_str.split("/")[0])
                    ^^^^^^^^^^^^^^^
AttributeError: 'int' object has no attribute 'split'
```

### Relevant atlas_intraday.log entries

`com.atlas.intraday` is running every 10 minutes and completing:

```text
[2026-06-22 17:20:00] Atlas intraday loop starting...
Result: DO NOTHING. No new buys, no exits this cycle.

[2026-06-22 17:30:04] Atlas intraday loop starting...
Result: DO NOTHING. No new buys, no exits this cycle.
```

### Relevant atlas_daily.log entries

Daily driver has recent successful dry-runs:

```text
[2026-06-22 17:30:04] ============================================================
[2026-06-22 17:30:04] Atlas daily driver starting (mode=DRY-RUN)
[2026-06-22 17:32:29] Daily loop completed successfully.
[2026-06-22 17:32:29] Atlas daily driver done.
```

## 5. What this script actually runs

The Market Scout shell script:

1. Starts bash with strict mode.
2. Runs an embedded Python block.
3. Checks America/New_York time.
4. Exits silently outside:
   - weekdays,
   - non-holidays,
   - 9:30am–4:00pm ET.
5. During market hours, runs:

```text
python3 /Users/yasser/scripts/market_scout.py
```

6. Captures stdout and stderr combined.
7. Prints captured output if any.
8. Exits with `market_scout.py`'s return code.

## 6. How it is scheduled

This is not launchd and not crontab.

It is a Hermes profile cron/no-agent job in:

```text
/Users/yasser/.hermes/profiles/atlas/cron/jobs.json
```

Job details:

```text
Name: Market Scout — market hours
ID: e387894093fe
Script: market_scout_market_hours.sh
no_agent: true
Schedule: */5 * * * 1-5
Delivery: origin
Enabled: true
State: scheduled
Last status: error
```

The script itself gates market hours, but the Hermes cron schedule fires every 5 minutes on weekdays regardless of hour:

```text
*/5 * * * 1-5
```

## 7. Does it duplicate com.atlas.intraday?

Partially yes, and operationally it is now mostly redundant.

### com.atlas.intraday

- Scheduler type: launchd
- Plist: `/Users/yasser/Library/LaunchAgents/com.atlas.intraday.plist`
- Frequency: every 10 minutes at minutes 0/10/20/30/40/50
- Command:

```text
/usr/bin/python3 /Users/yasser/scripts/atlas_intraday.py
```

`atlas_intraday.py` runs:

```text
/usr/bin/python3 /Users/yasser/scripts/atlas_manage.py
```

Current mode:
- Full decision mode.
- Evaluates exits and full scan/decision flow.

### Market Scout Hermes cron

- Scheduler type: Hermes cron/no-agent job
- Frequency: every 5 minutes Mon-Fri, with internal market-hours gate
- Command during market hours:

```text
python3 /Users/yasser/scripts/market_scout.py
```

`market_scout.py`:
- Discovers tickers from Benzinga/news.
- Falls back to a fixed liquid universe if no news found.
- Filters junk/ETF/crypto/non-clean tickers.
- Limits to 20 tickers.
- Imports `analyze_ticker` from `atlas_engine`.
- Scores discovered tickers into 4 / 3 / 2 / 0-1 buckets.
- Prints a “Market Scout: Interval Update”.

### Difference

- Market Scout is a news/discovery interval report.
- Intraday is the actual portfolio/decision loop via `atlas_manage.py`, including exits and buy decision logic.

### Overlap

- Both do market-hours scanning.
- Both can call `analyze_ticker`.
- Both can generate Vault signal pushes indirectly.
- Market Scout adds extra load every 5 minutes and is currently failing/timing out.
- Since `com.atlas.intraday` already runs full decision mode every 10 minutes, Market Scout duplicates much of the scan workload but not the exits/portfolio-management behavior.

## 8. Likely failure causes

Current observed failures:

1. Timeout after 120s:
   - `market_scout.py` can exceed Hermes no-agent timeout while scanning up to 20 tickers.
   - Each ticker may trigger API calls, LLM catalyst checks, and Vault signal work.

2. Current Python error:

```text
AttributeError: 'int' object has no attribute 'split'
```

At:

```text
/Users/yasser/scripts/market_scout.py line 73
score_val = int(score_str.split("/")[0])
```

Meaning:
- `market_scout.py` expects `score_str` to be a string like `"3/4 Pillars"`.
- It received an `int` instead.

## Final finding

- The timed-out scheduled job is a Hermes no-agent cron job, not launchd.
- It runs every 5 minutes on weekdays and internally no-ops outside market hours.
- During market hours it runs `/Users/yasser/scripts/market_scout.py`.
- It overlaps with `com.atlas.intraday`, which already runs full `atlas_manage.py` decision mode every 10 minutes.
- Current job failures are explained by both timeout risk and a concrete `market_scout.py` type error.
- No edits or disabling were performed.
