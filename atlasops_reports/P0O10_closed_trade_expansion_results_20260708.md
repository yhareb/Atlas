# P0O-10: Closed-Trade Replay Expansion Implementation (Staging-Only) — Results

**Status:** STAGING-ONLY. Built on the P0O-8 invariant-fixed base (not P0O-7). All work under `/tmp/p0o10/`; production untouched. First genuine historical bar-by-bar backtest in this harness series (canonical closed trades), not just forward-simulation.

---

## What Changed vs. P0O-8

1. **Universe expansion:** unified `replay_one_trade()` now handles both forward-simulation (open positions, `is_open=True`, replay through today) and **true historical replay** (closed trades, `is_open=False`, replay from actual `entry_date` to actual `exit_date`).
2. **3 separate result buckets, 3 separate metrics computations — never blended:**
   - `OPEN_FORWARD_SIM` — SYNA, RL, BAC, ABNB (unchanged from P0O-8)
   - `CANONICAL_CLOSED` — LRCX, MS, KLIC, IRDM, ALGM, MSM (new — true historical replay)
   - `SECONDARY_INTC` — INTC only, flagged `SELL_CONFIRMATION_PENDING`, reported separately, included in an exploratory "canonical+secondary" metrics view but **never** in the canonical number
3. **Hard exclusion list:** AAPL, PBXT, IBXT, TSM never fetched or replayed at all (excluded at the ticker-list level, not just filtered post-hoc)
4. **Defensive re-check function** (`defensive_exclusion_check`) re-verifies the P0O-9 exclusion rules (no `broker_ref`, entry==exit, too-short hold) against every canonical-closed row even though the ticker list is already pre-screened — belt-and-suspenders
5. **P0O-8 invariant fix fully preserved and generalized:** the invariant now checks against `evaluation_price` (today's price for open positions, or the actual historical close on the trade's real exit date for closed trades) instead of always assuming "today" — same 3-layer defense (forced status, pre-emit check, independent post-run `invariant_check()` function)
6. **New independent `invariant_check()` function** runs across ALL buckets after the replay completes and is reported as a top-level `PASS`/`FAIL` in both the JSON and the markdown report — a 4th verification layer beyond what P0O-8 had

## Verification

| Check | Result |
|---|---|
| Compile (`py_compile`) | PASS |
| Forbidden imports | ZERO — only `os, json, sqlite3, time, datetime, pathlib.Path, requests`; `atlas_engine`/`atlas_portfolio` appear only in the docstring |
| Cache fetch | 19/19 symbols — 11 reused from P0O-8 cache (cache hit), 8 newly fetched (XLI, XLC, LRCX, MS, KLIC, IRDM, ALGM, MSM, INTC — 9 new, but LRCX/MS/etc counted individually below) |
| No-lookahead self-test | **PASS** |
| Required-series preflight | **PASS** (19/19) |
| **Independent invariant check (new, runs across all 3 buckets)** | **PASS — zero violations** |
| Exclusions | 1 — a **second, unrelated LRCX row** (`trade_id=75`, status `PENDING_FILL`, no `exit_at`) correctly caught by `EXCLUDED_INSUFFICIENT_HISTORY`; this is NOT the canonical LRCX trade (`trade_id=12`, which replayed successfully) — confirms the exclusion logic is working correctly, not a bug |
| Production DB SHA before/after | Unchanged — `75eebd1...4370b258` |
| File created under `/Users/yasser/scripts` | None |
| Output files | Confined to `/tmp/p0o10/output/` only |

## Results Summary

### Canonical Closed Trades (6) — Combined-Selection Policy

| Ticker | Entry | Eval Price | Policy Exit Triggered? | Rec. Stop Status | Rec. Stop Price |
|---|---|---|---|---|---|
| LRCX | 368.39 | 433.33 | NO | VALID | 370.44 |
| MS | 225.98 | 211.72 | NO | VALID | 208.59 |
| KLIC | 121.34 | 133.76 | NO | VALID | 118.36 |
| IRDM | 53.76 | 51.09 | NO | VALID | 49.46 |
| ALGM | 65.55 | 55.48 | **YES** (2026-06-29 @ 60.31) | POLICY_ALREADY_TRIGGERED | N/A |
| MSM | 125.96 | 121.14 | NO | VALID | 117.36 |

*(Eval Price = EODHD daily close on the trade's actual exit date — a daily-bar approximation of the trade's real intraday exit price, expected to differ slightly; e.g. LRCX actual exit was 433.01, eval price 433.33.)*

### Secondary Bucket: INTC (SELL_CONFIRMATION_PENDING)

INTC's combined-selection policy shows `policy_exit_triggered=YES` (2026-06-29 @ 123.46) — i.e. the technical stop policies would have flagged an exit *before* the real broker-side confirmation exists. Reported only here, never folded into canonical metrics.

### Open-Position Forward-Sim (4) — unchanged from P0O-8, invariant still holds

SYNA and RL show `POLICY_ALREADY_TRIGGERED`; BAC and ABNB show `VALID` with a stop strictly below current price.

### Metrics — 3 Separate Buckets (Never Blended)

| Bucket | Combined-Selection Profit Factor | N |
|---|---|---|
| **Canonical (6 closed trades)** | **2.87** | 6 |
| Canonical + Secondary (7, incl. INTC, exploratory only) | 2.32 | 7 |
| Open-position forward-sim (4, separate bucket) | 0.53 | 4 |

**This is a meaningfully larger and more genuine sample than P0O-8's n=4 forward-sim-only result.** The canonical 6-trade bucket uses true historical bar-by-bar replay against real, broker-confirmed, completed trades — profit factor 2.87 for the combined-selection policy is a real (if still small-sample) backtest result, not a mechanics-validation placeholder. The open-position bucket remains forward-simulation only (as in P0O-7/P0O-8) since those 4 positions haven't exited yet, and is correctly kept in its own separate bucket rather than mixed into the closed-trade backtest number.

**Caveat still applies:** n=6 (canonical) and n=4 (open forward-sim) both remain small samples. This result should inform directional confidence, not be treated as statistically definitive.

## Answers to Structured Fields

- **P0O10_STATUS:** IMPLEMENTATION_COMPLETE (staging-only)
- **files_created:** `/tmp/p0o10/src/atlas_replay_harness.py`, `/tmp/p0o10/db/atlas_copy_p0o10.db`, 19 cache files under `/tmp/p0o10/cache/`, `/tmp/p0o10/output/replay_results_v2.json`, `/tmp/p0o10/output/replay_report_v2.md` — all under `/tmp`, nothing under `/Users/yasser/scripts`
- **compile_result:** PASS
- **cache_symbols_fetched:** 19/19 (SPY, QQQ, VIX.INDX, SOXX, XLY, XLF, XLI, XLC, SYNA, RL, BAC, ABNB, LRCX, MS, KLIC, IRDM, ALGM, MSM, INTC)
- **canonical_closed_trades_count:** 6 (LRCX, MS, KLIC, IRDM, ALGM, MSM)
- **secondary_INTC_included:** YES — separate bucket only, `SELL_CONFIRMATION_PENDING` flagged, excluded from canonical metrics
- **excluded_trades:** AAPL, PBXT, IBXT, TSM (permanently, per P0O-9); plus 1 unrelated pending LRCX row (`trade_id=75`, `PENDING_FILL`, no exit — correctly caught by `EXCLUDED_INSUFFICIENT_HISTORY`, not the canonical LRCX trade)
- **open_forward_sim_count:** 4 (SYNA, RL, BAC, ABNB)
- **no_lookahead_selftest:** PASS
- **required_series_preflight:** PASS (19/19)
- **invariant_violations:** ZERO — verified via the new independent `invariant_check()` function across all 3 buckets, plus manual JSON re-check
- **canonical_metrics_summary:** 6 trades, combined-selection profit factor 2.87, max DD -14.57/share; ALGM is the only trade where the combined policy already triggered historically (SELL_REVIEW-equivalent), all other 5 show a valid recommended stop below the trade's exit-date price
- **secondary_with_INTC_metrics_summary:** 7 trades (6 canonical + INTC), combined-selection profit factor drops to 2.32 — INTC's early technical-trigger and confirmation-pending status pulls the exploratory number down, illustrating exactly why it's kept separate from the canonical figure
- **open_position_forward_sim_summary:** unchanged from P0O-8 — SYNA/RL show `POLICY_ALREADY_TRIGGERED`, BAC/ABNB show `VALID` with stop < current price; combined-selection profit factor 0.53 (small n=4 sample, forward-sim only)
- **output_files:** `/tmp/p0o10/output/replay_report_v2.md`, `/tmp/p0o10/output/replay_results_v2.json`
- **production_paths_touched:** NO
- **protected_files_touched:** NO
- **production changes:** NONE
