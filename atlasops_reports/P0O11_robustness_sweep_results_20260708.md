# P0O-11: Replay Robustness / Parameter Sweep — Results

**Status:** STAGING-ONLY. Built on the P0O-10 replay engine (reused its cache, invariant logic, and bucket design). All work under `/tmp/p0o11/`; production untouched.

## Headline Finding: The Strong P0O-10 Result Is NOT Robust — It's Concentrated in One Trade

**LRCX alone accounts for 83.9% of gross winning PnL** in the canonical 6-trade bucket. Leave-one-out sensitivity confirms this directly: removing LRCX collapses the combined-selection profit factor from **2.87 → 0.46**. Every other single-trade removal keeps profit factor between 2.41 and 6.08 (MS's removal actually *increases* it, since MS was the largest loser). **The P0O-10 "2.87 profit factor" headline is materially dependent on one winning trade, not a broadly-robust edge.** This is exactly the overfitting risk this sweep was designed to surface, and it did.

## What Was Built

`/tmp/p0o11/src/atlas_replay_sweep.py` — reuses the P0O-10 cache (no re-fetch needed) and DB-read pattern; adds:
1. A parameterized `candidate_stops_param()` taking a `params` dict for ATR multiplier, Chandelier multiplier, swing-low window, EMA window, max-loss %
2. A **243-combination grid** (3 values × 5 dimensions), ATR/Chandelier lookback periods (14/22 days) held fixed per task scope
3. `bucket_metrics()` computing profit factor, max drawdown, avg R-multiple, false exits, missed exits per bucket per parameter set, with an `exclude_ticker` option for leave-one-out
4. `invariant_check_for_params()` — re-verifies the long-stop invariant independently for **every one of the 243 parameter combinations**, not just the default
5. Concentration-risk analysis (% of gross winning PnL per trade) and a per-trade contribution table

## Verification

| Check | Result |
|---|---|
| Compile (`py_compile`) | PASS |
| Forbidden imports | ZERO (`atlas_engine`/`atlas_portfolio` appear only in the docstring) |
| No-lookahead self-test | PASS |
| Required-series preflight | PASS |
| **Invariant violations across ALL 243 parameter combinations** | **ZERO** |
| Production DB SHA before/after | Unchanged — `75eebd1...4370b258` |
| File created under `/Users/yasser/scripts` | None |
| Output files | Confined to `/tmp/p0o11/output/` only |

## Top Parameter Sets (Canonical Bucket, Combined-Selection Policy)

| Ranking criterion | Best value | Params (ATR/Chand/SwingLow/EMA/MaxLoss) |
|---|---|---|
| Profit factor | 3.395 (5-way tie) | 2.0 / 2.0 / 10 / 20 / 0.05 (and equivalents) |
| Max drawdown (least negative) | -30.98/share | 2.0-4.0 / 3.0-4.0 / 10 / 10 / 0.12 (5-way tie — worse than baseline, listed for completeness of the "best" ranking methodology) |
| Avg R-multiple | 1.348 | 3.0 / 4.0 / 10 / 30 / 0.12 |
| Fewest false exits | 0 | 2.0 / 2.0 / 10 / 20-30 / 0.05-0.12 |
| Fewest missed exits | 1 (all tested sets have ≥1) | 2.0 / 2.0 / 10 / 10-30 / 0.08-0.12 |

**Important caveat on the "top by profit factor" table:** several parameter sets tie at 3.395 or better — this is a sign of a small, discrete outcome space (n=6 trades means only a handful of distinct trigger/no-trigger combinations are possible), not evidence of a robust optimum. The default params used in P0O-10 (3.0/3.0/20/20/0.08) land at 2.87 — solidly mid-pack, not cherry-picked, which is reassuring about P0O-10's methodology, but the underlying result is still thin.

## Leave-One-Trade-Out Sensitivity (Default Params)

| Excluded | Profit Factor | Δ from baseline (2.87) |
|---|---|---|
| **LRCX** | **0.46** | **-2.41 (catastrophic)** |
| MS | 6.08 | +3.21 |
| KLIC | 2.41 | -0.46 |
| IRDM | 3.18 | +0.31 |
| ALGM | 3.56 | +0.69 |
| MSM | 3.49 | +0.62 |

Only LRCX's removal causes a dramatic swing — everything else moves the number by less than a full point. This single-trade dependency is the core robustness concern.

## Answers to Structured Fields

- **P0O11_STATUS:** SWEEP_COMPLETE — 243-combination robustness sweep executed, concentration risk identified
- **parameter_grid_size:** 243 (3 values × 5 dimensions: ATR multiplier, Chandelier multiplier, swing-low window, EMA window, max-loss %)
- **canonical_best_sets:** Profit factor best = 3.395 (tied across several sets near ATR/Chandelier mult 2.0, swing-low 10, max-loss 0.05); avg R-multiple best = 1.348 (ATR 3.0, Chandelier 4.0, swing-low 10, EMA 30, max-loss 0.12); no single parameter set dominates across all 5 ranking criteria simultaneously
- **leave_one_out_summary:** Removing LRCX collapses profit factor 2.87→0.46 (catastrophic); removing any of the other 5 trades keeps profit factor in the 2.41–6.08 range (MS's removal, the largest loser, actually improves it)
- **concentration_risk:** **HIGH — LRCX alone = 83.9% of gross winning PnL** in the canonical bucket; only 2 of 6 trades are winners at all (LRCX, KLIC), and LRCX dominates even between those two
- **false_exit_missed_exit_summary:** Best parameter sets achieve 0 false exits (tighter ATR/Chandelier multiplier of 2.0); missed exits never reach 0 in this grid (minimum observed = 1), meaning even the most conservative parameter sets still miss at least one loss that a tighter stop would have caught
- **invariant_violations:** ZERO across all 243 parameter combinations — independently re-verified per combo, not just at the default
- **no_lookahead_selftest:** PASS
- **output_files:** `/tmp/p0o11/output/sweep_report_v1.md`, `/tmp/p0o11/output/sweep_results_v1.json`
- **production_paths_touched:** NO
- **protected_files_touched:** NO
- **production changes:** NONE

## Bottom Line for Prof

The combined-selection stop policy is **mechanically sound and invariant-safe across the entire parameter space tested**, but its P0O-10 profit-factor headline (2.87) should **not** be read as a validated edge yet — it depends heavily on one large winning trade (LRCX) that happened to be held for ~6 days through a strong move. With only 6 canonical trades total, this sample is too small to distinguish "the stop policy works" from "we got lucky on one trade." More closed-trade history (as it accumulates) or backtesting against a wider historical ticker universe would be needed before treating this profit factor as decision-grade evidence.
