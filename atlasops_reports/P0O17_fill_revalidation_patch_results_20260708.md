# P0O-17: Pullback Fill-Time Revalidation Patch (Staging-Only) — Results

**Status:** STAGING-ONLY. Approved under Standing Alpha-Work Override. All patches applied to staged copies under `/tmp/p0o17/` only; production files and DB untouched (SHA-verified before and after). Builds directly on the P0O-16 design.

---

## What Was Built

**Staged files patched:**
1. **`/tmp/p0o17/src/atlas_db.py`** (unprotected) — added one new read-only helper, `get_latest_signal(ticker, as_of=None)`, which fetches the freshest `signals` table row for a ticker. Pure read, zero side effects, zero writes.
2. **`/tmp/p0o17/src/atlas_portfolio.py`** (protected) — added 3 new functions (`_now_utc`, `_hours_between`, `_revalidate_pullback_fill`) and inserted the revalidation gate call inside `evaluate_pending_pullback()`, strictly between the existing price-trigger check and the existing `consider_buy()` call.
3. **`/tmp/p0o17/src/atlas_manage.py`** — **NOT modified.** The freshness window is a self-contained constant inside `atlas_portfolio.py`; no parameter-wiring through `atlas_manage.py` was needed, so this file was left untouched (confirmed via `diff`, zero differences from production).

**Gate logic (`_revalidate_pullback_fill`):** on every price-trigger touch, re-queries the live `signals` table via the new helper and routes to one of 3 outcomes:
- **`ALLOW_FILL`** (`FILL_REVALIDATION_PASSED`) — fresh signal is still BUY-tier, pillar count ≥3, RVOL passes, age within the freshness window → proceeds into the unchanged `consider_buy()` call
- **`EXPIRE_STALE_SIGNAL`** — fresh signal is AVOID (`FILL_EXPIRED_SIGNAL_AVOID`) or age exceeds the window (`FILL_EXPIRED_SIGNAL_AGE_EXCEEDED`) → calls the existing `expire_pending_pullback()`, same mechanism already used by the calendar-expiry path
- **`BLOCK_SIGNAL_DECAYED`** — fresh signal exists but has decayed below BUY-tier/RVOL floor (`FILL_BLOCKED_SIGNAL_DECAYED_SCORE`/`_RVOL`), or no fresh signal row exists at all (`FILL_BLOCKED_LIVE_DATA_MISSING`, the conservative default per P0O-16 Section 3) → returns a WAIT-type decision this pass, armed row stays intact for re-evaluation next pass

**Freshness window:** `PULLBACK_FILL_MAX_SIGNAL_AGE_HOURS = 24.0` — a new, explicit, adjustable implementation parameter (not a protected alpha constant), chosen conservatively based on P0O-14's empirical finding that most decay was already visible well inside 24h.

---

## Verification

| Check | Result |
|---|---|
| Compile — `atlas_db.py` | PASS |
| Compile — `atlas_portfolio.py` | PASS |
| Import test (patched `atlas_portfolio.py` against copied DB) | PASS — clean import, zero errors |
| `atlas_manage.py` | Confirmed byte-identical to production via `diff` — not modified, not needed |

### Tests (all against the copied DB `/tmp/p0o17/db/atlas_copy_p0o17.db` only)

| # | Scenario | Result |
|---|---|---|
| 1 | Fresh BUY-tier signal (4/4, RVOL pass) → `ALLOW_FILL` | **PASS** — `{'outcome': 'ALLOW_FILL', 'reason_code': 'FILL_REVALIDATION_PASSED', ...}` |
| 2 | WATCH decay (2/4) → `BLOCK_SIGNAL_DECAYED` | **PASS** — `{'outcome': 'BLOCK_SIGNAL_DECAYED', 'reason_code': 'FILL_BLOCKED_SIGNAL_DECAYED_SCORE', ...}` |
| 3a | AVOID decay (1/4) → `EXPIRE_STALE_SIGNAL` | **PASS** — `{'outcome': 'EXPIRE_STALE_SIGNAL', 'reason_code': 'FILL_EXPIRED_SIGNAL_AVOID', ...}` |
| 3b | Confirmed the expire mechanism actually flips DB status | **PASS** — test pullback row status became `EXPIRED` in the copied DB after calling the same `expire_pending_pullback()` the gate invokes |
| 4 | Missing live signal (ticker never in `signals` table) → `BLOCK_SIGNAL_DECAYED` | **PASS** — `{'outcome': 'BLOCK_SIGNAL_DECAYED', 'reason_code': 'FILL_BLOCKED_LIVE_DATA_MISSING', ...}` |
| 5 | Age exceeded (signal 48h old, fresh BUY label but stale) → `EXPIRE_STALE_SIGNAL` | **PASS** — `{'outcome': 'EXPIRE_STALE_SIGNAL', 'reason_code': 'FILL_EXPIRED_SIGNAL_AGE_EXCEEDED', 'age_hours': 48.0, ...}` |
| 6 | Price not triggered → existing WAIT path unchanged | **PASS** — confirmed via diff inspection that neither the `if not state:` early-WAIT branch nor the final WAIT-tail (after the trigger block) had any lines removed |

**7/7 assertions passed.**

### No Broker/Cash/Trades Writes — Verified

Table row counts compared before/after the entire test run, on both the copied DB and (separately) the untouched production DB:

| Table | Count (copied DB, after tests) | Count (production DB) | Match? |
|---|---|---|---|
| `trades` | 70 | 70 | YES |
| `cash_ledger` | 21 | 21 | YES |
| `broker_reconciliation` | 0 | 0 | YES |
| `position_lots` | 67 | 67 | YES |
| `portfolio_event_journal` | 85 | 85 | YES |

The only writes made anywhere during this task were to `signals` (test fixtures) and `pending_pullbacks` (one test row, intentionally created and then expired to prove the mechanism) — both in the copied DB only, never production.

### Protected Formula/Constant Disclosure — Checked

Diffed the entire patch against production and extracted every new numeric literal introduced: `24.0` (new freshness-window parameter), `3` (the pillar-tier floor, already publicly visible in every live Atlas report's "Score X/4 Pillars" display — not a new disclosure), `3600.0` (generic seconds→hours conversion), and `2705` (the hex digits of the `\u2705` checkmark-emoji unicode escape used to match the existing volume-pass marker format — not a number, not a constant). **Zero protected scoring formulas, thresholds, or alpha constants appear anywhere in the diff.**

### Byte-Identical Confirmation for Untouched Functions

Extracted and hash-compared the full function bodies of `consider_buy()`, `check_admission()`, `evaluate_exit()`, and `run_exits()` between production and the staged patch — **all 4 are byte-identical**, confirming zero impact on the buy-sizing pipeline, the admission gate, and the entire exit/stop engine.

### Production Files/DB — Re-Verified Unchanged

| File | SHA before | SHA after |
|---|---|---|
| `atlas.db` | `75eebd1...4370b258` | `75eebd1...4370b258` (match) |
| `atlas_portfolio.py` | `606332c...676c69` | `606332c...676c69` (match) |
| `atlas_db.py` | `72859e7...9ec18` | `72859e7...9ec18` (match) |
| `atlas_manage.py` | `96693d7...0e4f10` | `96693d7...0e4f10` (match) |

---

## Answers to Structured Fields

- **P0O17_STATUS:** PATCH_COMPLETE (staging-only), all required behaviors implemented and tested
- **staged_files:** `/tmp/p0o17/src/atlas_db.py` (new read-only helper added), `/tmp/p0o17/src/atlas_portfolio.py` (revalidation gate added), `/tmp/p0o17/src/atlas_manage.py` (copied but NOT modified — confirmed unneeded)
- **compile_result:** PASS for both modified files
- **tests_passed:** 7/7 — all 6 required scenarios covered (fresh BUY→ALLOW_FILL, WATCH→BLOCK, AVOID→EXPIRE, missing data→BLOCK, age exceeded→EXPIRE, price-not-triggered path proven unchanged via diff)
- **fill_time_revalidation_added:** YES
- **consider_buy_unchanged:** YES — byte-identical function body confirmed via extraction+comparison
- **broker_flow_unchanged:** YES — zero writes to `trades`, `cash_ledger`, `broker_reconciliation`, `position_lots`, or `portfolio_event_journal` anywhere in this task
- **stop_exit_logic_unchanged:** YES — `evaluate_exit()` and `run_exits()` byte-identical, confirmed via extraction+comparison
- **production_files_unchanged:** YES — SHA-256 verified identical before and after for all 3 source files
- **production_db_unchanged:** YES — SHA-256 verified identical before and after
- **protected_formula_disclosure:** NO — every new numeric literal in the diff accounted for (freshness window, already-public pillar floor, generic time conversion, unicode escape digits); zero scoring formulas or alpha constants exposed
- **ready_for_production_patch_review:** YES — staged, compiled, tested, and verified; awaiting Prof's review and explicit deployment authorization before any production copy
- **production changes:** NONE
