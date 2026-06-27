# Atlas Phase 10 Session Close Report

Generated: 2026-06-27 03:19:33 

## 1. Launchd Jobs

| Label | Loaded | State | Runs | Last exit | Path |
|---|---:|---|---:|---|---|
| `com.atlas.intraday` | YES | not running | 209 | 0 | `/Users/yasser/Library/LaunchAgents/com.atlas.intraday.plist` |
| `com.atlas.premarket` | YES | not running | 1 | 0 | `/Users/yasser/Library/LaunchAgents/com.atlas.premarket.plist` |
| `com.atlas.macro.premarket` | YES | not running | 0 | (never exited) | `/Users/yasser/Library/LaunchAgents/com.atlas.macro.premarket.plist` |
| `com.atlas.macro.postmarket` | YES | not running | 0 | (never exited) | `/Users/yasser/Library/LaunchAgents/com.atlas.macro.postmarket.plist` |
| `com.atlas.audit` | NO | not found |  |  | `plist missing` |
| `com.atlas.audit.report` | YES | not running | 113 | 0 | `/Users/yasser/Library/LaunchAgents/com.atlas.audit.report.plist` |
| `com.atlas.audit.retention` | YES | not running | 4 | 0 | `/Users/yasser/Library/LaunchAgents/com.atlas.audit.retention.plist` |
| `com.atlas.hermesgdrivebackup` | YES | not running | 2 | 0 | `/Users/yasser/Library/LaunchAgents/com.atlas.hermesgdrivebackup.plist` |
| `com.atlas.preopen.check` | YES | not running | 6 | 0 | `/Users/yasser/Library/LaunchAgents/com.atlas.preopen.check.plist` |
| `com.atlas.vaultsync` | YES | not running | 1730 | 1 | `/Users/yasser/Library/LaunchAgents/com.atlas.vaultsync.plist` |

Requested labels summary:
- `com.atlas.intraday`: loaded
- `com.atlas.premarket`: loaded
- `com.atlas.macro.premarket`: loaded
- `com.atlas.macro.postmarket`: loaded
- `com.atlas.audit`: not found/does not exist
- Audit jobs present under `com.atlas.audit.report` and `com.atlas.audit.retention`; no exact `com.atlas.audit` label exists.

## 2. Production DB Counts
- `trades`: 10
- `pending_pullbacks`: 26
- `signals`: 6377

## 3. TER / ONTO DB Search

Exact ticker/symbol checks:
- `trades.ticker` exact TER/ONTO count: 0
- `pending_pullbacks.ticker` exact TER/ONTO count: 0
- `signals.ticker` exact TER/ONTO count: 4
  - `{"id": 4705, "ticker": "TER", "timestamp": "2026-06-26 12:20:05"}`
  - `{"id": 4710, "ticker": "ONTO", "timestamp": "2026-06-26 12:21:25"}`
  - `{"id": 4714, "ticker": "TER", "timestamp": "2026-06-26 12:23:21"}`
  - `{"id": 4717, "ticker": "ONTO", "timestamp": "2026-06-26 12:23:50"}`

Broad text contains checks (for audit completeness):
- `handoff.data` contains `TER`: 2
- `handoff.data` contains `ONTO`: 1
- `pending_pullbacks.signal_json` contains `TER`: 21
- `pending_pullbacks.signal_json` contains `ONTO`: 3
- `signals.ticker` contains `TER`: 2
- `signals.ticker` contains `ONTO`: 2
- `signals.warnings` contains `TER`: 4

Conclusion: TER/ONTO are absent from `trades` and `pending_pullbacks`, but historical `signals` rows still contain exact TER/ONTO ticker rows; therefore “no TER or ONTO rows anywhere in DB” is NOT fully true.

## 4. Compile Checks

- `/Users/yasser/scripts/atlas_intraday.py`: PASS
- `/Users/yasser/scripts/atlas_manage.py`: PASS
- `/Users/yasser/scripts/pre_market_report.py`: PASS
- `/Users/yasser/scripts/atlas_macro_premarket.py`: PASS
- `/Users/yasser/scripts/atlas_macro_postmarket.py`: PASS
- `/Users/yasser/scripts/tests/test_scan_timing.py`: PASS

## 5. Backup Files Created Since 2026-06-26 00:00

Total backup/log backup matches: 38

- `/Users/yasser/Library/LaunchAgents/com.atlas.premarket.report_backup_20260627_012448_phase5_label_fix.plist` — 1076 bytes — mtime 2026-06-27 01:24:48 
- `/Users/yasser/scripts/atlas_audit_report_backup_20260626_180453_snapshot404_fallback.py` — 9209 bytes — mtime 2026-06-26 18:04:53 
- `/Users/yasser/scripts/atlas_backup_20260626_001656_eod_handoff_style.db` — 1978368 bytes — mtime 2026-06-26 00:16:56 
- `/Users/yasser/scripts/atlas_backup_20260626_003856_intraday_breakout.db` — 1978368 bytes — mtime 2026-06-26 00:38:56 
- `/Users/yasser/scripts/atlas_backup_20260626_010102_unified_handoff.db` — 1978368 bytes — mtime 2026-06-26 01:01:02 
- `/Users/yasser/scripts/atlas_backup_20260627_001514_phase1_remove_TER_ONTO_pending_fill.db` — 2904064 bytes — mtime 2026-06-27 00:06:38 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_003856_intraday_breakout.py` — 26049 bytes — mtime 2026-06-26 00:38:56 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_010102_unified_handoff.py` — 27050 bytes — mtime 2026-06-26 01:01:02 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_161958_sector_sweep.py` — 26004 bytes — mtime 2026-06-26 16:21:26 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_182424_interim_report_watchdog.py` — 26144 bytes — mtime 2026-06-26 18:24:24 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_184924_intraday_report_nohandoff_watchdog.py` — 26906 bytes — mtime 2026-06-26 18:49:24 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_191231_hard_timeout.py` — 30752 bytes — mtime 2026-06-26 19:12:31 
- `/Users/yasser/scripts/atlas_intraday_backup_20260626_213509_report_first_before_sector_sweep.py` — 31593 bytes — mtime 2026-06-26 21:35:09 
- `/Users/yasser/scripts/atlas_intraday_backup_20260627_000339_cronfix.py` — 32629 bytes — mtime 2026-06-27 00:03:39 
- `/Users/yasser/scripts/atlas_intraday_backup_20260627_010309_phase2_pending_entries.py` — 32405 bytes — mtime 2026-06-27 01:03:09 
- `/Users/yasser/scripts/atlas_intraday_backup_20260627_010850_phase2_pending_entries_reapply.py` — 33219 bytes — mtime 2026-06-27 01:08:50 
- `/Users/yasser/scripts/atlas_intraday_backup_20260627_011308_phase3_watchdog_180s.py` — 33219 bytes — mtime 2026-06-27 01:13:08 
- `/Users/yasser/scripts/atlas_intraday_backup_20260627_011430_phase4_watching_sort.py` — 33221 bytes — mtime 2026-06-27 01:14:30 
- `/Users/yasser/scripts/atlas_manage_backup_20260626_003856_intraday_breakout.py` — 31358 bytes — mtime 2026-06-26 00:38:56 
- `/Users/yasser/scripts/atlas_manage_backup_20260626_161958_sector_sweep.py` — 33936 bytes — mtime 2026-06-26 16:19:58 
- `/Users/yasser/scripts/atlas_manage_backup_20260626_220250_parallel_pillar_checks.py` — 40859 bytes — mtime 2026-06-26 22:02:50 
- `/Users/yasser/scripts/atlas_manage_backup_20260627_000339_sectorcache.py` — 42197 bytes — mtime 2026-06-27 00:03:39 
- `/Users/yasser/scripts/atlas_manage_backup_20260627_011430_phase4_watching_sort.py` — 42197 bytes — mtime 2026-06-27 01:14:30 
- `/Users/yasser/scripts/atlas_portfolio_backup_20260626_003856_intraday_breakout.py` — 53347 bytes — mtime 2026-06-26 00:38:56 
- `/Users/yasser/scripts/atlas_portfolio_backup_20260626_161958_sector_sweep.py` — 61391 bytes — mtime 2026-06-26 16:19:58 
- `/Users/yasser/scripts/atlas_portfolio_backup_20260626_180204_cwan_snapshot404.py` — 72331 bytes — mtime 2026-06-26 18:02:04 
- `/Users/yasser/scripts/atlas_portfolio_backup_20260627_000339_sectorcache.py` — 74335 bytes — mtime 2026-06-27 00:03:39 
- `/Users/yasser/scripts/atlas_preopen_check_backup_20260627_002959_premarket_marker.py` — 10061 bytes — mtime 2026-06-27 00:29:59 
- `/Users/yasser/scripts/eod_writer_backup_20260626_001656_handoff_style.py` — 3305 bytes — mtime 2026-06-26 00:16:56 
- `/Users/yasser/scripts/eod_writer_backup_20260626_010102_unified_handoff.py` — 7477 bytes — mtime 2026-06-26 01:01:02 
- `/Users/yasser/scripts/hermes_gdrive_backup.launchd.out.log` — 1848 bytes — mtime 2026-06-26 06:06:50 
- `/Users/yasser/scripts/hermes_gdrive_backup.log` — 2616 bytes — mtime 2026-06-26 06:06:50 
- `/Users/yasser/scripts/morning_briefing_backup_20260626_170619_intradaystyle.py` — 1804 bytes — mtime 2026-06-26 17:06:19 
- `/Users/yasser/scripts/post_market_report_backup_20260626_010102_unified_handoff.py` — 28511 bytes — mtime 2026-06-26 01:01:02 
- `/Users/yasser/scripts/pre_market_report_backup_20260626_010102_unified_handoff.py` — 45911 bytes — mtime 2026-06-26 01:01:02 
- `/Users/yasser/scripts/pre_market_report_backup_20260627_000339_launchdfix.py` — 45953 bytes — mtime 2026-06-27 00:03:39 
- `/Users/yasser/scripts/pre_market_report_backup_20260627_012448_phase5_dryrun_cli.py` — 47160 bytes — mtime 2026-06-27 01:24:48 
- `/Users/yasser/scripts/pre_market_report_backup_20260627_015345_phase6_early_movers.py` — 47880 bytes — mtime 2026-06-27 01:53:45 
