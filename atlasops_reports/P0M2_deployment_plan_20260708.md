# P0M-2 — PRODUCTION Pending Broker-Confirmation Report Patch — DEPLOYMENT PLAN

**Date:** 2026-07-08
**Status:** PLAN ONLY — nothing executed, nothing patched, nothing deployed.

## 1. Production File SHA Baseline (re-verified now)
| File | SHA256 |
|---|---|
| `atlas_db.py` | `518278bf7c5309b34d14c24354f10828cbaa963ce21ea625d6d9988f33111830` |
| `atlas_intraday.py` | `f87071d3aa48741ec89618fc1c2fe19c684bb7906ac58861193be101eb966c29` |
| `atlas_eod_positions.py` | `28d2dd2c9868170d5ee5c611bfe66ea29aa88eee7ff0f5e0743605512ed91ed6` |
| `atlas_macro_postmarket.py` | `0ec35e26f11a73d8d6ef0daf7cd1b8d8d044bb53ebd89cc092e4b7aa781bbdba` (not deployed, confirmed untouched) |

Matches the P0M-1 baseline exactly — no drift since staging was built.

## 2. Staged File SHA + Compile Status (re-verified now)
| File | SHA256 |
|---|---|
| `/tmp/p0m1/src/atlas_db.py` | `72859e7c573bbc075dbf502fb7a6465138c9220650342007d045636bf2a9ec18` |
| `/tmp/p0m1/src/atlas_intraday.py` | `1d010a9052c80568dcf3a43b134dc9521af89b290481e15dea956454132b2520` |
| `/tmp/p0m1/src/atlas_eod_positions.py` | `72574070eb4e6b17d79dd538fe446f9a00c82fce36aac8ff51d658457d7afd53` |

Fresh recompile (cache cleared, rerun): `python3 -m py_compile atlas_db.py atlas_intraday.py atlas_eod_positions.py` → exit code 0, all 3 PASS.

## 3. Additive-Diff Re-Verification
`diff <production> <staged> | grep -c "^<"` (count of lines removed from the production baseline) for each file:
- `atlas_db.py`: **0** removed lines
- `atlas_intraday.py`: **0** removed lines
- `atlas_eod_positions.py`: **0** removed lines

Explicit guard checks:
- `_buy_now_lines(summary, before_scan_signal_id, high=high)` — present and called (line 1984) ✅
- `_holding_lines(summary)` call — present (line 1982) ✅
- `holding_block(rows, {})` call in EOD — present (line 221) ✅

**additive_diff_verified: YES** / **report_assembly_guard_verified: YES**

## 4. Backup Plan
Timestamped backups, tag `p0m2_predeploy`, taken only inside a confirmed idle window:
```
archive/atlas_db.py_<TS>_p0m2_predeploy.bak.py
archive/atlas_intraday.py_<TS>_p0m2_predeploy.bak.py
archive/atlas_eod_positions.py_<TS>_p0m2_predeploy.bak.py
```
Each SHA256-verified against the production baseline above immediately after copy, before any write proceeds.

## 5. Idle-Window Deployment Plan
- Bounded idle poll: 12-minute cap, 5-second interval (same proven pattern as P0L-14/16/20).
- Pre-check at plan time: `atlas_intraday.py` currently **idle**, no lock file present.
- Re-check immediately before backup, and again immediately before the file copy step — abort deployment (return BLOCKED) if no clean window materializes within the cap, or if a process/lock appears between backup and copy.

## 6. Deploy — Copy Staged Files to Production
```bash
cp /tmp/p0m1/src/atlas_db.py             /Users/yasser/scripts/atlas_db.py
cp /tmp/p0m1/src/atlas_intraday.py       /Users/yasser/scripts/atlas_intraday.py
cp /tmp/p0m1/src/atlas_eod_positions.py  /Users/yasser/scripts/atlas_eod_positions.py
```
`atlas_macro_postmarket.py` is **not** deployed (no change staged for it).
Post-copy: SHA256-verify each production file matches its staged SHA exactly (table in §2).

## 7. Compile + Pycache Clear
```bash
python3 -m py_compile atlas_db.py atlas_intraday.py atlas_eod_positions.py
```
Then clear stale bytecode: standard `__pycache__/` entries plus macOS `com.apple.python` cache paths for these 3 modules (same sweep pattern used in P0L-16/20).

## 8. Smoke Test Plan (zero production DB writes, zero Telegram sends)
1. **Import checks:** `import atlas_db; import atlas_intraday; import atlas_eod_positions` from the production path — clean, no exceptions.
2. **Direct helper query:** `atlas_db.get_pending_broker_confirmation_trades()` against the **live production DB** (read-only SELECT, no writes) → expect exactly 1 row, `ticker='INTC'`.
3. **Staged/rendered intraday body:** call `_build_report(summary)` with a minimal synthetic summary (no live network scan) → assert `"SELL TRIGGERED / BROKER CONFIRMATION PENDING"` present and `"INTC"` present in that section.
4. **Staged/rendered EOD body:** call `build_report()` → assert same section + `"INTC"` present.
5. **Artifact exclusion:** assert `"AAPL"`, `"PBXT"`, `"IBXT"` do NOT appear in the new pending section of either rendered body.
6. **Existing sections intact:** assert `"HOLDING (4)"` and `"BUY NOW"` (intraday) / `"HOLDING"` (EOD) sections still render with unchanged tickers (SYNA/RL/BAC/ABNB).
7. **Protected-file check:** re-verify `atlas_engine.py` SHA=`0fa7ca17a0b37a415c39aeed0c743b4cebc5f6d301e4b8e6f9b62ef5ec3e1e78` and `atlas_portfolio.py` SHA=`606332cbe2af4f92f7a169ce57c98d76dfac3852beed13c1634b4aa878676c69` unchanged, mtimes still Jul 2 (pre-dating this task).
8. **No DB writes / no Telegram:** confirm no smoke step calls `send_telegram()`, `close_trade`, `confirm_trade_fill`, or any INSERT/UPDATE/DELETE — all smoke steps are read-only SELECTs and in-process report-string assembly only.

## 9. Rollback Plan
```bash
cp archive/atlas_db.py_<TS>_p0m2_predeploy.bak.py             /Users/yasser/scripts/atlas_db.py
cp archive/atlas_intraday.py_<TS>_p0m2_predeploy.bak.py       /Users/yasser/scripts/atlas_intraday.py
cp archive/atlas_eod_positions.py_<TS>_p0m2_predeploy.bak.py  /Users/yasser/scripts/atlas_eod_positions.py
```
SHA-verify each restored file matches the pre-deploy production baseline (§1) exactly. Recompile, clear pycache. No DB rollback needed — this deployment performs zero DB writes at any stage (smoke included).

## 10. DB / Ledger Scope Confirmation
This deployment is **code-only**. No DB cleanup, no ledger mutation, no trade-status change, no cash_ledger write, no bookkeeping table write — the entire change is a new read-only SELECT helper plus two new report-string sections. Confirmed via §3 diff (zero non-additive changes) and §8 smoke plan (zero write operations at any step).

---

## Return Fields

- **P0M2_STATUS:** DEPLOYMENT_PLAN_READY
- **production_file_sha_baseline:** atlas_db.py=`518278bf...111830`, atlas_intraday.py=`f87071d3...66c29`, atlas_eod_positions.py=`28d2dd2c...91ed6`, atlas_macro_postmarket.py=`0ec35e26...1bbdba` (unchanged, not deployed)
- **staged_file_sha:** atlas_db.py=`72859e7c...9ec18`, atlas_intraday.py=`1d010a90...b2520`, atlas_eod_positions.py=`72574070...7afd53` — fresh recompile PASS (exit 0)
- **deploy_files:** atlas_db.py, atlas_intraday.py, atlas_eod_positions.py (atlas_macro_postmarket.py excluded — no change staged)
- **additive_diff_verified:** YES (0 removed lines in all 3 files vs. current production baseline)
- **report_assembly_guard_verified:** YES (`_buy_now_lines`, `_holding_lines`, `holding_block` all present and called exactly as before)
- **deployment_window_plan:** bounded idle poll, 12-min cap / 5s interval; re-check immediately before backup and again before copy; abort/BLOCKED if no clean window or if process/lock appears mid-sequence
- **smoke_test_plan:** import checks; direct helper query (expect exactly INTC); rendered intraday + EOD bodies both show pending section with INTC; AAPL/PBXT/IBXT excluded from both; existing HOLDING/BUY NOW sections intact; protected-file SHA/mtime re-check; zero DB writes / zero Telegram sends confirmed across all steps
- **rollback_plan:** restore all 3 files from `p0m2_predeploy`-tagged backups, SHA-verify against production baseline, recompile, clear pycache — no DB rollback needed (zero DB writes at any stage)
- **protected_files_untouched_verification:** atlas_engine.py SHA=`0fa7ca17...ec1e78`, atlas_portfolio.py SHA=`606332cb...8676c69`, both mtimes Jul 2 (pre-dating this task) — neither is copied, read, or referenced by this deployment
- **risks:** live-process lock contention during the idle window (mitigated by bounded poll, same proven pattern as P0L-14/16/20); stale bytecode cache (mitigated by explicit clear step); regression to existing report sections (LOW — diff shows 0 removed lines, guard checks confirm all prior calls intact); protected-file exposure (NIL — files never touched)
- **approval_required:** YES
- **production changes:** NONE
