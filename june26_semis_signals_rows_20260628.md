# June 26 Semi Peer Signal Rows

Prof.

This file contains the evidence from the June 26 `signals` query that should have been attached instead of pasted into Telegram.

## Requested command

```bash
sqlite3 /Users/yasser/scripts/atlas.db "SELECT ticker, scan_time, pillar_score, entry_type, decision FROM signals WHERE ticker IN ('KLAC','TER','UCTT','MXL','MKSI','ALGM') AND date(scan_time)='2026-06-26' ORDER BY ticker, scan_time;"
```

## Result

```text
Error: in prepare, no such column: scan_time
  SELECT ticker, scan_time, pillar_score, entry_type, decision FROM signals WHER
                 ^--- error here
```

## Actual `signals` schema

```text
0|id|INTEGER|0||1
1|timestamp|DATETIME|0|CURRENT_TIMESTAMP|0
2|ticker|TEXT|0||0
3|signal|TEXT|0||0
4|score|INTEGER|0||0
5|rvol|REAL|0||0
6|entry_price|REAL|0||0
7|stop_loss|REAL|0||0
8|max_loss_per_share|REAL|0||0
9|atr|REAL|0||0
10|trend_stack|TEXT|0||0
11|relative_strength|TEXT|0||0
12|volume|TEXT|0||0
13|catalyst|TEXT|0||0
14|warnings|TEXT|0||0
```

## Equivalent query using actual columns

```bash
sqlite3 /Users/yasser/scripts/atlas.db "SELECT ticker, timestamp, score, signal, warnings FROM signals WHERE ticker IN ('KLAC','TER','UCTT','MXL','MKSI','ALGM') AND date(timestamp)='2026-06-26' ORDER BY ticker, timestamp;"
```

## Output

```text
ALGM|2026-06-26 12:21:07|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk
ALGM|2026-06-26 12:23:41|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk
ALGM|2026-06-26 18:13:48|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 734.25 < 50SMA 734.46) — cautious half-size buys
ALGM|2026-06-26 18:23:38|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 733.40 < 50SMA 734.44) — cautious half-size buys
ALGM|2026-06-26 18:33:45|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.83 < 50SMA 734.43) — cautious half-size buys
ALGM|2026-06-26 18:43:39|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.91 < 50SMA 734.43) — cautious half-size buys
ALGM|2026-06-26 18:53:41|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.02 < 50SMA 734.41) — cautious half-size buys
ALGM|2026-06-26 19:03:47|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 731.65 < 50SMA 734.40) — cautious half-size buys
ALGM|2026-06-26 19:13:49|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.31 < 50SMA 734.42) — cautious half-size buys
ALGM|2026-06-26 19:23:37|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.76 < 50SMA 734.43) — cautious half-size buys
ALGM|2026-06-26 19:35:18|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.20 < 50SMA 734.42) — cautious half-size buys
ALGM|2026-06-26 19:44:14|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.32 < 50SMA 734.42) — cautious half-size buys
ALGM|2026-06-26 19:54:16|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 733.25 < 50SMA 734.44) — cautious half-size buys
KLAC|2026-06-26 12:19:44|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk
KLAC|2026-06-26 19:35:29|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.20 < 50SMA 734.42) — cautious half-size buys
KLAC|2026-06-26 19:44:26|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.32 < 50SMA 734.42) — cautious half-size buys
KLAC|2026-06-26 19:54:30|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 733.25 < 50SMA 734.44) — cautious half-size buys
MKSI|2026-06-26 12:20:49|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
MKSI|2026-06-26 12:23:32|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
MKSI|2026-06-26 18:13:43|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 734.25 < 50SMA 734.46) — cautious half-size buys
MKSI|2026-06-26 18:23:38|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 733.40 < 50SMA 734.44) — cautious half-size buys
MKSI|2026-06-26 18:33:44|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.83 < 50SMA 734.43) — cautious half-size buys
MKSI|2026-06-26 18:43:37|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.91 < 50SMA 734.43) — cautious half-size buys
MKSI|2026-06-26 18:53:37|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.02 < 50SMA 734.41) — cautious half-size buys
MKSI|2026-06-26 19:03:46|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 731.65 < 50SMA 734.40) — cautious half-size buys
MKSI|2026-06-26 19:13:48|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.31 < 50SMA 734.42) — cautious half-size buys
MKSI|2026-06-26 19:23:37|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.76 < 50SMA 734.43) — cautious half-size buys
MKSI|2026-06-26 19:35:17|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.20 < 50SMA 734.42) — cautious half-size buys
MKSI|2026-06-26 19:44:12|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 732.32 < 50SMA 734.42) — cautious half-size buys
MKSI|2026-06-26 19:54:16|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk, ⚠️ Market weak (⚠️ WEAK — cautious (half size); SPY 733.25 < 50SMA 734.44) — cautious half-size buys
MXL|2026-06-26 12:20:27|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 17 trading days (2026-07-22) — elevated risk
TER|2026-06-26 12:20:05|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 21 trading days (2026-07-28) — elevated risk
TER|2026-06-26 12:23:21|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 21 trading days (2026-07-28) — elevated risk
UCTT|2026-06-26 12:20:16|2/4 Pillars|⚪ WATCH|⚠️ Earnings in 20 trading days (2026-07-27) — elevated risk
```
