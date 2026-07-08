# P0O-8: Replay Harness Invariant Repair (Staging-Only) — Results

**Status:** STAGING-ONLY. Fixed the P0O-7 invariant violation, re-ran the identical 10-symbol replay, verified zero violations. All work under `/tmp/p0o8/`; production untouched.

---

## Root Cause of the P0O-7 Bug

The daily-bar loop tracked one field, `last_stop_value`, for both "the stop value computed on the most recent day *before* the policy triggered" and "the stop value to report as today's live recommendation." Once a policy triggered mid-history (`triggered = True`), the loop's `continue` statement froze `last_stop_value` at that historical trigger-day level and never updated it again. The markdown report then displayed this **stale, frozen** value as if it were a live "VALID" recommended stop — even when the ticker's price had since fallen *below* that frozen level, making the displayed "stop" numerically higher than the current price. That is exactly what happened to SYNA (frozen at 120.36 vs. current 119.37) and RL (frozen at 395.45 vs. current 395.31).

## Fix Applied

Added an explicit post-loop reconciliation step in `replay_one_position()` that separates two previously-conflated concepts into 5 distinct fields per policy:

| Field | Meaning |
|---|---|
| `policy_exit_triggered` | Did this policy's stop cross on some historical day during the replay window? (YES/NO) |
| `policy_exit_date` | The historical date it triggered, or `null` |
| `policy_exit_price` | The stop level at the moment it triggered, or `null` |
| `current_recommended_stop_status` | `VALID` / `NO_VALID_STOP` / `POLICY_ALREADY_TRIGGERED` |
| `current_recommended_stop_price` | Only populated when status is `VALID`; always `null` otherwise |

**Hard invariant enforcement (defense in depth, 2 layers):**
1. If `policy_exit_triggered` is `True`, `current_recommended_stop_status` is forced to `POLICY_ALREADY_TRIGGERED` and `current_recommended_stop_price` is forced to `null` — a policy that already fired historically can never present a "live recommended stop" at all; it presents a **SELL_REVIEW verdict** instead.
2. If not triggered, before emitting `VALID`, the code re-checks `last_stop_value < current_price_today` explicitly (a second, final check beyond the per-day check already inside `candidate_stops()`) — if that check fails for any reason, status falls back to `NO_VALID_STOP` rather than ever emitting an unsafe number.
3. The markdown report writer additionally re-verifies the same invariant at render time and would print an explicit `INVARIANT VIOLATION DETECTED` banner if one ever slipped through — a third, independent tripwire.

## Verification

| Check | Result |
|---|---|
| Compile (`py_compile`) | PASS |
| Forbidden imports | ZERO (only `os, json, sqlite3, time, datetime, pathlib.Path, requests` — `atlas_engine`/`atlas_portfolio` appear only in the docstring, never as import statements) |
| Re-run against identical 10-symbol cache | Success — cache reused (all 10 "cache hit", no re-fetch needed since same trading day) |
| No-lookahead self-test | PASS |
| Required-series preflight | PASS (10/10) |
| Exclusions | 0 |
| **Invariant violations (recommended_stop ≥ current_price for any VALID status)** | **ZERO** — verified independently in Python against the raw JSON output, and by the report writer's own built-in check |
| Production DB SHA before/after | Unchanged — `75eebd1...4370b258` |
| File created under `/Users/yasser/scripts` | None |
| Output files | Confined to `/tmp/p0o8/output/` only |

## Corrected Per-Position Results (Combined-Selection Policy)

| Ticker | Entry | Current | Baseline Stop | Policy Exit Triggered? | Exit Date | Exit Price | Recommended Stop Status | Recommended Stop Price |
|---|---|---|---|---|---|---|---|---|
| **SYNA** | 126.44 | 119.37 | 113.35 | **YES** | 2026-06-26 | 120.36 | **POLICY_ALREADY_TRIGGERED** | N/A |
| **RL** | 405.34 | 395.31 | 387.56 | **YES** | 2026-06-30 | 395.45 | **POLICY_ALREADY_TRIGGERED** | N/A |
| BAC | 57.10 | 59.86 | 57.11 | NO | N/A | N/A | VALID | 57.27 |
| ABNB | 143.03 | 148.80 | 135.96 | NO | N/A | N/A | VALID | 142.45 |

SYNA and RL now correctly present as **SELL_REVIEW under the combined-selection policy** rather than showing an invalid above-current "stop" — this is exactly the behavior specified in the task. BAC and ABNB remain HOLD with a valid, strictly-below-current recommended stop.

Full per-policy breakdown (all 6 policies × 4 tickers, all invariant-safe) is in `/tmp/p0o8/output/replay_results_v1.json`.

## Answers to Structured Fields

- **P0O8_STATUS:** INVARIANT_REPAIR_COMPLETE — bug fixed, re-verified, zero violations
- **invariant_violation_fixed:** YES
- **SYNA_forward_sim_result:** Combined-selection policy `policy_exit_triggered=YES` (2026-06-26 @ 120.36) → `current_recommended_stop_status=POLICY_ALREADY_TRIGGERED`, no live stop price emitted; verdict SELL_REVIEW
- **RL_forward_sim_result:** Combined-selection policy `policy_exit_triggered=YES` (2026-06-30 @ 395.45) → `current_recommended_stop_status=POLICY_ALREADY_TRIGGERED`, no live stop price emitted; verdict SELL_REVIEW
- **BAC_forward_sim_result:** Combined-selection policy `policy_exit_triggered=NO` → `current_recommended_stop_status=VALID`, `current_recommended_stop_price=57.27` (strictly below current 59.86); verdict HOLD
- **ABNB_forward_sim_result:** Combined-selection policy `policy_exit_triggered=NO` → `current_recommended_stop_status=VALID`, `current_recommended_stop_price=142.45` (strictly below current 148.80); verdict HOLD
- **no_valid_stop_cases:** SYNA's EMA_INVALIDATION individual policy shows `NO_VALID_STOP` (insufficient valid EMA candidate that day); all other individual-policy/ticker combinations resolved to either VALID or POLICY_ALREADY_TRIGGERED
- **no_lookahead_selftest:** PASS
- **required_series_preflight:** PASS (10/10 symbols present)
- **output_files:** `/tmp/p0o8/output/replay_report_v1.md`, `/tmp/p0o8/output/replay_results_v1.json`
- **production_paths_touched:** NO
- **protected_files_touched:** NO
- **production changes:** NONE
