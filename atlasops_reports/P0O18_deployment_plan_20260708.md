# P0O-18: PRODUCTION DEPLOYMENT PLAN — Pullback Fill-Time Revalidation

**Status:** PLANNING ONLY. Nothing executed. No production files patched, no production DB written, no deployment performed. This is a TFE live-rule change (it alters when an armed pending pullback is allowed to convert into a real BUY attempt) — deployment requires Prof's **explicit approval** after reviewing this plan, separate from the earlier Standing Alpha-Work Override approval that covered the P0O-17 staging work itself.

---

## 1–2. SHA / Compile Confirmation (Re-Verified This Task)

| File | Production SHA | Staged SHA (P0O-17) | Status |
|---|---|---|---|
| `atlas.db` | `75eebd16...4370b258` | N/A (DB not modified by this patch) | Baseline unchanged, matches P0O-17 |
| `atlas_portfolio.py` | `606332cb...8676c69` | `97793979...05897d` | Differs — this IS the patch |
| `atlas_db.py` | `72859e7c...29ec18` | `dee59dea...986ba7b` | Differs — this IS the patch |
| `atlas_manage.py` | `96693d72...0e4f10` | `96693d72...0e4f10` | **Identical** — confirms `atlas_manage.py` was never touched and will NOT be deployed |

Staged `atlas_db.py`/`atlas_portfolio.py` re-compiled clean (`py_compile` PASS) immediately before writing this plan.

## 3. Unchanged-Function Verification (Re-Confirmed)

Extracted and byte-compared full function bodies between production and staged `atlas_portfolio.py`:

| Function | Byte-identical? |
|---|---|
| `consider_buy()` | YES |
| `check_admission()` | YES |
| `evaluate_exit()` | YES |
| `run_exits()` | YES |

Zero impact on sizing, admission, or the entire exit/stop engine — re-confirmed at plan time, not just at P0O-17 build time.

## 4. Changed-Behavior Location (Confirmed Scope)

All new logic sits **strictly inside `evaluate_pending_pullback()`**, specifically the branch that already handles "price has touched the trigger" — between the existing price check and the existing `consider_buy()` call. Three new functions added (`_now_utc`, `_hours_between`, `_revalidate_pullback_fill`); one new read-only helper added to `atlas_db.py` (`get_latest_signal`). No other function in either file is touched. The WAIT-path branches (both the "price not yet at trigger" early return and the trailing WAIT block after the trigger branch) are untouched — confirmed via diff inspection.

## 5. Backup Plan

- **Timestamped backups, tagged `p0o18_predeploy`:**
  - `archive/atlas_portfolio.py_<timestamp>_p0o18_predeploy.bak.py`
  - `archive/atlas_db.py_<timestamp>_p0o18_predeploy.bak.py`
- Each backup SHA-verified against the live production file immediately before backup creation, and re-verified immediately after, per standing protocol.
- **`atlas_manage.py` gets NO backup** — it will not be touched or deployed, consistent with Section 1's SHA match confirming it's identical to production already.

## 6. Deployment Window Plan

- **Pre-check (already performed for this plan):** confirmed no `atlas_manage.py`/`atlas_intraday.py`/`atlas_eod_positions.py`/`eod_writer.py`/`pre_market_report.py`/`atlas_macro_*` processes currently running (`pgrep` returned empty); `com.atlas.intraday` launchd job confirmed idle (PID `-`, not mid-run).
- **Bounded idle-poll at actual execution time (standing pattern):** re-check the same process list immediately before copying files, wait up to 12 minutes in 5-second increments if anything is mid-run, abort if no clean window materializes within the cap.
- **Target idle gate:** absence of any running process that imports `atlas_portfolio.py` or `atlas_db.py` — this covers `atlas_manage.py`-driven scans (the actual caller of `evaluate_pending_pullback`), `atlas_intraday.py`, and `atlas_eod_positions.py`, all of which transitively touch these two files.

## 7. Copy-to-Production Plan

- Copy `/tmp/p0o17/src/atlas_db.py` → `/Users/yasser/scripts/atlas_db.py`
- Copy `/tmp/p0o17/src/atlas_portfolio.py` → `/Users/yasser/scripts/atlas_portfolio.py`
- **Do NOT copy `atlas_manage.py`** — explicitly out of scope; will be verified NOT deployed (SHA re-check post-deploy should still show `atlas_manage.py` unchanged from its current production SHA)
- SHA-verify each copied file matches its staged source exactly immediately after copy

## 8. Compile + Pycache Plan

- Run `python3 -m py_compile atlas_db.py atlas_portfolio.py` against the live production files immediately after copy — must PASS before proceeding
- Clear `__pycache__` for both files (and any macOS-specific bytecode cache paths) to guarantee the next real import picks up the new source, not a stale compiled artifact

## 9. Copied-DB Smoke Test Plan (Production Files, Copied DB Only — Zero Production DB Writes)

All 6 smoke tests re-run against a **freshly copied** `atlas.db` (new copy taken at deployment time, not reusing the stale P0O-17 copy) — but exercising the **actual deployed production `atlas_portfolio.py`/`atlas_db.py`** files, not the staging copies, to prove the real deployed artifact behaves identically to what was tested in P0O-17:

| # | Scenario | Expected outcome |
|---|---|---|
| 1 | Fresh BUY-tier signal (4/4, RVOL pass) inserted into copied DB's `signals` table | `ALLOW_FILL` / `FILL_REVALIDATION_PASSED` |
| 2 | WATCH-tier signal (2/4) inserted | `BLOCK_SIGNAL_DECAYED` / `FILL_BLOCKED_SIGNAL_DECAYED_SCORE` |
| 3 | AVOID-tier signal (1/4) inserted + a test `pending_pullbacks` row | `EXPIRE_STALE_SIGNAL` / `FILL_EXPIRED_SIGNAL_AVOID`, AND confirm the test row's status actually flips to `EXPIRED` in the **copied** DB (never production) |
| 4 | Ticker with no `signals` row at all | `BLOCK_SIGNAL_DECAYED` / `FILL_BLOCKED_LIVE_DATA_MISSING` |
| 5 | BUY-tier signal but 48h old (age exceeds 24h window) | `EXPIRE_STALE_SIGNAL` / `FILL_EXPIRED_SIGNAL_AGE_EXCEEDED` |
| 6 | Price not yet at trigger | Existing WAIT path fires, unchanged — verified via diff-based proof (no removal of existing WAIT-path lines), same method as P0O-17 |

Test harness pattern: same `test_p0o17.py` approach as staging, but pointed at a fresh production-file import + fresh DB copy, run from a location that cannot accidentally write to the real production DB path (explicit `atlas_db.DB_PATH` override to the new copy, verified before any test executes).

## 10. No-Production-DB-Write Guarantee

- Every smoke test's `atlas_db.DB_PATH` is explicitly overridden to the fresh copy's path before any test logic runs — verified by printing/asserting the override took effect prior to test execution.
- Table row-count sweep (same 5 tables checked in P0O-17: `trades`, `cash_ledger`, `broker_reconciliation`, `position_lots`, `portfolio_event_journal`) compared on the **production** DB immediately before and immediately after the entire smoke-test run — must show zero deltas.
- The one intentional test-fixture write (the AVOID-scenario `pending_pullbacks` row insert + its expiry) happens exclusively in the copied DB, never in the path that could reach production.

## 11. Protected Formula/Constant Non-Disclosure Check

Re-run the same diff-based numeric-literal audit performed at P0O-17: extract every new numeric literal introduced by the deployed diff and confirm each is either (a) the new `24.0`-hour freshness-window parameter, (b) the pillar-tier floor of `3` (already public in every live rendered report), or (c) generic code constants (seconds-per-hour conversion, etc.) — zero scoring formulas, thresholds, or alpha constants disclosed anywhere in the deployed diff, report, or terminal output.

## 12. Rollback Plan

- If any compile check, smoke test, or the numeric-literal audit fails at deployment time: restore both files from their `p0o18_predeploy`-tagged backups, SHA-verify the restoration matches the pre-deploy baseline exactly, re-run compile as a final confirmation, and report the failure to Prof without proceeding further.
- No DB rollback is needed under any failure scenario, since this deployment makes zero production DB writes at any point (smoke tests are copied-DB-only, and the deployment itself only copies two `.py` files).
- Rollback re-establishes the exact P0O-17-baseline production state (SHAs `606332cb...` / `72859e7c...`) with no partial or intermediate state possible, since the copy operation is a simple two-file overwrite, not a multi-step migration.

---

## Answers to Structured Fields

- **P0O18_STATUS:** DEPLOYMENT_PLAN_COMPLETE — nothing executed, awaiting Prof's explicit deployment approval
- **production_file_sha_baseline:** `atlas_portfolio.py`=`606332cb...8676c69`, `atlas_db.py`=`72859e7c...29ec18`, `atlas_manage.py`=`96693d72...0e4f10`, `atlas.db`=`75eebd16...4370b258` — all re-verified unchanged from the P0O-17 baseline at plan time
- **staged_file_sha:** `atlas_portfolio.py`=`97793979...05897d`, `atlas_db.py`=`dee59dea...986ba7b` (both differ from production — this is the patch); `atlas_manage.py`=`96693d72...0e4f10` (identical to production — confirms it will NOT be deployed)
- **changed_behavior_summary:** New fill-time revalidation gate inserted strictly between the existing price-trigger check and the existing `consider_buy()` call inside `evaluate_pending_pullback()`; routes to `ALLOW_FILL`/`EXPIRE_STALE_SIGNAL`/`BLOCK_SIGNAL_DECAYED` based on a fresh re-query of the live `signals` table (new read-only `atlas_db.get_latest_signal()` helper) — no other code path touched
- **unchanged_functions_verified:** `consider_buy()`, `check_admission()`, `evaluate_exit()`, `run_exits()` — all re-confirmed byte-identical between production and staged files at plan time
- **deployment_window_plan:** Pre-checked idle now (no relevant processes running, `com.atlas.intraday` confirmed idle); bounded idle-poll (12min/5s) immediately before actual copy at execution time; target gate = no running process importing `atlas_portfolio.py`/`atlas_db.py`
- **backup_plan:** Timestamped, SHA-verified backups tagged `p0o18_predeploy` for `atlas_portfolio.py` and `atlas_db.py` only; `atlas_manage.py` gets no backup since it is not being touched
- **smoke_test_plan:** All 6 P0O-17 scenarios re-run against a freshly-copied DB (new copy at deploy time) but using the actual deployed production source files, with `atlas_db.DB_PATH` explicitly overridden to the copy before any test executes
- **rollback_plan:** Restore both files from `p0o18_predeploy` backups on any failure, SHA-verify restoration, re-compile as final check; zero DB rollback needed since no production DB write occurs anywhere in this deployment
- **live_rule_change_acknowledged:** YES — this changes when a pending pullback is permitted to fire a live BUY attempt (adds new WAIT/EXPIRE outcomes that don't exist today); explicitly flagged as a TFE live-rule change, not routine ops, per the task's own framing
- **approval_required:** YES — deployment will not proceed without Prof's explicit go-ahead on this specific plan
- **production changes:** NONE
