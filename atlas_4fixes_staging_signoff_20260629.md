# Atlas 4-Fix Staging Sign-off Packet

Status: STAGING ONLY. Production files, Telegram config, `.env`, and chat ID fields were not touched.

## Scope
1. Intraday ACTIONS: cap BUY display to top 5; overflow BUY signals appear in WAITING FOR DIP display only.
2. EOD handoff: remove `FIRST LIVE TEST`; footer date generated dynamically.
3. Pre-market macro brief: block sends/generation on non-market ET calendar days, even with `--force`.
4. Post-market macro brief: same non-market ET calendar-day gate.

## Staging workspace
- Scripts: `/tmp/atlas_4fixes_staging_scripts`
- Staging DB: `/tmp/atlas_4fixes_staging.db`
- Gate 3 DB: `/tmp/atlas_staging.db`

## Files changed in staging
- `/tmp/atlas_4fixes_staging_scripts/atlas_intraday.py`
- `/tmp/atlas_4fixes_staging_scripts/atlas_report_handoff.py`
- `/tmp/atlas_4fixes_staging_scripts/atlas_macro_premarket.py`
- `/tmp/atlas_4fixes_staging_scripts/atlas_macro_postmarket.py`
- `/tmp/atlas_4fixes_staging_scripts/tests/test_scan_timing.py` (staging harness path override only)

## Gate 1 — compile
```text
python3 -m py_compile atlas_intraday.py atlas_report_handoff.py atlas_macro_premarket.py atlas_macro_postmarket.py tests/test_scan_timing.py
compile_exit=0
```

## Gate 1 — behavior proofs

### Intraday ACTIONS cap + dry-run enforced
```text
[intraday] --force without --live: verification dry-run enforced; production DB writes and Telegram sends suppressed
🛒 BUY (5 of 30)
━━━ 🎣 WAITING FOR DIP (32) ━━━
[intraday] dry-run: final telegram send suppressed
```

### EOD handoff label/footer proof
```text
   🚀 Gap-up window 9:30–10:00 ET
   📈 Intraday breakout window 10:00–12:00 ET
   ✅ All fixes verified · June 28, 2026
FIRST_LIVE_TEST_PRESENT=no
```

### Macro pre-market non-market-day gate
```text
[macro_premarket] calendar gate closed; non-market ET day 2026-06-28; no report sent
```

### Macro post-market non-market-day gate
```text
[macro_postmarket] calendar gate closed; non-market ET day 2026-06-28; no report sent
```

### Production DB before/after Gate 1
```text
before: trades=10 signals=6906 pending_pullbacks=27
after : trades=10 signals=6906 pending_pullbacks=27
```

## Gate 2 — timing harness
```text
GATE2_RESULT_JSON={"candidate_count": 94, "elapsed_seconds": 477.315, "gate1_critical_tables": ["trades", "pending_pullbacks"], "isolated_db": "/var/folders/nz/48nykj7s0tl__8dfhq6dd0vm0000gn/T/atlas_scan_timing_k266ozxb/atlas_timing.db", "max_seconds": 480.0, "result": "DO NOTHING", "scanned_count": 70, "source_counts_after": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "source_counts_before": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "source_counts_unchanged": true, "source_critical_counts_unchanged": true, "temp_counts_after": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "temp_counts_before": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "under_limit": true}
[GATE2] elapsed_seconds=477.315
[GATE2] PASS
stderr:
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

## Gate 3 — three staging cycles
```text
STAGING_CYCLE_RESULT_JSON={"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 6906, "trades": 10}, "cycle": 1, "elapsed_seconds": 339.935, "result": "DO NOTHING", "scanned_count": 75, "under_limit": true}
STAGING_CYCLE_RESULT_JSON={"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 7076, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "cycle": 2, "elapsed_seconds": 157.691, "result": "DO NOTHING", "scanned_count": 74, "under_limit": true}
STAGING_CYCLE_RESULT_JSON={"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 7161, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 7076, "trades": 10}, "cycle": 3, "elapsed_seconds": 192.498, "result": "DO NOTHING", "scanned_count": 74, "under_limit": true}
STAGING_ALL_RESULTS_JSON=[{"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 6906, "trades": 10}, "cycle": 1, "elapsed_seconds": 339.935, "result": "DO NOTHING", "scanned_count": 75, "under_limit": true}, {"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 7076, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 6991, "trades": 10}, "cycle": 2, "elapsed_seconds": 157.691, "result": "DO NOTHING", "scanned_count": 74, "under_limit": true}, {"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 7161, "trades": 10}, "counts_before": {"pending_pullbacks": 28, "signals": 7076, "trades": 10}, "cycle": 3, "elapsed_seconds": 192.498, "result": "DO NOTHING", "scanned_count": 74, "under_limit": true}]
[STAGING] PASS
stderr:
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

## Diff: atlas_intraday.py
```diff
diff --git a/Users/yasser/scripts/atlas_intraday.py b/tmp/atlas_4fixes_staging_scripts/atlas_intraday.py
index 07fef75..c795c30 100755
--- a/Users/yasser/scripts/atlas_intraday.py
+++ b/tmp/atlas_4fixes_staging_scripts/atlas_intraday.py
@@ -543,13 +543,24 @@ def _risk_label_for_signal(row, summary):
     return "0.5% risk" if pillars == 3 or cautious else "1% risk"
 
 
+def _pillar_score_value(item):
+    text = str((item or {}).get("score") or "0/4")
+    m = re.search(r"(\d+)\s*/", text)
+    return int(m.group(1)) if m else 0
+
+
 def _actions_lines(buys, sells, summary=None, before_scan_signal_id=None):
     signal_buys = _unique(_current_cycle_buy_signals(before_scan_signal_id), key="ticker")
+    signal_buys = sorted(signal_buys, key=lambda b: (-_pillar_score_value(b), str(b.get("ticker") or "")))
+    display_buys = signal_buys[:5]
+    overflow_buys = signal_buys[5:]
+    if isinstance(summary, dict):
+        summary["_actions_overflow_buys"] = overflow_buys
     sells = _unique(sells)
     lines = ["", "━━━ ACTIONS ━━━"]
-    if signal_buys:
-        lines.append(f"🛒 BUY ({len(signal_buys)})")
-        for b in signal_buys:
+    if display_buys:
+        lines.append(f"🛒 BUY ({len(display_buys)} of {len(signal_buys)})")
+        for b in display_buys:
             ticker = str(b.get("ticker") or "?").upper()
             entry = _num(b.get("entry_price"))
             stop = _num(b.get("stop_loss"))
@@ -696,8 +707,20 @@ def _intraday_breakout_lines(summary):
     return lines
 
 
-def _waiting_lines(high):
+def _waiting_lines(high, extra_buy_waits=None):
     waits = _unique([h for h in high if str(h.get("action", "")).upper() == "WAIT" and "PULLBACK" in str(h.get("reason", "")).upper()])
+    for b in extra_buy_waits or []:
+        waits.append({
+            "ticker": str(b.get("ticker") or "").upper(),
+            "score": b.get("score"),
+            "entry": b.get("entry_price"),
+            "price": b.get("entry_price"),
+            "pct_over_ema": 0,
+            "reason": "Display overflow from ACTIONS BUY cap — wait for dip/recheck before acting",
+            "signal": b.get("signal"),
+            "warnings": b.get("warnings"),
+        })
+    waits = _unique(waits, key="ticker")
     lines = ["", f"━━━ 🎣 WAITING FOR DIP ({len(waits)}) ━━━", ""]
     if not waits:
         lines.append("✅ none")
@@ -816,7 +839,7 @@ def _build_report(summary):
     lines += _holding_lines(summary)
     lines += _gap_breakout_lines(summary)
     lines += _intraday_breakout_lines(summary)
-    lines += _waiting_lines(high)
+    lines += _waiting_lines(high, summary.get("_actions_overflow_buys", []))
     lines += _gates_lines(high)
     lines += _watch_lines(summary)
     return "\n".join(lines)
```

## Diff: atlas_report_handoff.py
```diff
diff --git a/Users/yasser/scripts/atlas_report_handoff.py b/tmp/atlas_4fixes_staging_scripts/atlas_report_handoff.py
index 65e418b..f145b8c 100644
--- a/Users/yasser/scripts/atlas_report_handoff.py
+++ b/tmp/atlas_4fixes_staging_scripts/atlas_report_handoff.py
@@ -137,8 +137,8 @@ def _watch_tomorrow_lines():
     lines = [
         "2️⃣ WATCH TOMORROW",
         "",
-        "   🚀 Gap-up window 9:30–10:00 ET — FIRST LIVE TEST",
-        "   📈 Intraday breakout window 10:00–12:00 ET — FIRST LIVE TEST",
+        "   🚀 Gap-up window 9:30–10:00 ET",
+        "   📈 Intraday breakout window 10:00–12:00 ET",
         "",
     ]
     lines += pullbacks or ["   🎣 No armed pullbacks"]
@@ -186,7 +186,8 @@ def build_atlas_handoff_report(context=None, report_date=None):
     lines += [SEP, ""]
     lines += _break_lines()
     lines += [SEP]
-    lines += [f"   ✅ All fixes verified · {day.strftime('%B %-d, %Y')}"]
+    footer_day = datetime.now(ET).date()
+    lines += [f"   ✅ All fixes verified · {footer_day.strftime('%B %-d, %Y')}"]
     lines += [SEP]
     return "\n".join(lines)
 
```

## Diff: atlas_macro_premarket.py
```diff
diff --git a/Users/yasser/scripts/atlas_macro_premarket.py b/tmp/atlas_4fixes_staging_scripts/atlas_macro_premarket.py
index 838db3c..d3fe017 100755
--- a/Users/yasser/scripts/atlas_macro_premarket.py
+++ b/tmp/atlas_4fixes_staging_scripts/atlas_macro_premarket.py
@@ -28,6 +28,12 @@ try:
 except Exception:
     _send_telegram = None
 
+try:
+    from atlas_time import is_trading_day
+except Exception:
+    def is_trading_day(day):
+        return day.weekday() < 5
+
 ET = ZoneInfo("America/New_York")
 MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
 EODHD_BASE = "https://eodhd.com/api"
@@ -479,6 +485,11 @@ def send_report(message: str) -> bool:
     return bool(_send_telegram(message, label="macro_premarket", parse_mode=""))
 
 
+def _valid_market_calendar_day(now_et: datetime | None = None) -> bool:
+    now_et = now_et or datetime.now(ET)
+    return bool(is_trading_day(now_et.date()))
+
+
 def main(argv: list[str] | None = None) -> int:
     parser = argparse.ArgumentParser(description="Atlas macro pre-market brief")
     parser.add_argument("--dry-run", action="store_true", help="Print report without Telegram send")
@@ -486,6 +497,10 @@ def main(argv: list[str] | None = None) -> int:
     parser.add_argument("--no-llm", action="store_true", help="Use deterministic fallback narrative")
     args = parser.parse_args(argv)
 
+    if not _valid_market_calendar_day():
+        print(f"[macro_premarket] calendar gate closed; non-market ET day {datetime.now(ET).date()}; no report sent")
+        return 0
+
     if not args.force and not _launchd_gate_open():
         return 0
 
```

## Diff: atlas_macro_postmarket.py
```diff
diff --git a/Users/yasser/scripts/atlas_macro_postmarket.py b/tmp/atlas_4fixes_staging_scripts/atlas_macro_postmarket.py
index c2882d1..dc7163b 100755
--- a/Users/yasser/scripts/atlas_macro_postmarket.py
+++ b/tmp/atlas_4fixes_staging_scripts/atlas_macro_postmarket.py
@@ -28,6 +28,12 @@ try:
 except Exception:
     _send_telegram = None
 
+try:
+    from atlas_time import is_trading_day
+except Exception:
+    def is_trading_day(day):
+        return day.weekday() < 5
+
 ET = ZoneInfo("America/New_York")
 EODHD_BASE = "https://eodhd.com/api"
 HTTP_TIMEOUT = float(os.environ.get("ATLAS_MACRO_POSTMARKET_TIMEOUT", "8"))
@@ -497,6 +503,11 @@ def send_report(message: str) -> bool:
     return bool(_send_telegram(message, label="macro_postmarket", parse_mode=""))
 
 
+def _valid_market_calendar_day(now_et: datetime | None = None) -> bool:
+    now_et = now_et or datetime.now(ET)
+    return bool(is_trading_day(now_et.date()))
+
+
 def main(argv: list[str] | None = None) -> int:
     parser = argparse.ArgumentParser(description="Atlas macro post-market wrap")
     parser.add_argument("--dry-run", action="store_true", help="Print report without Telegram send")
@@ -504,6 +515,10 @@ def main(argv: list[str] | None = None) -> int:
     parser.add_argument("--no-llm", action="store_true", help="Use deterministic fallback narrative")
     args = parser.parse_args(argv)
 
+    if not _valid_market_calendar_day():
+        print(f"[macro_postmarket] calendar gate closed; non-market ET day {datetime.now(ET).date()}; no report sent")
+        return 0
+
     if not args.force and not _launchd_gate_open():
         return 0
 
```

## Final production DB counts after all staging work
```text
trades=10
signals=6906
pending_pullbacks=27
```

## Deploy status
NOT DEPLOYED. Awaiting Prof approval.
