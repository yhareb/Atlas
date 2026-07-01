# AtlasOps GitHub + Google Drive Backup Fix Sign-off — 2026-07-01

## Summary

- Git push exit code: `0`
- Remote branch: `origin/main`
- Pushed HEAD: `23b5a23b`
- Current tracked exclusion matches after cleanup: `0`
- Existing daily backup scheduler: LaunchAgent `/Users/yasser/Library/LaunchAgents/com.atlas.hermesgdrivebackup.plist`
- Backup script: `/Users/yasser/scripts/hermes_gdrive_backup.sh`
- Backup script syntax: `bash -n` PASS

## Push verification

```text
23b5a23bd42f3bc569c319d43f03f363675231be	refs/heads/main
```

## Final `.gitignore`

```gitignore
# Atlas GitHub backup exclusions — code/system files only

# Secrets / local env
.env
*.env
.env.*

# Python caches
__pycache__/
pycache/
*.pyc
*.pyo

# Virtual environments / dependency installs
.atlasingestvenv/
.venv/
*venv/
*env/

# Runtime databases / state
*.db
*.db-journal
*.sqlite
*.sqlite3

# Runtime scratch / data stores
/tmp/
tmp/
atlas_inbox/
atlas_vectordb/

# Logs / process output
*.log
*.err.log
*.err
*.out

# Backups / generated archives
*.bak*
*.bak_*
*.backup*
*_backup_*.py
*_backup_*.sh
*_wo[0-9]*_*.py
*_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9].py
*.zip
*.tar.gz
backups/
/Users/yasser/backups/
staging/

# OS/editor noise
.DS_Store
*.tmp
```

## Existing Google Drive daily backup LaunchAgent entry

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atlas.hermesgdrivebackup</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/yasser/scripts/hermes_gdrive_backup.sh</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>WorkingDirectory</key>
  <string>/Users/yasser</string>

  <key>StandardOutPath</key>
  <string>/Users/yasser/scripts/hermes_gdrive_backup.launchd.out.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/yasser/scripts/hermes_gdrive_backup.launchd.err.log</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
```

## Perme backup path verification

```text
PRESENT scripts/atlas_perme.py
PRESENT scripts/atlas_rag_flags.py
PRESENT scripts/atlas_rag.py
PRESENT .hermes/profiles/perme
PRESENT atlas_inbox
PRESENT atlas_vectordb
BASH_N=PASS
```

## Updated backup script diff

```diff
diff --git a/hermes_gdrive_backup.sh b/hermes_gdrive_backup.sh
index 5b24a735..cbd2248d 100755
--- a/hermes_gdrive_backup.sh
+++ b/hermes_gdrive_backup.sh
@@ -10,6 +10,15 @@ TS="$(/bin/date '+%Y-%m-%d_%H%M')"
 ARCHIVE_NAME="hermes_backup_${TS}.tar.gz"
 ARCHIVE_PATH="${BACKUP_ROOT}/${ARCHIVE_NAME}"
 TMP_LOG="${BACKUP_ROOT}/last_run.tmp.log"
+BACKUP_ITEMS=(
+  ".hermes"
+  "scripts/atlas_perme.py"
+  "scripts/atlas_rag_flags.py"
+  "scripts/atlas_rag.py"
+  ".hermes/profiles/perme"
+  "atlas_inbox"
+  "atlas_vectordb"
+)
 
 mkdir -p "$BACKUP_ROOT"
 touch "$LOG_FILE"
@@ -107,8 +116,14 @@ if [ ! -x "$RCLONE" ]; then
   fail 3 "check rclone"
 fi
 
+for item in "${BACKUP_ITEMS[@]}"; do
+  if [ ! -e "/Users/yasser/${item}" ]; then
+    fail 7 "check backup item ${item}"
+  fi
+done
+
 run_step "create Google Drive folder" "$RCLONE" mkdir "$REMOTE_DIR"
-run_step "create tar.gz archive" /usr/bin/tar -czf "$ARCHIVE_PATH" -C /Users/yasser .hermes
+run_step "create tar.gz archive" /usr/bin/tar -czf "$ARCHIVE_PATH" -C /Users/yasser "${BACKUP_ITEMS[@]}"
 
 if [ ! -s "$ARCHIVE_PATH" ]; then
   fail 4 "verify local archive non-empty"
```

## Final GitHub tracked file list (`git ls-files`)

```text
.atlas_audit_vendor/.lock
.atlas_audit_vendor/psycopg-3.2.13.dist-info/INSTALLER
.atlas_audit_vendor/psycopg-3.2.13.dist-info/METADATA
.atlas_audit_vendor/psycopg-3.2.13.dist-info/RECORD
.atlas_audit_vendor/psycopg-3.2.13.dist-info/REQUESTED
.atlas_audit_vendor/psycopg-3.2.13.dist-info/WHEEL
.atlas_audit_vendor/psycopg-3.2.13.dist-info/licenses/LICENSE.txt
.atlas_audit_vendor/psycopg-3.2.13.dist-info/top_level.txt
.atlas_audit_vendor/psycopg/__init__.py
.atlas_audit_vendor/psycopg/_acompat.py
.atlas_audit_vendor/psycopg/_adapters_map.py
.atlas_audit_vendor/psycopg/_capabilities.py
.atlas_audit_vendor/psycopg/_cmodule.py
.atlas_audit_vendor/psycopg/_column.py
.atlas_audit_vendor/psycopg/_compat.py
.atlas_audit_vendor/psycopg/_connection_base.py
.atlas_audit_vendor/psycopg/_connection_info.py
.atlas_audit_vendor/psycopg/_conninfo_attempts.py
.atlas_audit_vendor/psycopg/_conninfo_attempts_async.py
.atlas_audit_vendor/psycopg/_conninfo_utils.py
.atlas_audit_vendor/psycopg/_copy.py
.atlas_audit_vendor/psycopg/_copy_async.py
.atlas_audit_vendor/psycopg/_copy_base.py
.atlas_audit_vendor/psycopg/_cursor_base.py
.atlas_audit_vendor/psycopg/_dns.py
.atlas_audit_vendor/psycopg/_encodings.py
.atlas_audit_vendor/psycopg/_enums.py
.atlas_audit_vendor/psycopg/_oids.py
.atlas_audit_vendor/psycopg/_pipeline.py
.atlas_audit_vendor/psycopg/_pipeline_async.py
.atlas_audit_vendor/psycopg/_pipeline_base.py
.atlas_audit_vendor/psycopg/_preparing.py
.atlas_audit_vendor/psycopg/_py_transformer.py
.atlas_audit_vendor/psycopg/_queries.py
.atlas_audit_vendor/psycopg/_server_cursor.py
.atlas_audit_vendor/psycopg/_server_cursor_async.py
.atlas_audit_vendor/psycopg/_server_cursor_base.py
.atlas_audit_vendor/psycopg/_struct.py
.atlas_audit_vendor/psycopg/_tpc.py
.atlas_audit_vendor/psycopg/_transformer.py
.atlas_audit_vendor/psycopg/_typeinfo.py
.atlas_audit_vendor/psycopg/_typemod.py
.atlas_audit_vendor/psycopg/_tz.py
.atlas_audit_vendor/psycopg/_wrappers.py
.atlas_audit_vendor/psycopg/abc.py
.atlas_audit_vendor/psycopg/adapt.py
.atlas_audit_vendor/psycopg/client_cursor.py
.atlas_audit_vendor/psycopg/connection.py
.atlas_audit_vendor/psycopg/connection_async.py
.atlas_audit_vendor/psycopg/conninfo.py
.atlas_audit_vendor/psycopg/copy.py
.atlas_audit_vendor/psycopg/crdb/__init__.py
.atlas_audit_vendor/psycopg/crdb/_types.py
.atlas_audit_vendor/psycopg/crdb/connection.py
.atlas_audit_vendor/psycopg/cursor.py
.atlas_audit_vendor/psycopg/cursor_async.py
.atlas_audit_vendor/psycopg/dbapi20.py
.atlas_audit_vendor/psycopg/errors.py
.atlas_audit_vendor/psycopg/generators.py
.atlas_audit_vendor/psycopg/postgres.py
.atlas_audit_vendor/psycopg/pq/__init__.py
.atlas_audit_vendor/psycopg/pq/_debug.py
.atlas_audit_vendor/psycopg/pq/_enums.py
.atlas_audit_vendor/psycopg/pq/_pq_ctypes.py
.atlas_audit_vendor/psycopg/pq/_pq_ctypes.pyi
.atlas_audit_vendor/psycopg/pq/abc.py
.atlas_audit_vendor/psycopg/pq/misc.py
.atlas_audit_vendor/psycopg/pq/pq_ctypes.py
.atlas_audit_vendor/psycopg/py.typed
.atlas_audit_vendor/psycopg/raw_cursor.py
.atlas_audit_vendor/psycopg/rows.py
.atlas_audit_vendor/psycopg/sql.py
.atlas_audit_vendor/psycopg/transaction.py
.atlas_audit_vendor/psycopg/types/__init__.py
.atlas_audit_vendor/psycopg/types/array.py
.atlas_audit_vendor/psycopg/types/bool.py
.atlas_audit_vendor/psycopg/types/composite.py
.atlas_audit_vendor/psycopg/types/datetime.py
.atlas_audit_vendor/psycopg/types/enum.py
.atlas_audit_vendor/psycopg/types/hstore.py
.atlas_audit_vendor/psycopg/types/json.py
.atlas_audit_vendor/psycopg/types/multirange.py
.atlas_audit_vendor/psycopg/types/net.py
.atlas_audit_vendor/psycopg/types/none.py
.atlas_audit_vendor/psycopg/types/numeric.py
.atlas_audit_vendor/psycopg/types/numpy.py
.atlas_audit_vendor/psycopg/types/range.py
.atlas_audit_vendor/psycopg/types/shapely.py
.atlas_audit_vendor/psycopg/types/string.py
.atlas_audit_vendor/psycopg/types/uuid.py
.atlas_audit_vendor/psycopg/version.py
.atlas_audit_vendor/psycopg/waiting.py
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/INSTALLER
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/METADATA
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/RECORD
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/REQUESTED
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/WHEEL
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/licenses/LICENSE.txt
.atlas_audit_vendor/psycopg_binary-3.2.13.dist-info/top_level.txt
.atlas_audit_vendor/psycopg_binary/.dylibs/libcom_err.3.0.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libcrypto.3.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libgssapi_krb5.2.2.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libk5crypto.3.1.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libkrb5.3.3.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libkrb5support.1.1.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/liblber.2.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libldap.2.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libpq.5.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libsasl2.3.dylib
.atlas_audit_vendor/psycopg_binary/.dylibs/libssl.3.dylib
.atlas_audit_vendor/psycopg_binary/__init__.py
.atlas_audit_vendor/psycopg_binary/_psycopg.cpython-39-darwin.so
.atlas_audit_vendor/psycopg_binary/_psycopg.pyi
.atlas_audit_vendor/psycopg_binary/_uuid.py
.atlas_audit_vendor/psycopg_binary/pq.cpython-39-darwin.so
.atlas_audit_vendor/psycopg_binary/py.typed
.atlas_audit_vendor/psycopg_binary/version.py
.atlas_audit_vendor/typing_extensions-4.15.0.dist-info/INSTALLER
.atlas_audit_vendor/typing_extensions-4.15.0.dist-info/METADATA
.atlas_audit_vendor/typing_extensions-4.15.0.dist-info/RECORD
.atlas_audit_vendor/typing_extensions-4.15.0.dist-info/REQUESTED
.atlas_audit_vendor/typing_extensions-4.15.0.dist-info/WHEEL
.atlas_audit_vendor/typing_extensions-4.15.0.dist-info/licenses/LICENSE
.atlas_audit_vendor/typing_extensions.py
.gitignore
archive/atlas_actions_fix_hwm_prod_incident_20260628.md
archive/atlas_actions_fix_hwm_staging_signoff_20260628_035319.md
archive/atlas_canon_redesign_staging_signoff_20260629.md
archive/atlas_engine_BROKEN_20260622_1640.py
archive/atlas_force_live_flag_staging_signoff_20260628.md
archive/market_scout_timeout_investigation_20260622.md
archive/post_market_report_after_tsmfix_dryrun_20260623.txt
archive/post_market_report_eodredesign_20260623_174418_freshbaseline.py
archive/post_market_report_eodredesign_livewired_dryrun_20260623.txt
archive/post_market_report_eodredesign_sample_20260622.txt
archive/post_market_report_sample_decisionlayer_20260622.md
archive/post_market_report_sample_engine_catalysts_20260622.md
archive/post_market_report_sample_risk_etf_20260622.md
archive/pre_market_report_sample_engine_catalysts_20260622.md
atlas_4_fixes_report_20260622_1811.md
atlas_4fixes_staging_signoff_20260629.md
atlas_account.py
atlas_actions_fix_staging_signoff_20260628_030223.md
atlas_all_report_template_dryrun_samples_20260629.md
atlas_audit.py
atlas_audit_report.py
atlas_backup.py
atlas_broker_ingest.py
atlas_daily.py
atlas_db.py
atlas_deep_system_verification_20260629_181420.md
atlas_deep_test_round2_20260630_025000.md
atlas_engine.py
atlas_eod_positions.py
atlas_ingest.py
atlas_instructions.md
atlas_intraday.py
atlas_intraday_fulldecision_run_20260622_1711.md
atlas_intraday_status.py
atlas_macro_postmarket.py
atlas_macro_premarket.py
atlas_macro_premarket_launchd.sh
atlas_manage.py
atlas_manage_handoff_persistence_report_20260622_1730.md
atlas_news_probe_and_market_scout_ordering_20260622.md
atlas_notify.py
atlas_overnight_gap.py
atlas_phase10_session_close_20260627_031933.md
atlas_portfolio.py
atlas_premarket_gaps.py
atlas_premarket_template.md
atlas_preopen_check.py
atlas_rag.py
atlas_rag_flags.py
atlas_readonly_patch_discovery_20260622.md
atlas_report_handoff.py
atlas_schemas.py
atlas_sector_universe_evidence_20260628_021759.md
atlas_staging_architecture_20260628.md
atlas_stream.py
atlas_symbol_meta.py
atlas_telegram_storage_file_list_20260628.md
atlas_ter_mksi_spy_gate_evidence_20260628.md
atlas_time.py
atlas_watchlist_handoff_inspection_20260622.md
atlasops_instructions.md
eod_writer.py
gate1_final_confirmation_20260627.md
gate1_verify_20260627_174142/atlas_macro_postmarket_force.txt
gate1_verify_20260627_174142/atlas_macro_premarket_force.txt
gate1_verify_20260627_174142/pre_market_report_force.txt
hermes_gdrive_backup.sh
june26_semis_signals_rows_20260628.md
lrcx_phantom_trade_readonly_investigation_20260623.md
m3_post_update_verification_20260628_212229.md
market_scout.py
morning_briefing.py
pending_fill_flow_report_20260623.md
post_market_report.py
post_market_report_corrected_render_from_md_20260622.txt
post_market_report_sample_fresh_window_20260622.md
pre_market_format_audit_20260625.md
pre_market_futures_na_probe_20260622.md
pre_market_report.py
pre_market_report_readonly_inspection_20260622.md
pre_market_report_sample_fresh_window_20260622.md
pullback_workorder_test_report_20260622_194945.md
report_samples_20260629/audit_report.stderr.txt
report_samples_20260629/audit_report.stdout.txt
report_samples_20260629/eod_handoff.stderr.txt
report_samples_20260629/eod_handoff.stdout.txt
report_samples_20260629/intraday_report.stderr.txt
report_samples_20260629/intraday_report.stdout.txt
report_samples_20260629/post_market_report.stderr.txt
report_samples_20260629/post_market_report.stdout.txt
report_samples_20260629/pre_market_brief.stderr.txt
report_samples_20260629/pre_market_brief.stdout.txt
report_samples_20260629/pre_market_gap_scan.stderr.txt
report_samples_20260629/pre_market_gap_scan.stdout.txt
report_samples_20260629/pre_market_macro_brief.stderr.txt
report_samples_20260629/pre_market_macro_brief.stdout.txt
report_templates_review/01_pre_market_brief.txt
report_templates_review/02_pre_market_gap_scan.txt
report_templates_review/03_pre_market_macro_brief.txt
report_templates_review/04_intraday_report.txt
report_templates_review/05_post_market_report.txt
report_templates_review/06_eod_handoff.txt
report_templates_review/07_audit_report.txt
tests/staging_simulated_report.py
tests/test_scan_timing.py
tsm_sell_lrcx_cleanup_targetfix_report_20260623.md
vault_client.py
vault_sync.py
```

## Current local working tree note

These unrelated local code modifications remain uncommitted/preserved after the GitHub backup cleanup:

```text
 M atlas_ingest.py
 M atlas_intraday.py
 M atlas_manage.py
 M atlas_rag_flags.py
 M atlas_report_handoff.py
 M atlas_symbol_meta.py
 M market_scout.py
 M pre_market_report.py
?? atlas_api_audit.py
?? atlas_perme.py
```
