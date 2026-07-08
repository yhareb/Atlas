# P0O-6: Replay Harness v1 — Staging Implementation Plan
**Status:** PLANNING ONLY. No code written, no production/staging files created, no DB copied, no network calls made. Builds on P0O-2 through P0O-5. `atlas_engine.py`/`atlas_portfolio.py` not touched, imported, or read beyond what was already confirmed in prior audits. No protected formulas/constants disclosed.

---

## 1. Module Name / Path

- **Module name:** `atlas_replay_harness.py`
- **Staging path (build/test location):** `/tmp/p0o6/src/atlas_replay_harness.py`
- **Eventual production path (NOT touched in this task):** `/Users/yasser/scripts/atlas_replay_harness.py` — net-new file, so no backup/SHA-diff needed at that future step (nothing to overwrite), but staging-first protocol still applies per standing rule: staged → compile-checked → dry-run verified → Prof review → THEN copied to production, never skipped just because it's a new file.
- **No live-path imports:** the module must **not** `import atlas_manage`, `atlas_intraday`, `eod_writer`, `pre_market_report`, or any script that has a Telegram-send or broker-action code path reachable at import time or call time. It may only import: `atlas_db` (for read helpers, if reused) or, more conservatively, open `atlas.db`/its staged copy directly via `sqlite3` without importing `atlas_db.py` at all — TBD at implementation time, leaning toward direct `sqlite3` reads to minimize any accidental live-path coupling.
- **`atlas_engine.py`/`atlas_portfolio.py`:** not imported at all in v1. The replay harness recomputes its own candidate-stop math (Section 7) using only the 6 public-benchmark methods from P0O-2/P0O-3 — it does not need and must not import the protected pillar-scoring modules for this pass.

---

## 2. Copied-DB Input Path

- **Source:** `/Users/yasser/scripts/atlas.db` (canonical production DB — read-only source, never written)
- **Copy destination:** `/tmp/p0o6/db/atlas_copy_p0o6.db`
- **Copy method:** file-level copy (`cp`, or Python `shutil.copy2` for a metadata-preserving copy) taken once at harness-run start; the harness never opens the production DB path directly, only ever the `/tmp` copy.
- **Access mode:** the harness must open the copied DB with SQLite in **read-only mode** (e.g. `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`) as a second layer of protection beyond "it's just a copy" — this makes an accidental write raise an exception immediately rather than silently succeeding against the copy.
- **Tables read:** `trades`, `position_lots` (per P0O-3 Section 7's forward-simulation requirement for the 4 open positions) — no bookkeeping/ledger tables needed for v1 since replay only needs entry/exit price+timestamp per historical trade, not the full double-entry ledger.

---

## 3. Historical Data Cache Path (`/tmp`)

- **Cache root:** `/tmp/p0o6/cache/`
- **Layout:** one JSON or CSV file per symbol, e.g. `/tmp/p0o6/cache/SPY.US.json`, `/tmp/p0o6/cache/SYNA.US.json`, `/tmp/p0o6/cache/SOXX.US.json`, `/tmp/p0o6/cache/VIX.INDX.json`, etc. — flat, one-file-per-symbol, no nested DB needed for v1's data volume (~2,900 rows/symbol × ~10 symbols is trivially small).
- **Fetch-once discipline:** each symbol is fetched from EODHD exactly once per harness run (or reused across runs if the cache file already exists and is fresh enough — freshness check TBD, e.g. re-fetch if cache file older than 1 day), using the existing `atlas_provider_guard.py` rate-limit-aware wrapper pattern confirmed in P0O-4/P0O-5, not a raw unthrottled loop.
- **Symbols to cache for v1** (per task scope): `SPY.US`, `QQQ.US`, `VIX.INDX`, `SOXX.US` and/or `SMH.US` (SYNA proxy), `XLY.US` (RL + ABNB proxy), `XLF.US` (BAC proxy), plus each open-position ticker itself (`SYNA.US`, `RL.US`, `BAC.US`, `ABNB.US`) — 9 symbols total for the 4-position v1 scope. Yield (`US10Y.INDX`) is explicitly **excluded from the fetch list** per task scope (v1 defers it, flags `REGIME_INPUT_PARTIAL` instead of fetching).
- **All cache files live under `/tmp`, never under `/Users/yasser/scripts`** — this keeps the harness's data footprint fully disposable/staging-only until Prof approves promoting the harness itself to production.

---

## 4. No-Lookahead Data Accessor

- **Design:** a single `HistoricalSeries` accessor class/function per symbol, constructed once from the full cached series, exposing only a `.as_of(date_t)` method that returns a slice `[:index_of(date_t)+1]` — i.e. all rows up to and including *t*, never beyond.
- **Structural enforcement:** the replay loop (Section 5) is the *only* caller of `.as_of(t)`; no other code path in the harness may hold a reference to the unsliced full series once replay begins — the full series is wrapped/hidden behind the accessor immediately after cache-load, so a coding mistake elsewhere in the harness cannot accidentally reach into "the whole future" by construction, not just by convention.
- **Applies uniformly** to all 9 cached symbols (Section 3) plus the ticker's own historical trade record (a trade's own future exit price/date must never be visible to the classifier while replaying steps before that exit date — this is the most likely accidental-lookahead bug, since the *outcome* data naturally lives right next to the *entry* data in the `trades` row, so the replay loop must explicitly withhold `exit_price`/`exit_date` from any per-step computation and only reveal them at the actual historical exit step).

---

## 5. Daily Bar Replay Loop

- **Granularity:** daily bars only (confirmed scope from P0O-4/P0O-5 — intraday explicitly deferred).
- **Outer loop:** iterate over historical trades read from the copied DB (Section 2) — for each trade, replay from its entry date to its actual exit date (closed trades) or through "today" (open positions: SYNA/RL/BAC/ABNB, per P0O-3 Section 6's forward-simulation requirement).
- **Inner loop:** for each trading day *t* from entry to exit (or entry to today), in chronological order:
  1. Pull `.as_of(t)` for the ticker, SPY, QQQ, mapped sector proxy, VIX (Section 4).
  2. Check sufficient lookback exists for the longest indicator window (Section 9 validation) — if not, mark this trade `EXCLUDED_INSUFFICIENT_HISTORY` and skip to the next trade (abandon mid-trade, don't partial-compute).
  3. Compute each of the 5 candidate stop values for day *t* (Section 7).
  4. Compute the baseline mechanical stop trajectory for day *t* (Section 6).
  5. Record whether each candidate stop would have triggered an exit on day *t* (candidate stop ≥ day's low, for a long) — if triggered, that candidate's simulated trade closes at day *t*; subsequent days for that candidate are not simulated further for this trade.
  6. Advance to *t+1*.
- **Per-trade output:** for each of the 5 stop policies + the baseline, record simulated exit date/price (or "still open as of today" for the open-position forward-sim case) — this per-trade record set is the direct input to Section 8's metrics.

---

## 6. Baseline Mechanical-Stop Replay

- **Purpose:** establish the "what actually happened" comparison anchor required by every metric in Section 8 (false exits, missed exits, profit factor delta, etc. are all *relative to* this baseline).
- **Source of truth:** the trade's actual recorded `entry_price`, `exit_price`, `entry_date`, `exit_date` from the copied `trades` table — i.e. the mechanical stop-hit logic that already exists live in `atlas_portfolio.py` is **not re-executed or re-derived** here; the harness simply reads its already-recorded historical outcome. This avoids any need to import or re-implement protected exit logic — the baseline is just historical fact, not a re-run computation.
- **Open positions (SYNA/RL/BAC/ABNB):** baseline = "still open, current stop = current mechanical stop as of the copied DB snapshot" (no exit yet) — the forward-simulation comparison for these 4 shows what each candidate policy *would* recommend today vs. what the live mechanical stop currently is, without needing a future outcome to compare against yet.

---

## 7. Candidate Stop-Policy Replay

Per P0O-3 Section 4/5, 5 methods computed at each replay step (Chandelier is the 6th conceptual method from P0O-2 but folds into "technical support" cadence here per task's explicit v1 list — task Section 7 lists 5 concrete items, treated as authoritative for v1 scope):

| Method | v1 implementation approach |
|---|---|
| **ATR stop** | Standard ATR(14) (or configurable window) × multiplier below current price, recomputed daily from `.as_of(t)` |
| **Chandelier stop** | Highest high since entry (tracked incrementally per trade during the inner loop) − ATR(22) × multiplier; trails up only — implemented as a running max, never re-lowers |
| **Technical support placeholder (if data available)** | v1 placeholder: nearest local swing-low over a fixed lookback window (e.g. lowest low of the last N bars) — explicitly flagged as a *placeholder* algorithm, not a fully-featured support/resistance detector; if this placeholder can't be meaningfully computed for a given ticker/window (e.g. insufficient bars), it emits `NO_VALID_STOP` for that method on that day rather than guessing |
| **EMA/MA invalidation stop** | Standard EMA (e.g. 20-EMA) value on day *t*; "stop" = break of this level, using the same `.as_of(t)` slice |
| **Max-loss floor** | Fixed % or $ loss cap from the trade's actual entry price (config parameter, not a live alpha constant) — this is the floor per the P0O-2 selection rule, never overridden by a looser candidate |

**Selection rule reused unchanged from P0O-2 Section 5 / P0O-3 Section 4:** tightest of {ATR, Chandelier, technical-support-placeholder, EMA} → apply macro-tightening if applicable (deferred/simplified in v1 since full regime classifier integration is a later phase) → floor at max-loss. Each of the 5 methods is *also* recorded and metric-scored independently (Section 8), not just the combined selection — so the replay can show which single method performs best/worst, not only the blended result.

---

## 8. Metrics

Computed per stop policy (5 individual methods + 1 combined-selection policy = 6 policies total) across the full replay trade set:

| Metric | Definition |
|---|---|
| **R multiple** | (exit price − entry price) / (entry price − initial stop price), per simulated trade |
| **Profit factor** | Sum of simulated winning trade $ / abs(sum of simulated losing trade $), per policy |
| **Max drawdown** | Largest peak-to-trough equity decline across the simulated trade sequence, per policy (using a simple equal-risk or equal-size assumption for v1 — position-sizing nuance deferred) |
| **Win/loss** | Count and ratio of simulated-profitable vs. simulated-losing trades, per policy |
| **False exits** | Count of trades where a candidate policy's stop would have triggered an exit that the actual baseline outcome (Section 6) shows continued favorably afterward (i.e. the policy exited too early relative to what actually happened) |
| **Missed exits** | Count of trades where the actual baseline outcome shows a loss that a candidate policy's stop would have caught earlier/avoided (i.e. the policy would have protected against a loss the real mechanical stop didn't catch in time) |

All 6 metrics reported **per policy, side-by-side**, plus the same set for the **baseline** (Section 6) as the comparison row — this lets Prof see "would any of these have been better than what actually happened" as a direct table, not an abstract score.

---

## 9. Validation

| Check | Enforcement |
|---|---|
| **No future rows accessible at replay step *t*** | Structural — enforced by the `.as_of(t)` accessor design (Section 4), verified by an explicit unit-style self-test: assert that `.as_of(t)` never returns a row with date > *t*, run against every cached symbol before any real replay executes |
| **All required series present** | Pre-flight check before the outer trade loop starts: confirm all 9 cached symbols (Section 3) loaded successfully with non-empty series; abort the entire run (not just one trade) if a *required*-tier symbol (ticker/SPY/QQQ/sector-proxy/VIX) is missing; optional-tier absence (yield, breadth) is expected in v1 and does not abort — it flags `REGIME_INPUT_PARTIAL` per P0O-4/P0O-5 design |
| **Insufficient-history exclusions logged** | Every trade skipped via `EXCLUDED_INSUFFICIENT_HISTORY` (Section 5, inner-loop step 2) is written to a dedicated exclusions log/report section — Prof must be able to see *which* trades were dropped and why, not just a silently-smaller final metrics table |
| **Output written only to `/tmp` report files** | All output — per-trade simulation detail, the metrics table (Section 8), the exclusions log — is written exclusively under `/tmp/p0o6/output/` (e.g. `replay_report_v1.md` or `.json`); the harness has **zero write path** to `/Users/yasser/scripts/atlasops_reports/`, `atlas.db`, or any production location in this v1 pass; promotion of the harness itself to a production-runnable tool is a separate, later, explicitly-approved step |

---

## Answers to Structured Fields

- **P0O6_STATUS:** PLAN_COMPLETE — staging implementation plan only, zero code written, zero files created, zero network calls made
- **proposed_files:** `/tmp/p0o6/src/atlas_replay_harness.py` (net-new module); production destination `/Users/yasser/scripts/atlas_replay_harness.py` NOT touched in this task
- **replay_inputs:** Ticker OHLCV + SPY + QQQ + mapped sector ETF (SOXX/SMH for SYNA, XLY for RL/ABNB, XLF for BAC) + VIX.INDX + historical `trades`/`position_lots` from a copied DB; breadth excluded entirely; yield excluded for v1 with `REGIME_INPUT_PARTIAL` flagged instead of fetched
- **data_cache_plan:** `/tmp/p0o6/cache/`, one file per symbol (9 symbols total), fetched once via the existing `atlas_provider_guard.py` rate-limit-aware pattern, never written under `/Users/yasser/scripts`
- **no_lookahead_design:** `.as_of(t)` accessor per symbol returning only rows ≤ t, constructed once and used exclusively by the replay loop; trade outcome fields (`exit_price`/`exit_date`) explicitly withheld from per-step computation until the actual historical exit step
- **replay_loop_design:** Outer loop over historical trades (closed + the 4 open positions for forward-sim), inner daily-bar loop per trade computing all 5 candidate stops + baseline, recording first-trigger exit per policy
- **stop_policy_design:** ATR, Chandelier (running max-high trail), technical-support placeholder (local swing-low, explicit `NO_VALID_STOP` if uncomputable), EMA/MA invalidation, max-loss floor — combined-selection rule reused unchanged from P0O-2/P0O-3, each method also scored independently
- **metrics_plan:** R-multiple, profit factor, max drawdown, win/loss, false exits, missed exits — computed per policy (5 individual + 1 combined = 6) plus the baseline row for direct side-by-side comparison
- **validation_plan:** structural no-lookahead self-test, required-series pre-flight abort, insufficient-history exclusion logging, `/tmp`-only output — zero production write path in v1
- **implementation_risk:** LOW-MEDIUM — data availability and schema design are already validated (P0O-4/P0O-5); main residual risk is the technical-support placeholder's simplicity (may need refinement post-v1) and max-drawdown's equal-size assumption (real position sizing varied historically, deferred deliberately for v1 simplicity)
- **approval_required:** YES — no implementation should begin until Prof authorizes moving from this plan to actual staged code
- **production changes:** NONE
