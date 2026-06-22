# Atlas watchlist / handoff persistence inspection

Read-only inspection. No files were modified. Protected files `atlas_engine.py` and `atlas_portfolio.py` were not read.

## 1. atlas_db.py handoff/watchlist functions

### grep output

```text
53:def get_connection():
64:    signals / positions / handoff tables are left exactly as they were. The
107:    # Handoff table (latest state snapshot) -- unchanged.
109:        CREATE TABLE IF NOT EXISTS handoff (
396:def get_trades(status=None, limit=500):
422:def get_realized_pnl():
443:def get_open_positions():
471:# Handoff (unchanged API)
473:def update_handoff(date_str, data_dict):
478:        INSERT INTO handoff (date, data)
485:    # Real-time push of the handoff snapshot (fire-and-forget; never raises).
486:    _safe_push("push_handoff", date_str, data_dict)
489:def get_handoff(date_str):
492:    cursor.execute('SELECT data FROM handoff WHERE date = ?', (date_str,))
```

### handoff table schema

```text
107:     # Handoff table (latest state snapshot) -- unchanged.
108:     cursor.execute('''
109:         CREATE TABLE IF NOT EXISTS handoff (
110:             id INTEGER PRIMARY KEY AUTOINCREMENT,
111:             date TEXT UNIQUE,
112:             data TEXT
113:         )
114:     ''')
```

### update_handoff body

```text
473: def update_handoff(date_str, data_dict):
474:     conn = get_connection()
475:     cursor = conn.cursor()
476:     data_json = json.dumps(data_dict)
477:     cursor.execute('''
478:         INSERT INTO handoff (date, data)
479:         VALUES (?, ?)
480:         ON CONFLICT(date) DO UPDATE SET data=excluded.data
481:     ''', (date_str, data_json))
482:     conn.commit()
483:     conn.close()
484: 
485:     # Real-time push of the handoff snapshot (fire-and-forget; never raises).
486:     _safe_push("push_handoff", date_str, data_dict)
```

### get_handoff body

```text
489: def get_handoff(date_str):
490:     conn = get_connection()
491:     cursor = conn.cursor()
492:     cursor.execute('SELECT data FROM handoff WHERE date = ?', (date_str,))
493:     row = cursor.fetchone()
494:     conn.close()
495:     if row:
496:         return json.loads(row[0])
497:     return None
```

## 2. atlas_manage.py BUY/WATCH/AVOID persistence inspection

### grep output

```text
11:                  time-exit rules. We sell BEFORE buying so freed cash and
13:  3. REGIME       check the SPY > 50SMA gate once. If risk-OFF, no new buys.
15:                  --file watchlist, or the default universe) -> BUY / BUY Small.
24:  - All sells/buys go through the existing atlas_db FIFO ledger (open_trade /
31:  python3 ~/scripts/atlas_manage.py --file wl.txt   # dry-run, watchlist file
108:    _hdr("EXITS  (evaluated before any new buys)")
138:    buys = []
140:    reserved_cash = 0.0   # cash earmarked by approved buys this run
155:        decision = port.consider_buy(
160:        if act == "BUY":
161:            buys.append(decision)
164:            print(f"  BUY   {tkr:<6} {decision['shares']} sh @ {decision['entry']} "
174:    _finish(live, sells, buys)
177:def _finish(live, sells, buys):
180:    print(f"  Buys executed  : {len(buys)}" if live else f"  Buys planned   : {len(buys)}")
193:    p.add_argument("--file", help="Path to a watchlist file (one/many tickers per line)")
```

### scan/result area

```text
130:     if not regime_ok:
131:         print("  No new positions today (SPY below 50-day SMA).")
132:         _finish(live, sells, [])
133:         return
134: 
135:     # 4 + 5. SCORE & CONSIDER ----------------------------------------------
136:     candidates = load_candidates(args)
137:     _hdr(f"SCAN & ENTRIES  ({len(candidates)} candidates)")
138:     buys = []
139:     pending = []          # tickers approved this run (cap awareness)
140:     reserved_cash = 0.0   # cash earmarked by approved buys this run
141:     for tkr in candidates:
142:         try:
143:             res = analyze_ticker(tkr, regime=regime)
144:         except TypeError:
145:             res = analyze_ticker(tkr)  # back-compat if regime kwarg absent
146:         if "error" in res:
147:             print(f"  ----  {tkr:<6} {res['error']}")
148:             continue
149:         score = res.get("score", "0/4 Pillars")
150:         pillars = int(str(score).split("/")[0])
151:         if pillars < 3:
152:             print(f"  skip  {tkr:<6} {res.get('signal','')}  ({score})")
153:             continue
154: 
155:         decision = port.consider_buy(
156:             res, dry_run=not live, regime=regime,
157:             pending=pending, reserved_cash=reserved_cash,
158:         )
159:         act = decision["action"]
160:         if act == "BUY":
161:             buys.append(decision)
162:             pending.append(tkr.upper())
163:             reserved_cash += decision["cost"]
164:             print(f"  BUY   {tkr:<6} {decision['shares']} sh @ {decision['entry']} "
165:                   f"(stop {decision['stop']}, {decision['risk_pct']:.1f}% risk, "
166:                   f"${decision['cost']:,.0f}) — {decision['reason']}")
167:         elif act == "WAIT":
168:             print(f"  wait  {tkr:<6} ({score}) {decision['reason']}")
169:         elif act == "BLOCK":
170:             print(f"  block {tkr:<6} ({score}) {decision['reason']}")
171:         else:
172:             print(f"  {act.lower():<5} {tkr:<6} ({score}) {decision['reason']}")
173: 
174:     _finish(live, sells, buys)
175: 
176: 
177: def _finish(live, sells, buys):
178:     _hdr("SUMMARY")
```

### Finding

- `atlas_manage.py` does not show a call to `update_handoff()`, `save_handoff()`, or any handoff/watchlist persistence in the inspected scan/result area.
- It prints BUY/WAIT/BLOCK/skip decisions and passes `sells`/`buys` into `_finish()`.
- The grep found `--file` watchlist input support, but no WATCH-list output persistence in `atlas_manage.py`.

## 3. Additional non-protected writer found

A read-only recursive search across non-protected scripts found `eod_writer.py` as the handoff writer.

Relevant excerpt from `/Users/yasser/scripts/eod_writer.py`:

```text
1: """
2: eod_writer.py
3: Runs at 4:05pm ET every trading day.
4: Reads today's signals from atlas.db, keeps only BUY and WATCH tickers,
5: and writes the handoff snapshot to the handoff table.
6: """
...
32:     handoff_data = {
33:         "date": today,
34:         "BUY": [],
35:         "WATCH": [],
36:         "last_scan": datetime.now().isoformat()
37:     }
38: 
39:     for ticker, signal in rows:
40:         if "BUY" in signal:
41:             handoff_data["BUY"].append(ticker)
42:         elif "WATCH" in signal:
43:             handoff_data["WATCH"].append(ticker)
44: 
45:     atlas_db.update_handoff(today, handoff_data)
```

## 4. Answer: is today's WATCH list persisted anywhere after the daily/open scan?

Yes, a stable persisted handoff mechanism exists, but with an important distinction.

### Persisted storage

- Database table: `handoff`
- Unique key: `date` (`YYYY-MM-DD`)
- Payload column: `data` as JSON text
- Writer API: `atlas_db.update_handoff(date_str, data_dict)`
- Reader API: `atlas_db.get_handoff(date_str)`

### JSON format used by `eod_writer.py`

```json
{
  "date": "YYYY-MM-DD",
  "BUY": [],
  "WATCH": [],
  "last_scan": "<ISO timestamp>"
}
```

### Operational distinction

- `atlas_manage.py` itself does not appear to persist the BUY/WATCH/AVOID scan result into `handoff`.
- `eod_writer.py` persists BUY and WATCH tickers into the `handoff` table by reading today's `signals` from `atlas.db`.
- Therefore, a separate process can read a stable WATCH list from:

```python
atlas_db.get_handoff(today)["WATCH"]
```

but only if `eod_writer.py` or another writer has already populated today's handoff row.

Based on the inspected `atlas_manage.py` path alone, the daily/open scan does not directly write today's WATCH list to `handoff`.
