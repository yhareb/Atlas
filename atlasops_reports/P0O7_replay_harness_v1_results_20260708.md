# P0O-7: Replay Harness v1 Implementation (Staging-Only) — Results

**Status:** STAGING-ONLY. Module created, executed, and verified entirely under `/tmp/p0o7/`. Zero production files touched, zero production DB writes, zero protected-file imports. Builds on the approved P0O-6 plan with the P0O-7 correction (SOXX for SYNA, no SMH fetch, exactly 10 cache symbols).

---

## What Was Built

**File:** `/tmp/p0o7/src/atlas_replay_harness.py` (~600 lines) — net-new module implementing:
1. Read-only copied-DB access (`sqlite3` URI `mode=ro` against a copy, never the production file)
2. EODHD fetch/cache for exactly the 10 specified symbols, cached under `/tmp/p0o7/cache/`
3. `HistoricalSeries.as_of(t)` — structural no-lookahead accessor (private row list, slice-only access)
4. Daily-bar replay loop with per-policy trigger tracking
5. Baseline outcome read directly from the copied `trades` table (no re-derivation of mechanical stop logic — protects against any need to touch `atlas_portfolio.py`)
6. Open-position forward simulation for SYNA/RL/BAC/ABNB (the only in-scope tickers, all currently OPEN)
7. 5 stop policies (ATR, Chandelier, swing-low placeholder, EMA/MA invalidation, max-loss floor) + 1 combined-selection policy, all public-benchmark math only
8. Metrics: R-multiple, profit factor, max drawdown, win/loss, false exits, missed exits
9. Validation: no-lookahead self-test, required-series preflight, insufficient-history exclusion logging, `/tmp`-only output enforcement

## Verification Performed

| Check | Result |
|---|---|
| Compile (`py_compile`) | PASS |
| Forbidden imports (`atlas_manage`, `atlas_intraday`, `eod_writer`, `pre_market_report`, `atlas_engine`, `atlas_portfolio`) | **ZERO** — only appear in explanatory docstring text, never as actual import statements (confirmed via grep of `^import`/`^from` lines: only `os, json, sqlite3, time, datetime, pathlib.Path, requests`) |
| Production DB SHA before/after run | Unchanged — `75eebd1...4370b258`, identical to the pre-copy baseline |
| File created at `/Users/yasser/scripts/atlas_replay_harness.py` | **None** — confirmed does not exist |
| Copied DB opened read-only | Yes, via `file:...?mode=ro` URI |
| Output file locations | `/tmp/p0o7/output/replay_results_v1.json`, `/tmp/p0o7/output/replay_report_v1.md` — both under `/tmp` only |

## Run Results Summary

- **Cache fetch:** all 10 symbols fetched successfully (SPY/QQQ/SOXX/XLY/XLF/SYNA/RL/BAC 2,893 rows each, VIX.INDX 2,928 rows, ABNB.US 1,397 rows — shorter history reflects ABNB's later IPO date, correctly reflected rather than padded/faked).
- **Preflight:** PASS — all 10 required series present and non-empty.
- **No-lookahead self-test:** PASS — spot-checked 4 checkpoints per symbol across all 10 series, zero violations.
- **Replay trades:** 4 (the 4 open positions — no closed-trade history exists for these specific tickers in the current book, so this run is open-position forward-simulation only, exactly as scoped for v1).
- **Exclusions:** 0 — all 4 positions had sufficient pre-entry lookback history.

### Per-Position Snapshot (Combined-Selection Policy)

| Ticker | Entry | Current | Live Baseline Stop | Combined Recommended Stop | Triggered? |
|---|---|---|---|---|---|
| SYNA | 126.44 | 119.37 | 113.35 | 120.36 | **YES @ 120.36** |
| RL | 405.34 | 395.31 | 387.56 | 395.45 | **YES @ 395.45** |
| BAC | 57.10 | 59.86 | 57.11 | 57.27 | NO |
| ABNB | 143.03 | 148.80 | 135.96 | 142.45 | NO |

This is the first concrete output of the macro-conditioned decision engine design (P0O-2 through P0O-6) — **advisory only, zero live effect**. It shows the combined-selection stop policy would have flagged SYNA and RL as SELL_REVIEW-tier today, tighter than their current live mechanical stops, while BAC and ABNB remain comfortably inside their combined-selection stop level.

### Metrics by Policy (n=4, sample-size caveat applies — see note below)

| Policy | Wins | Losses | Profit Factor | Max DD/share |
|---|---|---|---|---|
| ATR | 2 | 2 | 0.50 | -17.10 |
| CHANDELIER | 2 | 2 | 0.50 | -17.10 |
| SWING_LOW_PLACEHOLDER | 2 | 2 | 0.53 | -16.11 |
| EMA_INVALIDATION | 2 | 2 | 0.50 | -16.96 |
| MAX_LOSS_FLOOR | 2 | 2 | 0.42 | -20.15 |
| COMBINED_SELECTION | 2 | 2 | 0.53 | -15.97 |

Full detail (including per-trade R-multiples) is in `/tmp/p0o7/output/replay_results_v1.json`.

**Critical caveat (stated plainly, not glossed over):** n=4 is far too small a sample to draw any real conclusion about which stop policy is "better." This run validates that the **harness mechanics work correctly** (fetch, no-lookahead, policy computation, metrics, exclusion handling) — it is not yet a meaningful backtest, because there is no closed-trade history for these 4 tickers in the current book. A real validation pass requires either (a) running the harness against the 11 closed trades that exist for *other* tickers (AAPL, ALGM, IBXT, INTC, IRDM, KLIC, LRCX, MS, MSM, PBXT, TSM) — which would require expanding the cache-symbol/sector-mapping list beyond the 4 tickers this v1 pass was scoped to — or (b) waiting for real history to accumulate on the current 4 open positions.

## Answers to Structured Fields

- **P0O7_STATUS:** IMPLEMENTATION_COMPLETE (staging-only, harness built + run successfully)
- **files_created:** `/tmp/p0o7/src/atlas_replay_harness.py`, `/tmp/p0o7/db/atlas_copy_p0o7.db`, `/tmp/p0o7/cache/{SPY,QQQ,VIX,SOXX,XLY,XLF,SYNA,RL,BAC,ABNB}.{US,INDX}.json` (10 files), `/tmp/p0o7/output/replay_results_v1.json`, `/tmp/p0o7/output/replay_report_v1.md` — all under `/tmp`, nothing under `/Users/yasser/scripts`
- **compile_result:** PASS (`py_compile` clean)
- **cache_symbols_fetched:** 10/10 — SPY.US, QQQ.US, VIX.INDX, SOXX.US, XLY.US, XLF.US, SYNA.US, RL.US, BAC.US, ABNB.US
- **replay_trades_count:** 4 (open-position forward-simulation only; no closed-trade history exists for these tickers)
- **exclusions_count:** 0
- **no_lookahead_selftest:** PASS (zero violations across all 10 series, 4 checkpoints each)
- **required_series_preflight:** PASS (10/10 required series present and non-empty)
- **metrics_summary:** 6 policies computed (ATR, Chandelier, swing-low placeholder, EMA invalidation, max-loss floor, combined-selection); profit factor range 0.42–0.53, all n=4 — **sample size too small for a real conclusion, this run validates mechanics only**
- **open_position_forward_sim_summary:** SYNA and RL show combined-selection stop triggered today (tighter than live baseline stop); BAC and ABNB do not trigger
- **output_files:** `/tmp/p0o7/output/replay_report_v1.md`, `/tmp/p0o7/output/replay_results_v1.json`
- **production_paths_touched:** NO
- **protected_files_touched:** NO
- **production changes:** NONE
