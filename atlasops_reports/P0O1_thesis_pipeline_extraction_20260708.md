# P0O-1 — READ-ONLY Atlas Assessment Thesis & Fat Engine Pipeline Extraction

**Date:** 2026-07-08
**Scope:** READ-ONLY extraction only. No patches/deploys/DB writes/strategy or config changes. `atlas_engine.py`/`atlas_portfolio.py` never edited — only function/path names, docstrings, and high-level control flow referenced; no scoring/threshold math values exposed.

## 1. Current Assessment Thesis

**Source: `~/.hermes/profiles/atlas/SOUL.md`** (Atlas persona/doctrine) + `atlas_engine.py::analyze_ticker()` (implementation):

> "Atlas is a lean, deterministic, ruthless US equity swing trading scout... evaluates stocks based on a **4-Pillar Tiered Scoring Model**":
> 1. **Trend Stack** — Price > 50SMA > 150SMA > 200SMA
> 2. **Relative Strength** — Price within 10% of its 50-day high
> 3. **Volume** — RVOL above a configured threshold (relative volume above average)
> 4. **Catalyst** — Recent analyst upgrade or news event in the last 3 days

Final score 0/4–4/4, rendered via the "Telegram Card Format" (fixed template: Entry Price, Score, RVOL, 4 pillar lines, Risk Card with ATR/Stop/Max-Loss-per-Share, optional warnings). **"NEVER GUESS OR CALCULATE DATA YOURSELF"** — every ticker must go through `atlas_engine.py`.

This is a **momentum/trend-continuation swing strategy** with a **binary pillar-gate model** (count-based, not weighted-composite) layered with several **secondary, never-blocking overlays**: regime, macro sentiment, macro calendar, sector sweep, catalyst override, and a Perme threshold overlay. The explicit design principle threaded through the code comments is: *primary pillar gate is hard; every macro/regime/sentiment signal is advisory/secondary and either sizes-down or informs, but does not block or override the pillar gate itself.*

## 2. Current TFE / Decision-Ownership Map

There is no single module literally named "TFE" in the codebase — the trade-flow-engine role is split across a fixed pipeline of named modules:

| Owner | Module | Role |
|---|---|---|
| **Perme** | writes `latest_context.json` + `perme_engine_packet_v1.jsonl` to `/Users/yasser/atlas_inbox/` (external process, not in `~/scripts/`) | Produces a macro/sentiment "threshold overlay" (`sentiment`, `ticker_notes`, TTL) and an annotation-only "engine packet" consumed by reports |
| **Atlas (engine)** | `atlas_engine.py` (protected) | Pure per-ticker scoring: 4-pillar checks, regime/macro-sentiment/macro-calendar/fundamentals/catalyst/insider checks, `analyze_ticker()` as the single entry point |
| **Atlas (portfolio/TFE)** | `atlas_portfolio.py` (protected) | The actual decision engine: admission gating, position sizing, all "consider_*" entry variants (buy, pullback, gap-breakout, intraday-breakout, sector-catalyst-peer-breakout), and all exit logic (`evaluate_exit`, `run_exits`) |
| **Orchestrator** | `atlas_manage.py` | Wires engine + portfolio together per run: loads macro sentiment + Perme overlay, runs exits first, checks regime, builds candidate universe (held + pending-pullback + ema-retry + fresh scan), runs parallel pillar checks, then sequentially considers each candidate through portfolio functions |
| **Reports** | `atlas_intraday.py`, `atlas_eod_positions.py`, `eod_writer.py`/`atlas_report_handoff.py`, `pre_market_report.py`, `atlas_macro_premarket.py`, `atlas_macro_postmarket.py` | Pure renderers/notifiers; read `LAST_RUN_SUMMARY`/DB/handoff state and format Telegram messages. No decision logic of their own beyond report-section filtering (e.g. `status='OPEN'` for HOLDING). |
| **Broker/bookkeeping** | `atlas_db.py` (legacy tables) + P0L-series dual-write bookkeeping tables | Legacy `trades`/`cash_ledger`/`account` = source of truth for execution state; new bookkeeping tables (`portfolio_event_journal`, `position_lots`, `ledger_postings`, `valuation_marks`, `report_snapshots`, `invariant_checks`) = telemetry-only shadow ledger, confirmed (P0L series) to have zero write-back influence on trading decisions |

**Ownership boundary is clean:** scoring lives in `atlas_engine.py`, all buy/sell/sizing decisions live in `atlas_portfolio.py`, orchestration/sequencing lives in `atlas_manage.py`, and reports are pure downstream consumers.

## 3. Current New-Position Pipeline (from `atlas_manage.py::run()`)

1. **Candidate discovery** — union of: currently-OPEN tickers (re-evaluated for pending-pullback logic), `pending_pullbacks(status='WAITING')`, `ema_retry_candidates(status='WAITING')`, and a fresh scan universe (via `market_scout`/watchlist/CLI args), minus a static excluded-ticker set (index ETFs, delisted, etc.).
2. **Scoring** — `_run_parallel_pillar_checks()` runs `atlas_engine.analyze_ticker(ticker, regime=entry_regime)` in parallel (8 workers) for every candidate, producing the 4-pillar score + supporting signal fields.
3. **Sequential consideration loop** — for each candidate, in order: `port.evaluate_pending_pullback()` (if it has an active pending-pullback row) → then, if not already handled, one of several `port.consider_*` entry-path functions (plain buy, gap-up breakout, intraday-breakout continuation, sector-catalyst-peer-breakout) depending on which entry-type conditions are met.
4. **BUY / WAIT / AVOID / BLOCK logic** — each `consider_*` function returns a decision dict with an `action` (`BUY`/`WAIT`/`SKIP`/`BLOCK`/`EXPIRE`), gated first by `port.check_admission()` (pure allow/deny — position caps, sector caps, duplicate-ticker check, blocked-ticker list; regime is informational-only here, never a hard block) and then by the entry-specific pillar/price/pullback conditions inside each `consider_*` function.
5. **Entry/stop/target calculation** — happens inside `consider_buy()`/`consider_*` (protected file, sizing math not exposed here); `size_position()`/`size_position_for_risk()` are the two named sizing helper functions; risk-based position sizing takes `(equity, entry, stop[, risk_pct/half])`.
6. **Macro inputs currently USED at this stage:**
   - `check_regime()` — SPY vs 50SMA, informational only, appended to `regime_detail` text seen inside `consider_buy()`'s "WEAK regime → half-size risk" branch.
   - `get_macro_sentiment()` — Perme's `latest_context.json` sentiment (RISK_OFF/CAUTION/NEUTRAL); when RISK_OFF and "active" (non-shadow), appended as `"WEAK MACRO_RISK_OFF"` text into `entry_regime[1]`, which flows into the same half-size-risk branch as regime weakness.
   - `check_macro_context()` — EODHD macro calendar (Fed/CPI-type high-impact days) — informational note only, "cautious sizing, never a block" per its own docstring; not confirmed to actually alter numeric sizing beyond the note (bounded review — did not trace deeper into the protected file).
   - `_load_perme_threshold_overlay()` — Perme's per-ticker `ticker_notes`/global `min_pillars`/`min_rvol` overlay, read but described in `atlas_manage.py` comments as informational (`LAST_RUN_SUMMARY["perme_threshold_overlay"]`) — **not confirmed wired into the actual admission/consider_buy gating logic** in the code paths reviewed; it is computed and logged every run but its consumption inside the protected file was not traced (out of scope for a non-disclosing extraction).

## 4. Current Existing-Position Pipeline (from `atlas_portfolio.py::run_exits()` / `evaluate_exit()`)

1. **`run_exits(dry_run)`** iterates every open lot via `_open_positions()`, computing `regime = check_regime()` once, then calling `evaluate_exit(lot, dry_run, regime)` per lot.
2. **`evaluate_exit()`** docstring: *"Decide whether an open lot should be closed today. Uses the persisted decision stop as the hard stop. Trailing/regime rules may raise the effective stop, but never lower the persisted decision stop."* — confirms a **trailing-stop-only** design: the original decision stop is a floor; only upward stop revision is possible via trailing/regime rules.
3. Actions returned: `HOLD`/`SELL` (with `reason` text) — this maps 1:1 to the "HOLD / SELL / POSITION RISK" review already exposed in the intraday report sections `SELL NOW`, `POSITION RISK ALERT`, `REVIEW NOW`.
4. **Stop-hit logic** — confirmed (via the P0L-17→P0L-23 INTC incident work) to emit a `STOP_HIT_DETECTED` bookkeeping event, and set `trades.status='CLOSED'` with `exit_price`/`exit_at` populated **before** any broker-side confirmation exists — this is a detection-driven closure model, not a broker-confirmation-driven one.
5. **Pending broker confirmation handling** — as of P0M-1/P0M-3 (already deployed), `atlas_db.get_pending_broker_confirmation_trades()` surfaces any `CLOSED` trade with a real `broker_ref` but no `BROKER_SELL_FILLED` journal event / matching cash_ledger credit, in a dedicated report-only section ("⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING"). This is a **report-layer patch**, not a change to the underlying exit-decision or bookkeeping lifecycle — the exit engine itself still closes on detection, independent of broker confirmation.
6. **Macro/sector inputs at exit time:** only `check_regime()` is passed into `evaluate_exit()`. No macro-sentiment (`get_macro_sentiment()`), macro-calendar (`check_macro_context()`), or Perme overlay is passed into the exit path in `run_exits()` as reviewed — **sell-side review currently does not consume the same macro overlays that gate new buys.** No sector-relative-strength function (e.g. a "sector momentum" check analogous to `sector_of()`) was found wired into `evaluate_exit()`.

## 5. Where Macro Regime Currently Affects Behavior

| Effect | Currently wired? | Mechanism |
|---|---|---|
| **New buys** (sizing) | ✅ YES | `regime_detail`/`entry_regime` text passed into `consider_buy()`; WEAK regime or RISK_OFF macro sentiment → half-size risk (per code comments; exact multiplier not exposed here) |
| **Rankings** (candidate ordering/prioritization) | ❌ Not found | No ranking/sort-by-macro-adjusted-score function identified in the reviewed pipeline; candidates are evaluated in discovery order, not macro-re-ranked |
| **Sector suppression** (blocking a whole sector during a sector-specific risk event) | ❌ Not found as a general mechanism | `sector_of()` exists and is used by `check_admission()` for sector position-caps (diversification), and by the "sector catalyst sweep" peer-breakout entry path — but no code path was found that suppresses/blocks a sector based on macro regime or sector-relative weakness |
| **Stop tightening** | ⚠️ Partially — asymmetric | `evaluate_exit()`'s docstring confirms trailing/regime rules can only **raise** (tighten) the stop, never lower it; `check_regime()` is passed into the exit evaluation, suggesting regime can influence trailing-stop tightening, but the mechanism's exact trigger condition and magnitude were not traced (protected file, out of scope) |
| **Sell review** (macro-aware HOLD/SELL decisioning) | ❌ Not found | `run_exits()`/`evaluate_exit()` only receives `regime` (SPY-based), not `macro_sentiment`, `macro_context`, or the Perme overlay — the same macro inputs that inform new-buy sizing are absent from the sell-side review entirely |

## 6. Gaps vs. a Desired CTO-Level Thesis

| Desired capability | Current state | Gap |
|---|---|---|
| **Macro-conditioned recommendations** | Only regime (SPY vs 50SMA) + macro-sentiment (Perme, RISK_OFF/CAUTION/NEUTRAL) feed into buy-side sizing as a binary/tri-state overlay; sell-side has none | No graduated/continuous macro-conditioning; no macro input to sell-side at all; no per-sector macro conditioning |
| **Exact recommended stop numbers surfaced to Prof** | Stop values exist internally (`stop_loss` field, persisted decision stop) and are shown in report cards, but there's no distinct "recommended stop revision" recommendation surfaced separately from the currently-active stop | Reports show the *current* stop; there's no explicit "Atlas recommends moving your stop to $X because Y" advisory distinct from the mechanical trailing-stop that's already applied |
| **Sector-relative strength** | `sector_of()` exists (used for caps/sweep-peer-discovery only); no sector RS/momentum scoring found (e.g. "this sector is underperforming SPY by X% over Y days") | No dedicated sector-relative-strength pillar or overlay; Pillar 2 is single-ticker RS vs. its own 50-day high, not sector-relative |
| **Position re-underwriting** (periodic re-scoring of an already-open position against current pillar/macro conditions, independent of stop-hit) | Not found — `evaluate_exit()` only checks stop/trailing conditions, not "would Atlas still buy this today at 4/4?" | No mechanism re-runs the full pillar scoring against open positions to flag "thesis has weakened, consider trimming" outside of a literal stop breach |
| **Replay/backtest harness** | Not found anywhere in `~/scripts/` — no `backtest.py`, no historical-replay runner, no notion of "run this decision logic against date X's data and compare to what actually happened" | No backtest/replay capability exists at all; all verification work to date (P0K/P0L/P0M/P0N) has been live-system read-only auditing, never historical simulation |

## 7. Files Likely Involved in a Future Redesign

| File | Role in redesign |
|---|---|
| `atlas_engine.py` (protected) | Any new pillar (e.g. sector-RS) or macro-conditioning change to scoring lives here |
| `atlas_portfolio.py` (protected) | Any change to admission gating, sizing formula, exit/trailing-stop logic, or a new "re-underwriting" check lives here |
| `atlas_manage.py` | Orchestration changes — e.g. wiring macro/Perme overlay into the exit path, or adding a ranking/prioritization step, or wiring a backtest mode |
| `atlas_db.py` | Any new persisted field (e.g. "recommended stop" distinct from "active stop", or a re-underwriting flag/table) |
| `atlas_intraday.py` / `atlas_eod_positions.py` / `atlas_report_handoff.py` | Any new advisory section (e.g. "recommended stop revision", "sector weakness flag", "re-underwriting review") surfaced to Prof |
| *(new, does not yet exist)* `atlas_backtest.py` or similar | A replay/backtest harness would be a net-new module, not a modification of an existing one |

## Protected Files Warning

**`atlas_engine.py` and `atlas_portfolio.py` were not opened for line-by-line inspection beyond `grep`-derived function/class name lists and their one-line docstrings** (all reproduced above are the literal, already-non-disclosing docstrings the code ships with — no scoring formulas, thresholds, weights, or numeric constants were read or reproduced). Any actual redesign work touching these files requires either: (a) Prof's direct work order under the Standing Alpha-Work Override, or (b) a bounded excerpt request under the Explicit Limited Source View Override, per the standing AtlasOps mandate.

---

## Return Fields

- **P0O1_STATUS:** EXTRACTION_COMPLETE
- **current_assessment_thesis:** 4-Pillar Tiered Scoring Model (Trend Stack, Relative Strength, Volume/RVOL, Catalyst) — binary pillar-gate momentum/swing strategy, 0/4–4/4 score, fixed Telegram card output; all macro/regime/sentiment inputs are explicitly secondary/advisory, never a hard block on the pillar gate itself
- **current_TFE_pipeline_map:** Perme (external macro/sentiment context + annotation packet) → `atlas_engine.py` (per-ticker scoring, `analyze_ticker()`) → `atlas_portfolio.py` (admission/sizing/entry-variant/exit decisions) → `atlas_manage.py` (orchestration: exits-first, regime gate, candidate discovery, parallel scoring, sequential consideration) → reports (pure renderers) → `atlas_db.py` legacy tables (source of truth) + P0L bookkeeping tables (telemetry-only, zero decision influence)
- **current_new_position_logic:** discovery (held + pending-pullback + ema-retry + fresh scan) → parallel pillar scoring → sequential `consider_*` entry-path evaluation (plain buy / pullback / gap-breakout / intraday-breakout / sector-catalyst-peer-breakout) → `check_admission()` pure gate (caps/dupes/blocklist) → sizing via `size_position()`/`size_position_for_risk()`
- **current_existing_position_logic:** `run_exits()` iterates open lots → `evaluate_exit()` per lot using only `regime` as context → persisted decision stop is a floor; trailing/regime rules may only raise it → HOLD/SELL decision; stop-hit closes `trades.status` on detection, independent of broker confirmation; P0M report-layer patch surfaces unconfirmed-broker-sell trades without altering the underlying exit lifecycle
- **current_macro_inputs_used:** `check_regime()` (SPY vs 50SMA, buy-side sizing + exit `regime` param), `get_macro_sentiment()` (Perme RISK_OFF/CAUTION/NEUTRAL, buy-side sizing only), `check_macro_context()` (EODHD macro calendar, buy-side note/cautious-sizing only)
- **current_macro_inputs_ignored:** Perme per-ticker threshold overlay (`_load_perme_threshold_overlay()` — computed/logged every run but not confirmed wired into actual admission/consider_buy gating in the reviewed paths); ALL macro/sentiment/calendar inputs are absent from the entire sell-side (`run_exits()`/`evaluate_exit()`) — only bare SPY regime reaches the exit path; no sector-relative-strength input anywhere
- **current_stop_logic_summary:** persisted decision stop = hard floor, never lowered; trailing/regime rules may raise (tighten) it; stop-hit detection closes the trade immediately (sets `trades.status='CLOSED'`) independent of and prior to broker-side sell confirmation
- **current_recommendation_outputs:** fixed Telegram Card Format (ticker/signal/entry/score/RVOL/4 pillars/ATR/stop/max-loss-per-share/warnings) for new candidates; intraday/EOD report sections (HOLDING, SELL NOW, POSITION RISK ALERT, REVIEW NOW, BUY NOW, TOP PICKS, WAITING FOR DIP, MACRO WATCH, and now SELL TRIGGERED/BROKER CONFIRMATION PENDING) for ongoing state — all descriptive/current-state, no distinct "recommended action" layer separate from the mechanical decision already taken
- **gaps_vs_updated_thesis:** (1) no macro-conditioning on sell-side at all; (2) no distinct "recommended stop" advisory separate from the mechanically-applied trailing stop; (3) no sector-relative-strength pillar/overlay (only single-ticker RS vs. own 50-day high); (4) no position re-underwriting mechanism (open positions aren't re-scored against current pillar/macro conditions absent a literal stop breach); (5) no replay/backtest harness exists anywhere in the codebase
- **files_likely_involved_later:** `atlas_engine.py` (protected — new pillars/macro-conditioning), `atlas_portfolio.py` (protected — sizing/exit/re-underwriting logic), `atlas_manage.py` (orchestration wiring), `atlas_db.py` (new persisted fields), `atlas_intraday.py`/`atlas_eod_positions.py`/`atlas_report_handoff.py` (new advisory report sections), and a net-new `atlas_backtest.py`-style module for replay/backtest (does not currently exist)
- **protected_files_warning:** `atlas_engine.py`/`atlas_portfolio.py` were reviewed only at the function-signature/docstring level via bounded greps — zero scoring formulas, thresholds, weights, or numeric constants were read or exposed. Any actual code change to either file requires Prof's explicit work order (Standing Alpha-Work Override) or a bounded excerpt request (Limited Source View Override) per the standing AtlasOps mandate.
- **production changes:** NONE
