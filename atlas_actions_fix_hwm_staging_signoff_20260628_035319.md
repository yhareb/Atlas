# Atlas actions_fix_hwm staging sign-off packet

Generated: 20260628_035319

## Status

- Production deploy: NOT DONE. Awaiting Prof. approval.
- Current unsafe 15-minute-only staged version: superseded, not deployed.
- New staged fix: signal ID high-water mark.
- Staged files changed:
  - `/tmp/atlas_actions_fix_staging_scripts/atlas_intraday.py`
  - `/tmp/atlas_actions_fix_staging_scripts/atlas_db.py`
- Production files changed: none.
- Staging workspace: `/tmp/atlas_actions_fix_staging_scripts`
- Staging DB: `/tmp/atlas_staging.db`

## Patch summary

```text
1. Added atlas_db.get_max_signal_id(): SELECT MAX(id) FROM signals.
2. atlas_intraday captures high-water ID immediately before atlas_manage.run().
3. _build_report passes _before_scan_signal_id to _actions_lines().
4. _actions_lines passes before_scan_signal_id to _current_cycle_buy_signals().
5. _current_cycle_buy_signals() uses id > ? for normal operation.
6. If before_id is None/0, it falls back to the 15-minute timestamp window.
7. Forbidden broker-confirmation label remains absent from staged workspace.
```

## Active-file diffs

### atlas_intraday.py

```diff
--- /Users/yasser/scripts/atlas_intraday.py
+++ /tmp/atlas_actions_fix_staging_scripts/atlas_intraday.py
@@ -1,4 +1,4 @@
-import os, sys, datetime, contextlib, io, re, time, errno, signal, threading, subprocess
+import os, sys, datetime, contextlib, io, re, time, errno, signal, threading, subprocess, sqlite3, json
 from types import SimpleNamespace
 from zoneinfo import ZoneInfo
 
@@ -15,9 +15,20 @@
 except Exception:
     pass
 
-SCRIPTS_DIR = "/Users/yasser/scripts"
+SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
 sys.path.insert(0, SCRIPTS_DIR)
 import atlas_db
+if not hasattr(atlas_db, "get_max_signal_id"):
+    def _get_max_signal_id_fallback():
+        conn = atlas_db.get_connection()
+        cursor = conn.cursor()
+        cursor.execute("SELECT MAX(id) FROM signals")
+        row = cursor.fetchone()
+        conn.close()
+        return int(row[0] or 0)
+    atlas_db.get_max_signal_id = _get_max_signal_id_fallback
+if os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB"):
+    atlas_db.DB_PATH = os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB")
 from atlas_symbol_meta import ticker_label
 
 _ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
@@ -441,31 +452,114 @@
     ]
 
 
-def _actions_lines(buys, sells):
-    buys = _unique(buys)
+def _current_cycle_buy_signals(before_id=None, minutes=15):
+    """Return BUY/BUY Small signal rows written after the scan high-water mark."""
+    db_path = getattr(atlas_db, "DB_PATH", "/Users/yasser/scripts/atlas.db")
+    try:
+        con = sqlite3.connect(db_path)
+        con.row_factory = sqlite3.Row
+        if before_id:
+            where_clause = """
+            WHERE id > ?
+              AND signal LIKE '%BUY%'
+              AND (
+                COALESCE(score, '') LIKE '4/%'
+                OR COALESCE(score, '') LIKE '3/%'
+              )
+            """
+            params = (int(before_id),)
+        else:
+            where_clause = """
+            WHERE timestamp >= datetime('now', ?)
+              AND signal LIKE '%BUY%'
+              AND (
+                COALESCE(score, '') LIKE '4/%'
+                OR COALESCE(score, '') LIKE '3/%'
+              )
+            """
+            params = (f"-{int(minutes)} minutes",)
+        rows = con.execute(
+            f"""
+            SELECT ticker, score, signal, entry_price, stop_loss, warnings
+            FROM signals
+            {where_clause}
+            ORDER BY
+              CASE
+                WHEN CAST(substr(COALESCE(score, '0/4'), 1, instr(COALESCE(score, '0/4'), '/') - 1) AS INTEGER) >= 4 THEN 0
+                WHEN CAST(substr(COALESCE(score, '0/4'), 1, instr(COALESCE(score, '0/4'), '/') - 1) AS INTEGER) = 3 THEN 1
+                ELSE 2
+              END,
+              ticker
+            """,
+            params,
+        ).fetchall()
+        con.close()
+        return [dict(r) for r in rows]
+    except Exception as e:
+        print(f"[intraday] current-cycle BUY signal query failed: {e}", flush=True)
+        return []
+
+
+def _pending_target_for_signal(ticker, entry):
+    """Pull target from pending state when available; otherwise use 25% fallback."""
+    ticker = str(ticker or "").upper()
+    entry = _num(entry)
+    fallback = round(entry * 1.25, 2) if entry else None
+    try:
+        row = atlas_db.get_pending_pullback(ticker)
+    except Exception:
+        row = None
+    if row:
+        for key in ("target", "target_price"):
+            if row.get(key) not in (None, ""):
+                return _num(row.get(key), fallback or 0.0)
+        raw = row.get("signal_json")
+        if raw:
+            try:
+                data = json.loads(raw) if isinstance(raw, str) else raw
+                for key in ("target", "target_price"):
+                    if isinstance(data, dict) and data.get(key) not in (None, ""):
+                        return _num(data.get(key), fallback or 0.0)
+                risk_card = data.get("risk_card") if isinstance(data, dict) else None
+                if isinstance(risk_card, dict):
+                    for key in ("target", "target_price"):
+                        if risk_card.get(key) not in (None, ""):
+                            return _num(risk_card.get(key), fallback or 0.0)
+            except Exception:
+                pass
+    return fallback
+
+
+def _risk_label_for_signal(row, summary):
+    pillars = _pillar_num(row.get("score"))
+    detail = str((summary or {}).get("entry_regime_detail") or (summary or {}).get("regime_detail") or "")
+    macro = (summary or {}).get("macro_context") or {}
+    cautious = (
+        "WEAK" in detail.upper()
+        or "UNKNOWN" in detail.upper()
+        or "UNAVAILABLE" in detail.upper()
+        or bool(macro.get("cautious") if isinstance(macro, dict) else False)
+    )
+    return "0.5% risk" if pillars == 3 or cautious else "1% risk"
+
+
+def _actions_lines(buys, sells, summary=None, before_scan_signal_id=None):
+    signal_buys = _unique(_current_cycle_buy_signals(before_scan_signal_id), key="ticker")
     sells = _unique(sells)
     lines = ["", "━━━ ACTIONS ━━━"]
-    if buys:
-        lines.append(f"🛒 BUY ({len(buys)}) — engine wants in")
-        for b in buys:
-            ticker = str(b.get("ticker") or b.get("symbol") or "?").upper()
-            entry = _num(b.get("entry"))
-            stop = _num(b.get("stop"))
-            target = _num(b.get("target"))
-            shares = int(_num(b.get("shares")))
-            cost = _num(b.get("cost"), entry * shares)
-            risk = b.get("risk_pct")
-            win_pct = ((target - entry) / entry * 100) if entry else 0
-            loss_pct = ((entry - stop) / entry * 100) if entry else 0
-            risk_txt = "N/A" if risk in (None, "") else f"{_num(risk):.1f}%"
-            live_price = b.get("live_price") or b.get("current_price") or b.get("price") or entry
+    if signal_buys:
+        lines.append(f"🛒 BUY ({len(signal_buys)})")
+        for b in signal_buys:
+            ticker = str(b.get("ticker") or "?").upper()
+            entry = _num(b.get("entry_price"))
+            stop = _num(b.get("stop_loss"))
+            target = _pending_target_for_signal(ticker, entry)
+            score = str(b.get("score") or "")
             label = _ticker_label(ticker, b)
-            lines += [
-                "",
-                f"🟢 {label} Buy at {_price(entry)} - currently trading at {_price(live_price)} · stop {_price(stop)} · target {_price(target)} · {risk_txt} risk",
-                f"   ~{_money(cost)} · win +{win_pct:.0f}% / loss −{loss_pct:.0f}%",
-                f"   {_register_buy_line(ticker, shares, entry)}",
-            ]
+            risk_txt = _risk_label_for_signal(b, summary or {})
+            lines.append(
+                f"   • {label} — {_whole(entry)} · stop {_whole(stop)} · target {_whole(target)} · {score} · {risk_txt}"
+            )
     else:
         lines.append("🛒 BUY: none this cycle")
     if sells:
@@ -715,8 +809,9 @@
     waiting_count = len(_unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()]))
     pending_count = len(atlas_db.get_pending_fill_trades())
 
+    before_scan_signal_id = summary.get("_before_scan_signal_id")
     lines = _header_lines(summary, hold_count)
-    lines += _actions_lines(buys, sells)
+    lines += _actions_lines(buys, sells, summary, before_scan_signal_id)
     lines += _pending_entry_lines()
     lines += _holding_lines(summary)
     lines += _gap_breakout_lines(summary)
@@ -776,6 +871,8 @@
 
 
 def run_intraday():
+    cli_force = "--force" in sys.argv
+    cli_dry_run = "--dry-run" in sys.argv
     now = datetime.datetime.now()
     print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Atlas intraday loop starting...")
 
@@ -783,28 +880,37 @@
     if lock_fd is None:
         print(f"[intraday] overlap guard: another atlas_intraday run is still active ({LOCK_PATH}); sending status and exiting cleanly.")
         try:
-            _send_telegram_async(_quick_status_report("previous scan still running"), label="atlas_overlap_status")
-            print("[intraday] overlap status telegram queued")
+            if not cli_dry_run:
+                _send_telegram_async(_quick_status_report("previous scan still running"), label="atlas_overlap_status")
+                print("[intraday] overlap status telegram queued")
+            else:
+                print("[intraday] dry-run: overlap status telegram suppressed")
         except Exception as e:
             print(f"[intraday] overlap status telegram failed (non-fatal): {e}")
         return {"skipped": True, "reason": "previous intraday run still active"}
     try:
         signal.alarm(MAX_INTRADAY_RUNTIME_SECONDS)
-        return _run_intraday_locked(now)
+        return _run_intraday_locked(now, force=cli_force, dry_run=cli_dry_run)
     finally:
         signal.alarm(0)
         _release_run_lock(lock_fd)
 
 
-def _run_intraday_locked(now):
+def _run_intraday_locked(now, force=False, dry_run=False):
     ok, gate_detail = is_market_hours()
-    if not ok:
+    if not ok and not force:
         print(f"[intraday] market-hours gate: {gate_detail}; exiting cleanly with no scan/trade/Telegram.")
         return {"skipped": True, "reason": gate_detail}
-    print(f"[intraday] market-hours gate: {gate_detail}")
-    try:
-        _send_telegram_async(_quick_status_report("scan starting"), label="atlas_start_status")
-        print("[intraday] start status telegram subprocess queued")
+    if not ok and force:
+        print(f"[intraday] market-hours gate bypassed by --force: {gate_detail}")
+    else:
+        print(f"[intraday] market-hours gate: {gate_detail}")
+    try:
+        if not dry_run:
+            _send_telegram_async(_quick_status_report("scan starting"), label="atlas_start_status")
+            print("[intraday] start status telegram subprocess queued")
+        else:
+            print("[intraday] dry-run: start status telegram suppressed")
     except Exception as e:
         print(f"[intraday] start status telegram failed (non-fatal): {e}")
 
@@ -818,6 +924,21 @@
             print(f"[intraday] stream unavailable; polling continues: {e}")
 
     import atlas_manage
+    staging_db = os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB")
+    if staging_db:
+        try:
+            atlas_db.DB_PATH = staging_db
+            if hasattr(atlas_manage, "atlas_db"):
+                atlas_manage.atlas_db.DB_PATH = staging_db
+            if hasattr(atlas_manage, "acct"):
+                atlas_manage.acct.DB_PATH = staging_db
+            if hasattr(atlas_manage, "port"):
+                if hasattr(atlas_manage.port, "atlas_db"):
+                    atlas_manage.port.atlas_db.DB_PATH = staging_db
+                if hasattr(atlas_manage.port, "acct"):
+                    atlas_manage.port.acct.DB_PATH = staging_db
+        except Exception as e:
+            print(f"[intraday] staging DB override warning: {e}")
     # Report-first safety: the full intraday Telegram report must be generated from
     # the base scan before sector-sweep peer enrichment can consume the launchd
     # window. This does not modify sector-sweep logic; it disables the sweep trigger
@@ -832,7 +953,7 @@
                 print("[intraday] report-first mode: sector sweep peer enrichment deferred until after Telegram report")
         except Exception as e:
             print(f"[intraday] report-first sector-sweep deferral unavailable (non-fatal): {e}")
-    args = SimpleNamespace(tickers=[], file=None, live=True, exits_only=False, json=False)
+    args = SimpleNamespace(tickers=[], file=None, live=not dry_run, exits_only=False, json=False)
     stdout_buf = io.StringIO()
     stderr_buf = io.StringIO()
     scan_done = {"done": False}
@@ -841,11 +962,21 @@
         if scan_done.get("done"):
             return
         try:
-            interim = _quick_status_report("full scan still running >180s")
-            _send_telegram_async(interim, label="atlas_interim_status")
-            print("[intraday] interim telegram report queued")
+            if not dry_run:
+                interim = _quick_status_report("full scan still running >180s")
+                _send_telegram_async(interim, label="atlas_interim_status")
+                print("[intraday] interim telegram report queued")
+            else:
+                print("[intraday] dry-run: interim telegram suppressed")
         except Exception as e:
             print(f"[intraday] interim telegram report failed (non-fatal): {e}")
+
+    try:
+        _before_scan_signal_id = atlas_db.get_max_signal_id()
+        print(f"[intraday] signal high-water before scan id={_before_scan_signal_id}")
+    except Exception as e:
+        _before_scan_signal_id = 0
+        print(f"[intraday] signal high-water capture failed; falling back to 15m window: {e}")
 
     interim_timer = threading.Timer(180.0, _send_interim_report_if_slow)
     interim_timer.daemon = True
@@ -870,6 +1001,7 @@
     if not isinstance(summary, dict):
         print("WARNING: Could not get structured intraday summary; not asserting an action.")
         summary = getattr(atlas_manage, "LAST_RUN_SUMMARY", {}) or {}
+    summary["_before_scan_signal_id"] = _before_scan_signal_id
     if stream_status is not None:
         summary["stream_status"] = stream_status
 
@@ -886,8 +1018,11 @@
     print("[intraday] telegram report body end")
 
     try:
-        ok = send_telegram(report_msg)
-        print(f"[intraday] telegram report success={ok}")
+        if not dry_run:
+            ok = send_telegram(report_msg)
+            print(f"[intraday] telegram report success={ok}")
+        else:
+            print("[intraday] dry-run: final telegram send suppressed")
     except Exception as e:
         print(f"[intraday] telegram report failed (non-fatal): {e}")
 

```

### atlas_db.py

```diff
--- /Users/yasser/scripts/atlas_db.py
+++ /tmp/atlas_actions_fix_staging_scripts/atlas_db.py
@@ -294,6 +294,15 @@
 # --------------------------------------------------------------------------- #
 # Signals (unchanged API)
 # --------------------------------------------------------------------------- #
+def get_max_signal_id():
+    conn = get_connection()
+    cursor = conn.cursor()
+    cursor.execute("SELECT MAX(id) FROM signals")
+    row = cursor.fetchone()
+    conn.close()
+    return int(row[0] or 0)
+
+
 def log_signal(ticker, signal, score, rvol, entry_price, stop_loss, max_loss_per_share, atr, trend_stack, relative_strength, volume, catalyst, warnings):
     conn = get_connection()
     cursor = conn.cursor()

```

## Gate 1 — compile

Command:

```bash
python3 -m py_compile "/tmp/atlas_actions_fix_staging_scripts/atlas_intraday.py" "/tmp/atlas_actions_fix_staging_scripts/atlas_db.py"
```

Result:

```text
exit code: 0
stdout bytes: 0
stderr bytes: 0
```

## Gate 1 — dry-run command

```bash
cp -p "/Users/yasser/scripts/atlas.db" "/tmp/atlas_staging.db"
ATLAS_DB="/tmp/atlas_staging.db" ATLAS_STAGING_DB="/tmp/atlas_staging.db" ATLAS_DISABLE_TELEGRAM=1 ATLAS_MOCK_TELEGRAM=1 ATLAS_SCRIPTS_DIR="/tmp/atlas_actions_fix_staging_scripts" PYTHONPATH="/tmp/atlas_actions_fix_staging_scripts" ATLAS_INTRADAY_MAX_RUNTIME_SECONDS=600 python3 "/tmp/atlas_actions_fix_staging_scripts/atlas_intraday.py" --force --dry-run   > /tmp/atlas_actions_fix_hwm_gate1_20260628_035319.out   2> /tmp/atlas_actions_fix_hwm_gate1_20260628_035319.err
```

High-water evidence:

```text
[intraday] signal high-water before scan id=6395
```

Gate 1 assertions:

```text
ACTIONS section found: True
BUY line: 🛒 BUY (34)
Forbidden broker label present in dry-run output: False
2/4 rows present in ACTIONS extract: False
```

ACTIONS extract:

```text
━━━ ACTIONS ━━━
🛒 BUY (34)
   • ELVN (Enliven Therapeutics) — $50 · stop $44 · target $63 · 4/4 Pillars · 0.5% risk
   • JNJ (Johnson & Johnson) — $255 · stop $246 · target $318 · 4/4 Pillars · 0.5% risk
   • MRK (Merck) — $129 · stop $124 · target $161 · 4/4 Pillars · 0.5% risk
   • MRNA (Moderna) — $67 · stop $60 · target $84 · 4/4 Pillars · 0.5% risk
   • PGEN (Precigen) — $6 · stop $5 · target $7 · 4/4 Pillars · 0.5% risk
   • RL (Ralph Lauren) — $411 · stop $391 · target $514 · 4/4 Pillars · 0.5% risk
   • SLS (SELLAS Life Sciences Group) — $12 · stop $11 · target $15 · 4/4 Pillars · 0.5% risk
   • AAL (American Airlines Group) — $18 · stop $17 · target $22 · 3/4 Pillars · 0.5% risk
   • ABBV (AbbVie) — $253 · stop $243 · target $317 · 3/4 Pillars · 0.5% risk
   • ABSI (Absci) — $11 · stop $9 · target $14 · 3/4 Pillars · 0.5% risk
   • ALGM (Allegro MicroSystems) — $58 · stop $51 · target $72 · 3/4 Pillars · 0.5% risk
   • AMAT (Applied Materials) — $627 · stop $558 · target $784 · 3/4 Pillars · 0.5% risk
   • APGE (Apogee Therapeutics) — $133 · stop $123 · target $166 · 3/4 Pillars · 0.5% risk
   • BAC (Bank of America) — $58 · stop $56 · target $72 · 3/4 Pillars · 0.5% risk
   • BLZE (Backblaze) — $15 · stop $13 · target $18 · 3/4 Pillars · 0.5% risk
   • CAT (Caterpillar) — $997 · stop $934 · target $1,247 · 3/4 Pillars · 0.5% risk
   • CGEM (Cullinan Therapeutics) — $18 · stop $16 · target $23 · 3/4 Pillars · 0.5% risk
   • CSCO (Cisco Systems) — $114 · stop $108 · target $142 · 3/4 Pillars · 0.5% risk
   • CWAN (Clearwater Analytics) — $25 · stop $24 · target $31 · 3/4 Pillars · 0.5% risk
   • EVC (Entravision Communication) — $12 · stop $11 · target $15 · 3/4 Pillars · 0.5% risk
   • EWTX (Edgewise Therapeutics) — $41 · stop $37 · target $52 · 3/4 Pillars · 0.5% risk
   • FCEL (FuelCell Energy Inc NEW) — $24 · stop $19 · target $30 · 3/4 Pillars · 0.5% risk
   • GLW (Corning) — $221 · stop $196 · target $276 · 3/4 Pillars · 0.5% risk
   • JPM (JPMorgan Chase) — $329 · stop $317 · target $411 · 3/4 Pillars · 0.5% risk
   • KLIC (Kulicke & Soffa Industries) — $125 · stop $112 · target $157 · 3/4 Pillars · 0.5% risk
   • KO (Coca-Cola) — $83 · stop $80 · target $103 · 3/4 Pillars · 0.5% risk
   • MEI (Methode Electronics) — $19 · stop $17 · target $24 · 3/4 Pillars · 0.5% risk
   • MKSI (Mks) — $389 · stop $349 · target $486 · 3/4 Pillars · 0.5% risk
   • MSM (MSC Industrial Direct) — $118 · stop $114 · target $148 · 3/4 Pillars · 0.5% risk
   • MU (Micron Technology) — $1,132 · stop $972 · target $1,415 · 3/4 Pillars · 0.5% risk
   • SPCX (SpaceX) — $153 · stop $116 · target $192 · 3/4 Pillars · 0.5% risk
   • SYNA (Synaptics) — $121 · stop $106 · target $151 · 3/4 Pillars · 0.5% risk
   • TGT (Target) — $140 · stop $134 · target $175 · 3/4 Pillars · 0.5% risk
   • UNF (Unifirst) — $266 · stop $257 · target $333 · 3/4 Pillars · 0.5% risk
💰 SELL: none — holding all
```

## Gate 2 — timing harness

Command:

```bash
cp -p "/Users/yasser/scripts/atlas.db" "/tmp/atlas_staging.db"
python3 "/Users/yasser/scripts/tests/test_scan_timing.py" --db "/tmp/atlas_staging.db" --max-seconds 480   > /tmp/atlas_actions_fix_hwm_gate2_20260628_035319.out   2> /tmp/atlas_actions_fix_hwm_gate2_20260628_035319.err
```

Pass flag:

```text
True
```

Result JSON:

```text
GATE2_RESULT_JSON={"candidate_count": 97, "elapsed_seconds": 360.683, "gate1_critical_tables": ["trades", "pending_pullbacks"], "isolated_db": "/var/folders/nz/48nykj7s0tl__8dfhq6dd0vm0000gn/T/atlas_scan_timing_8u24b9nq/atlas_timing.db", "max_seconds": 480.0, "result": "DO NOTHING", "scanned_count": 75, "source_counts_after": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "source_counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "source_counts_unchanged": true, "source_critical_counts_unchanged": true, "temp_counts_after": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "temp_counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "under_limit": true}
```

## Gate 3 — three staging cycles

Command:

```bash
cp -p "/Users/yasser/scripts/atlas.db" "/tmp/atlas_staging.db"
ATLAS_SCRIPTS_DIR="/tmp/atlas_actions_fix_staging_scripts" ATLAS_STAGING_DB="/tmp/atlas_staging.db" ATLAS_DB="/tmp/atlas_staging.db" "/Users/yasser/.hermes/profiles/atlas-staging/bin/run_atlas_manage_staging.py" --cycles 3 --max-seconds 480   > /tmp/atlas_actions_fix_hwm_gate3_20260628_035319.out   2> /tmp/atlas_actions_fix_hwm_gate3_20260628_035319.err
```

Pass flag:

```text
True
```

Result JSON:

```text
STAGING_ALL_RESULTS_JSON=[{"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6465, "trades": 10}, "counts_before": {"pending_pullbacks": 26, "signals": 6377, "trades": 10}, "cycle": 1, "elapsed_seconds": 362.145, "result": "DO NOTHING", "scanned_count": 75, "under_limit": true}, {"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6553, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6465, "trades": 10}, "cycle": 2, "elapsed_seconds": 171.502, "result": "DO NOTHING", "scanned_count": 73, "under_limit": true}, {"candidate_count": 97, "counts_after": {"pending_pullbacks": 28, "signals": 6641, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6553, "trades": 10}, "cycle": 3, "elapsed_seconds": 207.058, "result": "DO NOTHING", "scanned_count": 73, "under_limit": true}]
```

## DB safety proof

Current post-staging counts:

```text
/Users/yasser/scripts/atlas.db {"pending_pullbacks": [26, 35], "signals": [6377, 6395], "trades": [10, 18]}
/tmp/atlas_staging.db {"pending_pullbacks": [28, 37], "signals": [6641, 6659], "trades": [10, 18]}
```

Interpretation:

```text
Production DB count remains signals=6377, trades=10, pending_pullbacks=26.
Staging DB changed during Gate 3 as expected.
```

## Forbidden-label scan

```text
Staging workspace forbidden broker label count: 0
```

## Decision

```text
All requested staging gates passed after replacing the unsafe rolling 15-minute primary selection with signal ID high-water logic.
Production deploy remains blocked until Prof. approves.
```

## Production deploy command set after approval only

```bash
PHASE=actions_fix_hwm
STAMP=$(date +%Y%m%d_%H%M%S)
PROD=/Users/yasser/scripts
STAGE=/tmp/atlas_actions_fix_staging_scripts

cp -p "$PROD/atlas_intraday.py" "$PROD/atlas_intraday_backup_${PHASE}_${STAMP}.py"
cp -p "$PROD/atlas_db.py" "$PROD/atlas_db_backup_${PHASE}_${STAMP}.py"
cp -p "$STAGE/atlas_intraday.py" "$PROD/atlas_intraday.py"
cp -p "$STAGE/atlas_db.py" "$PROD/atlas_db.py"
python3 -m py_compile "$PROD/atlas_intraday.py" "$PROD/atlas_db.py"
python3 "$PROD/atlas_intraday.py" --force
```
