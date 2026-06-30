# Atlas actions_fix_hwm production deploy incident

Generated for Prof. by AtlasOps on 2026-06-28.

## Summary

The production `--force` verification run was live, not dry-run. It created 7 new `PENDING_FILL` trade rows in `/Users/yasser/scripts/atlas.db`.

I incorrectly reported the production DB counts without explicitly recognizing that `trades` increased from 10 to 17. The increase is real.

## Commands requested by Prof.

Prof requested:

```bash
sqlite3 /Users/yasser/scripts/atlas.db "SELECT id, ticker, status, timestamp FROM trades ORDER BY id DESC LIMIT 10;"
```

Actual output:

```text
Error: in prepare, no such column: timestamp
  SELECT id, ticker, status, timestamp FROM trades ORDER BY id DESC LIMIT 10;
               error here ---^
```

Reason: `trades` has no `timestamp` column. It uses `entry_at` and `exit_at`.

## Schema + corrected query output

Command run:

```bash
sqlite3 /Users/yasser/scripts/atlas.db "PRAGMA table_info(trades); SELECT id, ticker, status, entry_at, exit_at, quantity, entry_price, notes FROM trades ORDER BY id DESC LIMIT 10;"
```

Output:

```text
0|id|INTEGER|0||1
1|ticker|TEXT|1|'OPEN'|0
2|status|TEXT|1|'OPEN'|0
3|quantity|INTEGER|1||0
4|entry_price|REAL|1||0
5|entry_at|DATETIME|0|CURRENT_TIMESTAMP|0
6|exit_price|REAL|0||0
7|exit_at|DATETIME|0||0
8|entry_fees|REAL|0|0|0
9|exit_fees|REAL|0|0|0
10|realized_pnl|REAL|0||0
11|realized_pnl_pct|REAL|0||0
12|parent_id|INTEGER|0||0
13|notes|TEXT|0||0
14|updated_at|DATETIME|0|CURRENT_TIMESTAMP|0
15|stop_loss|REAL|0||0
16|risk_pct|REAL|0||0
17|target_price|REAL|0||0
18|broker_ref|TEXT|0|NULL|0
27|CSCO|PENDING_FILL|2026-06-28 09:03:43||25|113.6|Atlas v2 entry: Pulled back to 10-EMA 118.97 (close 113.60); score 3/4 Pillars; signal 🟡 BUY (Small); stop 107.84; target 125.12; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
26|UNF|PENDING_FILL|2026-06-28 09:03:39||15|266.07|Atlas v2 entry: Pulled back to 10-EMA 263.98 (close 266.07); score 3/4 Pillars; signal 🟡 BUY (Small); stop 256.51; target 285.19; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
25|MSM|PENDING_FILL|2026-06-28 09:03:36||31|118.18|Atlas v2 entry: Pulled back to 10-EMA 117.02 (close 118.18); score 3/4 Pillars; signal 🟡 BUY (Small); stop 113.61; target 127.32; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
24|MRNA|PENDING_FILL|2026-06-28 09:03:33||17|67.19|Atlas v2 entry: Gap-Up Breakout Entry: gap +12.5%, volume 2.1x 30D, sentiment +0.75; opening-range stop below $59.23; score 3/4 Pillars; signal 🟡 BUY (Small); stop 58.93; target 83.71; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
23|JPM|PENDING_FILL|2026-06-28 09:02:39||13|329.55|Atlas v2 entry: Pulled back to armed 10-EMA limit 329.55 (last 329.17); score 3/4 Pillars; signal 🟡 BUY (Small); stop 318.62; target 351.41; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
22|EVC|PENDING_FILL|2026-06-28 09:02:26||136|12.2|Atlas v2 entry: Gap-Up Breakout Entry: gap +7.1%, volume 1.6x 30D, sentiment +0.95; opening-range stop below $11.19; score 3/4 Pillars; signal 🟡 BUY (Small); stop 11.13; target 14.34; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
21|PGEN|PENDING_FILL|2026-06-28 09:02:11||383|5.83|Atlas v2 entry: Gap-Up Breakout Entry: gap +5.6%, volume 2.2x 30D, sentiment +0.98; opening-range stop below $5.48; score 3/4 Pillars; signal 🟡 BUY (Small); stop 5.45; target 6.59; 0.5% risk on equity $29,126 (cautious weak-market/macro mode)
18|SYNA|OPEN|2026-06-26 14:09:51||7.90888959|126.44|Atlas v2 entry: Pulled back to 10-EMA 132.98 (close 127.77); score 3/4 Pillars; signal 🟡 BUY (Small); stop 113.35; target 156.61; 0.5% risk on equity $30,333 (cautious weak-market/macro mode) | Broker fill confirmed ref P680372452
17|MS|CLOSED|2026-06-25 14:16:37|2026-06-26 13:48:27|4.42522128|225.98|Atlas v2 entry: Pulled back to 10-EMA 220.91 (close 224.59); score 3/4 Pillars; signal 🟡 BUY (Small); stop 215.5; target 242.77; 0.5% risk on equity $32,214 (cautious weak-market/macro mode) | Broker fill confirmed ref P1104545791
16|INTC|OPEN|2026-06-25 14:08:30||7.70534157|129.78|Atlas v2 entry: Pulled back to armed 10-EMA limit 129.43 (last 129.14); score 3/4 Pillars; signal 🟡 BUY (Small); stop 113.02; target 162.25; 0.5% risk on equity $32,213 (cautious weak-market/macro mode) | Broker fill confirmed ref P780203310
```

## Discrepancy explained

The production deploy command set from the sign-off packet included:

```bash
python3 "$PROD/atlas_intraday.py" --force
```

This is **not dry-run**. In the deployed `atlas_intraday.py`, the logic is:

```python
cli_dry_run = "--dry-run" in sys.argv
args = SimpleNamespace(tickers=[], file=None, live=not dry_run, exits_only=False, json=False)
```

Therefore, when the command was run as:

```bash
python3 /Users/yasser/scripts/atlas_intraday.py --force
```

then:

```text
dry_run=False
live=True
```

That allowed `atlas_manage.run()` / portfolio entry logic to write production `PENDING_FILL` rows.

## New production rows written

The run created these 7 rows:

```text
21|PGEN|PENDING_FILL|2026-06-28 09:02:11
22|EVC|PENDING_FILL|2026-06-28 09:02:26
23|JPM|PENDING_FILL|2026-06-28 09:02:39
24|MRNA|PENDING_FILL|2026-06-28 09:03:33
25|MSM|PENDING_FILL|2026-06-28 09:03:36
26|UNF|PENDING_FILL|2026-06-28 09:03:39
27|CSCO|PENDING_FILL|2026-06-28 09:03:43
```

## Final correction

My earlier statement that no new trades were written was wrong.

Correct state:

```text
Production trades count before live --force: 10
Production trades count after live --force: 17
Delta: +7 PENDING_FILL rows
```

These are **real production DB rows**, not staging artifacts.

## Safety note

No broker execution is proven by these rows. They are Atlas production DB `PENDING_FILL` records created by the live forced pipeline run. They should be treated as pending/manual-action records unless separately confirmed against broker state.
