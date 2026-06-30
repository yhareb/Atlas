# Atlas --force / --live Safety Patch — Staging Sign-off Packet

Status: STAGING ONLY. Production source was not deployed.

## Requested behavior
- `--force` alone: bypass market-hours gate, force dry-run, no production DB writes, no Telegram send.
- `--force --live`: bypass market-hours gate, live run, DB writes and Telegram sends allowed.
- Normal launchd/no flags: unchanged live behavior.

## Staging paths
- Staged scripts: `/tmp/atlas_force_live_flag_staging_scripts`
- Staged DB: `/tmp/atlas_force_live_flag_staging.db` and Gate 3 `/tmp/atlas_staging.db`
- Changed staged file: `/tmp/atlas_force_live_flag_staging_scripts/atlas_intraday.py`
- Changed staged Gate 2 harness copy: `/tmp/atlas_force_live_flag_staging_scripts/tests/test_scan_timing.py` only to honor `ATLAS_SCRIPTS_DIR` in staging.

## Patch diff against production atlas_intraday.py
```diff
diff --git a/Users/yasser/scripts/atlas_intraday.py b/tmp/atlas_force_live_flag_staging_scripts/atlas_intraday.py
index 321711a..07fef75 100755
--- a/Users/yasser/scripts/atlas_intraday.py
+++ b/tmp/atlas_force_live_flag_staging_scripts/atlas_intraday.py
@@ -872,9 +872,15 @@ def _send_telegram_async(message, label="atlas"):
 
 def run_intraday():
     cli_force = "--force" in sys.argv
-    cli_dry_run = "--dry-run" in sys.argv
+    cli_live = "--live" in sys.argv
+    explicit_dry_run = "--dry-run" in sys.argv
+    cli_dry_run = explicit_dry_run or (cli_force and not cli_live)
     now = datetime.datetime.now()
     print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Atlas intraday loop starting...")
+    if cli_force and cli_dry_run and not cli_live:
+        print("[intraday] --force without --live: verification dry-run enforced; production DB writes and Telegram sends suppressed")
+    elif cli_force and cli_live:
+        print("[intraday] --force --live: live forced run enabled; DB writes and Telegram sends allowed")
 
     lock_fd = _acquire_run_lock()
     if lock_fd is None:
@@ -925,6 +931,21 @@ def _run_intraday_locked(now, force=False, dry_run=False):
 
     import atlas_manage
     staging_db = os.environ.get("ATLAS_STAGING_DB") or os.environ.get("ATLAS_DB")
+    force_dryrun_temp_db = None
+    production_db = os.path.realpath("/Users/yasser/scripts/atlas.db")
+    env_db_is_production = bool(staging_db) and os.path.realpath(staging_db) == production_db
+    if force and dry_run and (not staging_db or env_db_is_production):
+        try:
+            import shutil
+            source_db = staging_db or getattr(atlas_db, "DB_PATH", "/Users/yasser/scripts/atlas.db")
+            force_dryrun_temp_db = f"/tmp/atlas_intraday_force_dryrun_{os.getpid()}.db"
+            shutil.copy2(source_db, force_dryrun_temp_db)
+            staging_db = force_dryrun_temp_db
+            print(f"[intraday] forced dry-run DB isolated: {source_db} -> {staging_db}")
+        except Exception as e:
+            force_dryrun_temp_db = None
+            print(f"[intraday] forced dry-run DB isolation failed; aborting before scan: {e}")
+            return {"skipped": True, "reason": "forced dry-run DB isolation failed"}
     if staging_db:
         try:
             atlas_db.DB_PATH = staging_db
@@ -1026,6 +1047,13 @@ def _run_intraday_locked(now, force=False, dry_run=False):
     except Exception as e:
         print(f"[intraday] telegram report failed (non-fatal): {e}")
 
+    if force_dryrun_temp_db:
+        try:
+            os.unlink(force_dryrun_temp_db)
+            print(f"[intraday] forced dry-run temp DB removed: {force_dryrun_temp_db}")
+        except Exception as e:
+            print(f"[intraday] forced dry-run temp DB cleanup warning: {e}")
+
 
 if __name__ == "__main__":
     run_intraday()
```

## Gate 1A — CLI mode semantics probe
```text
ARGV=<none>

[2026-06-28 22:30:51] Atlas intraday loop starting...
CAPTURE force=False dry_run=False
ARGV=--force

[2026-06-28 22:30:51] Atlas intraday loop starting...
[intraday] --force without --live: verification dry-run enforced; production DB writes and Telegram sends suppressed
CAPTURE force=True dry_run=True
ARGV=--force --live

[2026-06-28 22:30:51] Atlas intraday loop starting...
[intraday] --force --live: live forced run enabled; DB writes and Telegram sends allowed
CAPTURE force=True dry_run=False
ARGV=--force --dry-run

[2026-06-28 22:30:51] Atlas intraday loop starting...
[intraday] --force without --live: verification dry-run enforced; production DB writes and Telegram sends suppressed
CAPTURE force=True dry_run=True
```

## Gate 1B — compile
```text
compile_exit=0
```

## Gate 1C — staged --force alone full run, production DB no-write proof
```text
Command: ATLAS_INTRADAY_MAX_RUNTIME_SECONDS=600 PYTHONPATH=/tmp/atlas_force_live_flag_staging_scripts python3 /tmp/atlas_force_live_flag_staging_scripts/atlas_intraday.py --force

[intraday] --force without --live: verification dry-run enforced; production DB writes and Telegram sends suppressed
[intraday] dry-run: start status telegram suppressed
[intraday] forced dry-run DB isolated: /Users/yasser/scripts/atlas.db -> /tmp/atlas_intraday_force_dryrun_7766.db
[intraday] dry-run: interim telegram suppressed
Result: ACTION - 7 BUY(S), 0 SELL(S). See Vault.
[intraday] dry-run: final telegram send suppressed
[intraday] forced dry-run temp DB removed: /tmp/atlas_intraday_force_dryrun_7766.db

Production DB counts before/after from Gate 1 retry:
before: 10 / 6906 / 27
after : 10 / 6906 / 27
```

## Gate 1 caveat — first staged attempt exposed env-loading gap
```text
First attempt before the temp-DB condition was hardened:
production counts before: 10 / 6821 / 27
production counts after : 10 / 6906 / 27
Effect: production signals audit rows increased; trades and pending_pullbacks did not change.
Fix: hardened forced dry-run isolation to treat ATLAS_DB=/Users/yasser/scripts/atlas.db from the Atlas .env as production and copy it to /tmp before scan.
```

## Gate 2 — timing harness
```text
GATE2_RESULT_JSON={"candidate_count": 94, "elapsed_seconds": 334.644, "gate1_critical_tables": ["trades", "pending_pullbacks"], "isolated_db": "/var/folders/nz/48nykj7s0tl__8dfhq6dd0vm0000gn/T/atlas_scan_timing_u0rkw4ys/atlas_timing.db", "max_seconds": 480.0, "result": "ACTION", "scanned_count": 75, "source_counts_after": {"pending_pullbacks": 27, "signals": 6821, "trades": 10}, "source_counts_before": {"pending_pullbacks": 27, "signals": 6821, "trades": 10}, "source_counts_unchanged": true, "source_critical_counts_unchanged": true, "temp_counts_after": {"pending_pullbacks": 27, "signals": 6821, "trades": 10}, "temp_counts_before": {"pending_pullbacks": 27, "signals": 6821, "trades": 10}, "under_limit": true}
[GATE2] elapsed_seconds=334.644
[GATE2] PASS
stderr:
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

## Gate 3 — 3 staging cycles
```text
STAGING_CYCLE_RESULT_JSON={"candidate_count": 94, "counts_after": {"pending_pullbacks": 27, "signals": 6991, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 6906, "trades": 10}, "cycle": 1, "elapsed_seconds": 327.101, "result": "ACTION", "scanned_count": 75, "under_limit": true}
STAGING_CYCLE_RESULT_JSON={"candidate_count": 94, "counts_after": {"pending_pullbacks": 27, "signals": 7076, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 6991, "trades": 10}, "cycle": 2, "elapsed_seconds": 150.52, "result": "ACTION", "scanned_count": 75, "under_limit": true}
STAGING_CYCLE_RESULT_JSON={"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 7161, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 7076, "trades": 10}, "cycle": 3, "elapsed_seconds": 189.577, "result": "ACTION", "scanned_count": 75, "under_limit": true}
STAGING_ALL_RESULTS_JSON=[{"candidate_count": 94, "counts_after": {"pending_pullbacks": 27, "signals": 6991, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 6906, "trades": 10}, "cycle": 1, "elapsed_seconds": 327.101, "result": "ACTION", "scanned_count": 75, "under_limit": true}, {"candidate_count": 94, "counts_after": {"pending_pullbacks": 27, "signals": 7076, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 6991, "trades": 10}, "cycle": 2, "elapsed_seconds": 150.52, "result": "ACTION", "scanned_count": 75, "under_limit": true}, {"candidate_count": 94, "counts_after": {"pending_pullbacks": 28, "signals": 7161, "trades": 10}, "counts_before": {"pending_pullbacks": 27, "signals": 7076, "trades": 10}, "cycle": 3, "elapsed_seconds": 189.577, "result": "ACTION", "scanned_count": 75, "under_limit": true}]
[STAGING] PASS
stderr:
/Users/yasser/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

## Final production DB counts after staging work
```text
10
6906
27
```

## Production deploy status
NOT DEPLOYED. Awaiting Prof approval.
