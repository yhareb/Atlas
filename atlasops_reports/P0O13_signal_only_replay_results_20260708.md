# P0O-13: Signal-Only FILLED Pullback Replay — Results

**Status:** STAGING-ONLY. Built on the P0O-10/P0O-11 replay engine. All work under `/tmp/p0o13/`; production untouched.

---

## Headline Finding: Signal-Only Candidates Perform MUCH Worse Than Canonical Trades — Profit Factor 0.05 vs. 2.87

Adding the new SIGNAL_ONLY_FILLED_PULLBACK bucket (14 candidates, sourced strictly from `pending_pullbacks.status='FILLED'`) produced a **profit factor of 0.05** — catastrophically worse than the canonical broker-confirmed bucket's 2.87. Blending them into the "combined exploratory" bucket drags the number down to **0.39**. This is a real, market-data-driven result (verified below, not a bug) with an important interpretation: **the tickers Atlas's own logic armed at a 3/4-pillar tier but that were never actually taken as real trades performed far worse than the 6 trades that WERE taken.** This could mean several things worth flagging to Prof rather than concluding definitively:
- Real trade selection (whatever combination of pillar tier + catalyst + Prof's own judgment led to an actual broker trade) may be doing meaningful additional filtering beyond the raw pillar-armed trigger
- The signal-only bucket's stop-policy simulation exits later/differently than whatever real discipline would have applied to these tickers had they been traded
- Small-sample noise remains a factor (n=14, walk-forward split further thins each half to n=7)

**This is exactly the kind of exploratory-bucket result that should stay clearly separated from canonical metrics** (which it does, per design) — it's a data point for Prof's judgment, not evidence that Atlas's signal generation itself is broken.

## What Was Built

`/tmp/p0o13/src/atlas_replay_signal_only.py` — new module, reusing the P0O-10/P0O-11 replay math verbatim (identical ATR/Chandelier/swing-low/EMA/max-loss/combined-selection formulas) plus:

1. **New `SIGNAL_ONLY_FILLED_PULLBACK` bucket loader** — reads `pending_pullbacks` where `status='FILLED'`, uses `trigger_price` as the synthetic entry (Atlas's own already-computed value, never fabricated), forward-simulates like an open position since no real exit exists
2. **Overlap exclusion:** any FILLED pullback ticker already tracked as a real trade/position elsewhere (LRCX, MS, KLIC, IRDM, ALGM, MSM, INTC, SYNA, RL, BAC, ABNB) or already excluded per P0O-9 (TSM) is excluded from this bucket to avoid double-counting the same real-world event under two identities
3. **5 separate buckets, 5 separate metrics runs** — canonical, signal-only, combined-exploratory, secondary INTC, open-position forward-sim
4. **Winner-concentration check** — formalized 40% threshold, flags `NOT-YET-TRUSTED` when exceeded
5. **Leave-one-out** on both signal-only and combined buckets
6. **Walk-forward chronological split** (entry-date-sorted, first half = train, second half = test) on both signal-only and combined buckets
7. **Per-sector profit-factor breakdown** for canonical and combined buckets

## Verification

| Check | Result |
|---|---|
| Compile (`py_compile`) | PASS |
| Forbidden imports | ZERO (`atlas_engine`/`atlas_portfolio` appear only in the docstring) |
| Cache fetch | 36/36 symbols (17 reused from P0O-11, 19 newly fetched) |
| No-lookahead self-test | PASS |
| Required-series preflight | PASS |
| **Invariant check** | **PASS — zero violations** across all buckets |
| Production DB SHA before/after | Unchanged — `75eebd1...4370b258` |
| File created under `/Users/yasser/scripts` | None |
| Output files | Confined to `/tmp/p0o13/output/` only |
| Signal-only candidate count | 14 (of 22 total FILLED pullbacks; 8 excluded for overlap with tracked real trades) |
| Spot-check of a signal-only loser (CAT) | Confirmed genuine market data — CAT fell from trigger 1009.62 to a real close of 940.12 by 2026-07-07, including an actual gap-down day; not a data artifact |

## Results by Bucket

| Bucket | N | Wins | Losses | Profit Factor | Max DD/share | Avg R |
|---|---|---|---|---|---|---|
| **1. Canonical (broker-confirmed)** | 6 | 2 | 4 | **2.87** | -14.57 | 0.234 |
| **2. Signal-Only (exploratory)** | 14 | 5 | 9 | **0.05** | -186.44 | -0.503 |
| **3. Combined (exploratory)** | 20 | 7 | 13 | **0.39** | -200.30 | -0.272 |
| 4. Secondary INTC | 1 | 0 | 1 | 0.00 | -6.32 | -1.000 |
| 5. Open forward-sim | 4 | 2 | 2 | 0.53 | -15.97 | 2.647 |

## Winner Concentration

| Bucket | Top Contributor | % of Gross Win | Flag |
|---|---|---|---|
| Canonical | LRCX | 83.9% | **NOT-YET-TRUSTED** (unchanged from P0O-11) |
| Signal-only | ELVN | 30.1% | Passes (no single trade >40%) |
| Combined | LRCX | 74.7% | **NOT-YET-TRUSTED** |

The signal-only bucket's winners are more evenly distributed (ELVN 30.1%, KO 29.7%, EVC 20.0%) — but that's cold comfort given the bucket's overall profit factor is 0.05; even distribution of a small win doesn't offset a much larger, broadly-distributed set of losses.

## Leave-One-Out

**Signal-only bucket:** removing any single ticker barely moves the result (0.03–0.08 range) — this confirms the poor performance is **broad-based across the bucket, not one bad trade** (the opposite problem from the canonical bucket's LRCX-concentration issue).

**Combined bucket:** removing LRCX (the canonical bucket's dominant winner) drops profit factor from 0.39 to 0.10 — showing LRCX is still propping up the combined number even diluted across 20 trades.

## Walk-Forward Split

| Bucket | Train (earlier half) PF | Test (later half) PF |
|---|---|---|
| Signal-only | 0.06 (N=7, 2026-06-28→07-01) | 0.04 (N=7, 2026-07-02→07-07) |
| Combined | 0.67 (N=10, 2026-06-24→07-01) | 0.07 (N=10, 2026-07-01→07-07) |

The signal-only bucket is poor in **both** halves — not a case of "good early, bad late" degradation, but consistently weak throughout the ~2-week window sampled. The combined bucket's train/test gap (0.67→0.07) is heavily influenced by LRCX and the canonical trades landing mostly in the train half by date.

## Per-Sector Breakdown (Canonical Bucket)

| Sector | N | Profit Factor |
|---|---|---|
| SOXX (semis) | 3 | 14.75 |
| XLF, XLC, XLI | 1 each | 0.00 |

Semis alone drive the canonical bucket's strong headline — consistent with the LRCX/KLIC concentration already flagged.

## Answers to Structured Fields

- **P0O13_STATUS:** IMPLEMENTATION_COMPLETE (staging-only)
- **signal_only_candidates_count:** 14
- **excluded_pending_pullbacks:** 8 — LRCX, TSM, INTC, BAC, RL, ALGM, KLIC, ABNB (all excluded for overlapping an already-tracked real trade/position; zero WAITING/EXPIRED rows exist among these 8, they were excluded purely for overlap, not status)
- **cache_symbols_fetched:** 36/36 (17 reused from P0O-11 cache, 19 newly fetched: AMD, CAT, ELVN, EVC, GE, INDV, JCI, KLAC, KO, MAS, ONTO, PGEN, TGT, VICR, XBI, XLP, XLV + a few re-verified)
- **canonical_metrics_summary:** N=6, profit factor 2.87 (unchanged from P0O-10/11), max DD -14.57/share
- **signal_only_metrics_summary:** N=14, profit factor **0.05** (catastrophically weak), max DD -186.44/share, 5 wins/9 losses — broad-based underperformance, not concentrated in one trade
- **combined_exploratory_metrics_summary:** N=20, profit factor 0.39 — dragged down by the signal-only bucket despite LRCX's continued strong contribution
- **walk_forward_summary:** Signal-only weak in both halves (0.06 train / 0.04 test) — consistent underperformance, not a degrading-over-time pattern; combined bucket shows a large train/test gap (0.67/0.07) driven by canonical trades' date distribution
- **per_sector_summary:** Canonical bucket's strength is concentrated in SOXX/semis (PF 14.75, N=3); all other sectors in canonical show 0 wins; combined bucket per-sector table available in full report
- **winner_concentration_flags:** Canonical and Combined both **flagged NOT-YET-TRUSTED** (LRCX >40% threshold, unchanged concern from P0O-11); Signal-only bucket passes the concentration check but has no good news to concentrate — its problem is breadth of losses, not one trade
- **leave_one_out_summary:** Signal-only: removing any one ticker keeps PF in a narrow 0.03–0.08 band (broad weakness, no single driver); Combined: removing LRCX drops PF from 0.39 to 0.10 (still LRCX-dependent even at n=20)
- **invariant_violations:** ZERO across all 5 buckets
- **no_lookahead_selftest:** PASS
- **output_files:** `/tmp/p0o13/output/signal_only_report_v1.md`, `/tmp/p0o13/output/signal_only_results_v1.json`
- **production_paths_touched:** NO
- **protected_files_touched:** NO
- **production changes:** NONE

## Bottom Line for Prof

Expanding the sample surfaced a real signal, not a bug: the tickers Atlas's pillar logic armed at 3/4-pillar tier but that were never taken as real trades performed far worse (PF 0.05) than the 6 trades that were actually taken (PF 2.87). This is worth investigating further — it may mean real trade selection has valuable additional filtering beyond the raw pillar trigger, or it may mean the exit simulation for these untraded signals behaves differently than real discipline would have. Either way, this strengthens the case for NOT yet trusting either bucket's number as decision-grade, and suggests the next useful step may be understanding *why* the signal-only bucket underperforms so badly before expanding the sample further.
