# P0N-3 — PRODUCTION eod_writer.py Telegram Routing Patch — DEPLOYMENT PLAN

**Date:** 2026-07-08
**Status:** PLAN ONLY — nothing executed, nothing patched, nothing deployed. No env changes, no Telegram sends, no protected-file interaction.

## 1. Production File SHA Baseline (re-verified now)
`/Users/yasser/scripts/eod_writer.py` = `7d45d22c6a66d75257cab97d138a1f9cbc82ca35c72859a74ccb848e18963fcb` — matches P0N-2 baseline exactly, unchanged.

## 2. Staged File SHA + Compile Status (re-verified now)
`/tmp/p0n2/src/eod_writer.py` = `515bc83f92acc2e679dd0a4b587bb396c365b33fb2a8bf11108f7ec80ecfb8e7`
Fresh recompile (cache cleared, rerun): `python3 -m py_compile eod_writer.py` → exit code 0, PASS.

## 3. Diff Re-Verification — Route-Only Change
Diff between production and staged confirms exactly 3 changed regions, nothing else:
- **Import line:** `from atlas_notify import send_telegram` → `... , _admin_chat_id as _owner_chat_id`
- **`_reports_group_chat_id()` / `_postmarket_thread_id()`:** comment-only additions marking them as retained-for-reference/unused (functions themselves not deleted, not called by the new send path)
- **`_send_report_telegram()`:** group-preferring branch replaced with unconditional `send_telegram(message, label="eod_writer", parse_mode="", chat_id=_owner_chat_id(), message_thread_id=None)`

**Content-building functions unchanged:** re-confirmed via isolated diff of `_build_handoff_message()` through `generate_eod_handoff()` — 0 differences (exit code 0).
**Cron/scheduler untouched:** this deployment only copies a `.py` file; the Hermes `atlas`-profile cron job `bfcc04221d23` ("EOD Handoff Writer", schedule `5 0 * * 2-6`) is not part of the deploy — confirmed currently in normal `scheduled` state, not paused/mid-run, no changes planned to its definition.

**additive_diff_verified: YES** / **content_unchanged_verified: YES**

## 4. Backup Plan
```
archive/eod_writer.py_<TS>_p0n3_predeploy.bak.py
```
SHA256-verified against the production baseline (§1) immediately after copy, taken only inside a confirmed idle window.

## 5. Idle-Window Plan
Pre-check at plan time (informational, to be re-checked live at execution time):
- `eod_writer.py` process: **currently idle**, no process found.
- No lock file present in `/Users/yasser/scripts/`.
- Hermes cron job `bfcc04221d23`: state=`scheduled`, `last_run_at` was 2026-07-08 00:06:10, next run not due until 2026-07-09 00:05 — no active/mid-run instance.

At execution time: re-check `pgrep -f eod_writer.py` and the lock-file check immediately before backup, and again immediately before the file copy. Bounded idle poll (12-min cap / 5s interval, same proven pattern as prior P0L/P0M deployments) if a process/lock is found. Abort/BLOCKED if no clean window materializes within the cap.

## 6. Deploy — Copy Staged File to Production
```bash
cp /tmp/p0n2/src/eod_writer.py /Users/yasser/scripts/eod_writer.py
```
Post-copy: SHA256-verify production file matches staged SHA (`515bc83f...cb8e7`) exactly.

## 7. Compile + Pycache Clear
```bash
python3 -m py_compile eod_writer.py
```
Then clear stale bytecode: standard `__pycache__/` entry plus macOS `com.apple.python` cache paths for this one module (same sweep pattern as prior deployments).

## 8. Smoke Test Plan (zero real Telegram/network calls, zero protected-file interaction)
1. **Source check — `_owner_chat_id()` used:** grep production `_send_report_telegram()` body for `chat_id=_owner_chat_id()`.
2. **Source check — `message_thread_id=None`:** grep for `message_thread_id=None` in the same function.
3. **Source check — group/topic vars absent from send path:** grep `_send_report_telegram()` body specifically (not the whole file) for `ATLAS_REPORTS_GROUP_CHAT_ID` / `ATLAS_TOPIC_POSTMARKET_THREAD_ID` / `_reports_group_chat_id(` / `_postmarket_thread_id(` — expect zero matches inside that function.
4. **Mocked route test (same technique as P0N-2):** import production `eod_writer` with `atlas_notify.send_telegram` monkey-patched to a capture function (no real network call), `_owner_chat_id` mocked to a sentinel, and `ATLAS_REPORTS_GROUP_CHAT_ID`/`ATLAS_TOPIC_POSTMARKET_THREAD_ID` deliberately poisoned with wrong sentinel values — assert the captured `chat_id` equals the mock DM sentinel (not the poisoned group sentinel) and `message_thread_id is None`.
   - **Import-resolution constraint:** `eod_writer.py` does `import atlas_portfolio as port` at module level. Per this task's explicit instruction, the real `atlas_portfolio.py` will **not** be copied, read, or imported for this smoke test. The same non-functional stub module used in P0N-2 (`consider_buy`/`_last_price` both raise `NotImplementedError`, zero real logic) will be reused/placed on `sys.path` ahead of the real file so the import resolves without ever touching the protected file. The smoke test only exercises `_send_report_telegram()`, which never calls into `port`.
5. **No real Telegram send:** confirmed by construction — `send_telegram` is fully mocked for step 4; steps 1-3 are static source greps only.

## 9. Rollback Plan
```bash
cp archive/eod_writer.py_<TS>_p0n3_predeploy.bak.py /Users/yasser/scripts/eod_writer.py
```
SHA-verify restored file matches the pre-deploy production baseline (§1) exactly. Recompile, clear pycache. No DB rollback needed — this deployment performs zero DB writes.

## 10. Pre-Market Files — Confirmed Unchanged / Still DM-Only
Re-verified now (informational, not part of this deploy):
- `pre_market_report.py` SHA=`5ca4a1c4a29860212b147eaaa81146225002463f6f802a3c5b9976a85def4275` — `chat_id=_owner_chat_id()`, `message_thread_id=None` confirmed present.
- `atlas_macro_premarket.py` SHA=`c8ab2c023c3ca2317148c0b586fe6e97a88b4e702944ef7a87c93aab172c1e9b` — same DM-only pattern confirmed present.
Neither file is touched by this deployment; both remain correctly routed.

**premarket_routes_unchanged: YES**

---

## Return Fields

- **P0N3_STATUS:** DEPLOYMENT_PLAN_READY
- **production_file_sha_baseline:** `eod_writer.py` = `7d45d22c6a66d75257cab97d138a1f9cbc82ca35c72859a74ccb848e18963fcb` (unchanged, re-verified)
- **staged_file_sha:** `eod_writer.py` = `515bc83f92acc2e679dd0a4b587bb396c365b33fb2a8bf11108f7ec80ecfb8e7` — fresh recompile PASS (exit 0)
- **additive_diff_verified:** YES (only import line + `_send_report_telegram()`/comment region changed; 3 scoped regions, nothing else)
- **content_unchanged_verified:** YES (isolated diff of `_build_handoff_message()`→`generate_eod_handoff()`: 0 differences)
- **deployment_window_plan:** bounded idle poll, 12-min cap / 5s interval; pre-check confirms `eod_writer.py` currently idle, no lock file, cron job `bfcc04221d23` in normal `scheduled` state (not mid-run); re-check immediately before backup and again before copy; abort/BLOCKED if no clean window or if process/lock appears mid-sequence
- **backup_plan:** timestamped copy tagged `p0n3_predeploy` in `archive/`, SHA256-verified against production baseline immediately after copy
- **smoke_test_plan:** 3 static source-grep checks (`_owner_chat_id()` used, `message_thread_id=None`, group/topic vars absent from the send function specifically) + 1 mocked-route test (poisoned group/topic env sentinels, mocked `send_telegram`/`_owner_chat_id`, zero real network calls) — import resolution for `atlas_portfolio` uses the same non-functional stub from P0N-2, never the real protected file
- **rollback_plan:** restore from `p0n3_predeploy`-tagged backup, SHA-verify against production baseline, recompile, clear pycache — no DB rollback needed (zero DB writes)
- **protected_files_untouched_plan:** `atlas_engine.py`/`atlas_portfolio.py` will not be read, copied, or imported at any point in this deployment or its smoke tests; the P0N-2 stub module (synthetic placeholder, zero real logic) is reused solely to satisfy `eod_writer.py`'s module-level import statement during the mocked route test
- **premarket_routes_unchanged:** YES (`pre_market_report.py`/`atlas_macro_premarket.py` re-verified DM-only, SHAs unchanged, not part of this deploy)
- **risks:** live-process/cron-job contention during the idle window (mitigated by bounded poll + cron-state pre-check); stale bytecode cache (mitigated by explicit clear step); regression to report content (LOW — diff shows content-building functions byte-identical); protected-file exposure (NIL — stub-only import resolution, real files never touched); Hermes cron job `bfcc04221d23` firing mid-deploy (LOW — next run not due until 2026-07-09 00:05, well outside any reasonable deployment window)
- **approval_required:** YES
- **production changes:** NONE
