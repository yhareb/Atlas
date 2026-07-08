# P0O-2: Atlas/TFE Macro-Conditioned Decision Engine — RFC
**Status:** READ-ONLY DESIGN DOCUMENT. No code, DB, strategy, TFE, report, routing, scheduler, env, Telegram, stop, target, exit, or risk changes made. `atlas_engine.py`/`atlas_portfolio.py` not edited; no protected alpha formulas or constants disclosed below — only architecture, algorithm *names*, and public benchmark concepts (ATR, Chandelier, IBD loss-control) which are industry-standard public knowledge, not Atlas proprietary logic.

Builds on P0O-1 extraction (current 4-Pillar Tiered Scoring thesis; Perme→TFE→Portfolio→Reports ownership chain; confirmed gaps: no sell-side macro input, no distinct recommended-stop concept, no sector-RS pillar, no re-underwriting, no replay harness).

---

## 1. Updated Assessment Thesis

**Current thesis (baseline):** Atlas is a 4-Pillar Tiered Scoring momentum/swing **scout** — Trend Stack + Relative Strength + Volume/RVOL + Catalyst gate admission; macro/regime data is advisory-only on the buy side and **absent entirely** on the sell side.

**Updated thesis:** Atlas/TFE becomes a **macro-conditioned decision engine** that produces *deterministic, explainable, numeric* recommendations for both new and existing positions, where:

- The 4-pillar technical gate remains the **core edge-detection layer** (unchanged, protected) — this RFC does not propose changing pillar scoring math.
- Every recommendation (new-position or existing-position) is **macro-conditioned**: regime, sector rotation, and portfolio concentration state modulate size, stop tightness, and hold/sell urgency — symmetrically, on both sides of the trade lifecycle (today only the buy side sees macro).
- Every recommendation carries an **exact numeric stop, target, and R:R** derived from a documented, selectable stop algorithm — not just a pillar pass/fail.
- Every existing position is **re-underwritten** on each cycle against current conditions (not just monitored for stop-hit), producing a HOLD/TIGHTEN/REDUCE/SELL_REVIEW/SELL_NOW verdict with a reason code trail.
- All new logic ships in **shadow mode** first — recommendations are logged and rendered in a separate report section, with zero live trading effect — and must clear a replay/backtest gate before promotion to live-affecting status.
- Professor remains the sole live-execution authority; the system's job is to make the *option* it's presenting numerically explicit, not to act on its own judgment.

---

## 2. Decision Ownership (unchanged roles, tightened contract)

| Role | Owns | Does NOT own |
|---|---|---|
| **Perme** | Macro facts, regime classification, sentiment, calendar events, sector rotation signal — published as a versioned packet | Any buy/sell/size/stop decision |
| **TFE** (`atlas_engine.py`) | Deterministic recommendation computation: pillar score + macro adjustment + stop algorithm + reason codes | Execution; report rendering; Telegram |
| **Atlas** (reports/renderers) | Rendering recommendations for human review, including the new SHADOW section | Any decision logic |
| **Professor** | Final approval on every recommendation, UNLESS an already-approved standing stop rule (i.e. an existing hard mechanical stop Prof has explicitly pre-authorized) fires — that path remains automatic as today | — |

This is a **read contract**, not a code change: Perme → packet (facts only) → TFE (recommendation, no action) → Atlas (render, no action) → Prof (approve) → existing broker/bookkeeping path (unchanged, already gated by Prof-approved live/dry-run flags).

---

## 3. New-Position Recommendation Model

**Verdict enum:** `BUY | WAIT | AVOID`

**Per-candidate output fields:**
- `entry` — proposed entry price (existing pillar-gate logic, unchanged)
- `stop` — from Section 5 algorithm
- `target` — R:R-derived (existing target logic + macro adjustment factor, unchanged math, adjustment layer only)
- `rr_ratio` — (target−entry)/(entry−stop)
- `size_tier` — FULL / HALF / QUARTER / SKIP, driven by: pillar score tier (existing) × macro regime multiplier (existing, currently buy-side only) × **new** sector exposure penalty
- `macro_adjustment` — regime state + sentiment + calendar-proximity flag applied to size/stop, with explicit before/after values (not just a hidden multiplier)
- `sector_exposure_check` — penalty (size cut) or hard block if sector already at portfolio concentration cap or sector ETF proxy (SMH/SOXX/XLK/XLF-class) is in confirmed downtrend
- `reason_codes` — ordered list, e.g. `["PILLAR_PASS_TIER1", "REGIME_RISK_ON", "SECTOR_STRONG", "CATALYST_CONFIRMED"]` or `["PILLAR_PASS_TIER2", "REGIME_RISK_OFF", "SIZE_HALVED"]`

**No change to the pillar gate itself** — this model wraps the existing 4-pillar output with an explicit, numeric, macro-and-sector-aware sizing/stop/target layer and a human-readable reason trail.

---

## 4. Existing-Position Re-Underwriting Model

**Verdict enum:** `HOLD | TIGHTEN_STOP | REDUCE | SELL_REVIEW | SELL_NOW`

**Per-position output fields:**
- `current_stop` — the live mechanical stop as recorded today (unchanged source)
- `recommended_stop` — output of Section 5 algorithm, computed fresh every cycle
- `stop_delta` — recommended vs current (informational; this RFC proposes **shadow-only** display, no automatic stop mutation)
- `sector_relative_weakness` — ticker return vs. sector ETF proxy over lookback window (new metric, not present today)
- `macro_risk_flag` — regime deterioration, sentiment reversal, or calendar event proximity since entry
- `portfolio_concentration_flag` — position size vs. total book, sector cluster vs. cap
- `reason_codes` — e.g. `["STOP_STILL_VALID", "SECTOR_WEAKENING", "HOLD"]` or `["MACRO_RISK_OFF", "RECOMMENDED_STOP_ABOVE_CURRENT", "TIGHTEN_STOP"]` or `["SECTOR_BREAKDOWN", "CONCENTRATION_CAP_HIT", "REDUCE"]`

**Critical distinction from today:** today's sell-side path (`run_exits`/`evaluate_exit`) only sees bare SPY regime and a hard mechanical stop-hit check. This model adds a **parallel, non-authoritative re-underwriting pass** — it does not touch or replace the existing mechanical stop-hit close logic. The mechanical stop remains the only thing that can auto-close a position; the re-underwriting verdict is advisory until Prof promotes it out of shadow mode.

---

## 5. Stop Recommendation Algorithm

Six candidate stop methods computed in parallel per position, all standard public technical-analysis benchmarks (no Atlas proprietary constants involved):

| Method | Basis |
|---|---|
| **ATR stop** | Entry/current price − (ATR multiplier × ATR(14)) |
| **Chandelier stop** | Highest high since entry − (ATR multiplier × ATR(22)), trails up only, standard volatility-trail benchmark |
| **Technical support stop** | Nearest confirmed swing-low / prior consolidation floor below current price |
| **EMA/MA invalidation stop** | Break of a defined moving average (e.g. 20/50-EMA) as trend invalidation |
| **Max-loss stop** | Fixed % or $ loss cap from entry (portfolio risk-of-ruin ceiling, IBD-style loss-control benchmark) |
| **Macro-tightened stop** | Any of the above, tightened by a regime-risk-off multiplier |

**Selection rule for `recommended_stop`:** take the **tightest (highest, for a long) of** {ATR stop, Chandelier stop, technical support stop, EMA invalidation stop}, then apply the macro-tightening multiplier if regime is risk-off, then **floor at** the max-loss stop (never recommend a stop looser than the max-loss ceiling). This mirrors IBD-style "cut losses fast, let the tightest valid technical level govern" doctrine while keeping a hard max-loss backstop. The exact multipliers/lookback windows are implementation parameters to be tuned in shadow mode against replay data (Section 9) — not fixed in this RFC.

This selection rule and its multipliers are **new orchestration logic**, not a modification of `atlas_engine.py`/`atlas_portfolio.py` internals — it can be implemented as a new module that only *reads* pillar/position state and existing OHLCV, producing an advisory number alongside, not inside, the protected files.

---

## 6. Data / Tool Requirements

| Requirement | Purpose | Status today |
|---|---|---|
| OHLCV provider (existing) | ATR/EMA/MA/RSI/MACD/RVOL inputs | Already in use for pillar scoring |
| ATR / EMA / MA / RSI / MACD / RVOL calculators | Stop algorithm + re-underwriting metrics | ATR/RVOL likely already computed for pillars; EMA/MA/RSI/MACD availability TBD — verify during implementation, not assumed here |
| Sector ETF proxies (SMH, SOXX, XLK, XLF, etc.) | Sector-relative strength, sector exposure penalty, sector breakdown detection | **Not currently fetched** — new data requirement |
| Perme packet (existing) | Regime, sentiment, calendar, macro facts | Already produced; buy-side consumption confirmed, sell-side consumption is the new integration point |
| Benzinga/catalyst feed (existing) | Catalyst pillar input | Already in use |
| Portfolio/bookkeeping state (existing, `atlas_db.py`) | Concentration checks, current stop, position age/size | Already available via existing tables |

**New dependency:** sector ETF OHLCV fetch (reuse existing provider/pipeline, new tickers only — no new vendor required if current provider covers ETFs).

---

## 7. Output Contract

**Candidate recommendation schema (new-position):**
```json
{
  "ticker": "string",
  "verdict": "BUY|WAIT|AVOID",
  "entry": 0.0,
  "stop": 0.0,
  "target": 0.0,
  "rr_ratio": 0.0,
  "size_tier": "FULL|HALF|QUARTER|SKIP",
  "macro_adjustment": {"regime": "string", "sentiment": "string", "size_multiplier": 0.0, "stop_multiplier": 0.0},
  "sector_exposure_check": {"sector": "string", "proxy": "string", "penalty_applied": true, "block": false},
  "reason_codes": ["string"],
  "confidence": 0.0,
  "requires_prof_approval": true
}
```

**Position recommendation schema (existing-position):**
```json
{
  "ticker": "string",
  "trade_id": 0,
  "verdict": "HOLD|TIGHTEN_STOP|REDUCE|SELL_REVIEW|SELL_NOW",
  "current_stop": 0.0,
  "recommended_stop": 0.0,
  "stop_delta": 0.0,
  "sector_relative_weakness": 0.0,
  "macro_risk_flag": "string|null",
  "portfolio_concentration_flag": "string|null",
  "reason_codes": ["string"],
  "confidence": 0.0,
  "requires_prof_approval": true
}
```

**Reason codes:** short enumerated strings (e.g. `PILLAR_PASS_TIER1`, `REGIME_RISK_OFF`, `SECTOR_BREAKDOWN`, `CONCENTRATION_CAP_HIT`, `STOP_STILL_VALID`, `RECOMMENDED_STOP_ABOVE_CURRENT`, `MAX_LOSS_FLOOR_APPLIED`) — exact taxonomy finalized during implementation, not fixed here.

**`confidence`:** float 0–1, derived from pillar tier + data completeness (e.g. missing sector proxy data lowers confidence) — not a new alpha signal, purely a data-quality/tier indicator.

**`requires_prof_approval`:** always `true` in shadow mode; becomes conditionally `false` only for pre-existing, already-approved mechanical stop-hit closes (unchanged from today) — never for any new macro/sector/re-underwriting verdict without explicit future authorization.

---

## 8. Shadow-Mode Rollout

- **No live stop changes** — `recommended_stop` is logged/rendered only; `current_stop` (the mechanical one) is never overwritten by this system.
- **No live broker action** — verdicts never call any order/execution path.
- **Log recommendations only** — new table or log stream (design TBD, likely a new `shadow_recommendations` table in `atlas_db.py`, additive-only, zero impact on existing tables).
- **Render separate "TFE SHADOW RECOMMENDATIONS" report section** — new, clearly-labeled, additive-only block in existing reports (or a new standalone report), never mixed into the live BUY NOW / HOLDING sections Prof currently acts on.
- **Promotion gate:** no shadow recommendation type becomes live-affecting until (a) it has cleared the replay/backtest validation in Section 9, and (b) Prof explicitly authorizes promotion for that specific recommendation type (e.g. "promote recommended_stop tightening for SELL_REVIEW only").

---

## 9. Replay / Backtest Design

- **Historical trades:** replay against Atlas's own closed-trade history (`trades` table, already 70 rows) plus, where available, extended historical OHLCV for open positions' full lifecycle.
- **Alternative stop policies:** run each of the 6 candidate stop methods (Section 5) and the combined selection rule against the same historical trade set, holding entry/exit-signal timing fixed, varying only the stop.
- **False exits:** count trades where an alternative stop would have closed a position that then continued favorably (opportunity cost).
- **Missed exits:** count trades where an alternative stop would have avoided/reduced a loss that the actual (mechanical) stop did not catch in time.
- **Metrics:** profit factor, max drawdown, win/loss ratio, average R-multiple — computed per stop policy, compared against the actual historical outcome as baseline.
- **Gate for promotion:** a stop policy (or the re-underwriting verdict logic generally) must show a **non-degrading** profit factor and **no worse** max drawdown than baseline on the replay set before Prof considers promoting it out of shadow mode. Exact numeric acceptance thresholds are a Prof decision, not fixed in this RFC.
- **New module required:** no replay/backtest harness exists anywhere in the current codebase (confirmed in P0O-1) — this is 100% new build, isolated from all live paths, reads historical DB/OHLCV only, writes nothing to production tables.

---

## 10. Files Likely Involved Later

| File | Expected role | Constraint |
|---|---|---|
| `atlas_manage.py` | Orchestration hook to call new recommendation module per cycle | Editable, unprotected |
| `atlas_engine.py` | **Protected** — may need a narrow, explicitly Prof-authorized read-only accessor for pillar tier/score if not already exposed; no scoring math changes without a direct work order | Protected — override rules apply |
| `atlas_portfolio.py` | **Protected** — position/stop state is read from here; no changes without a direct work order | Protected — override rules apply |
| `atlas_db.py` | New additive tables for shadow recommendations, sector proxy cache | Editable, additive-only |
| Report renderers (`atlas_intraday.py`, `atlas_eod_positions.py`, `eod_writer.py`, `pre_market_report.py`) | New additive "TFE SHADOW RECOMMENDATIONS" section | Editable, additive-only, staging-first per standing protocol |
| **New replay module** (does not exist yet) | Historical stop-policy backtest, promotion gating | New file, isolated, read-only against live DB |

---

## 11. Explicit Non-Goals

- No LLM makes any trade decision — all recommendation logic is deterministic, rule/formula-based (existing pillar math + documented public stop algorithms), never an LLM judgment call.
- Perme has **no** direct buy/sell authority — it supplies facts only, never a verdict.
- **No automatic stop change** before explicit Prof approval and shadow/replay clearance — the mechanical stop-hit close path is the only thing that may act autonomously, and only because it is already pre-approved and unchanged.
- **No broker automation** beyond what already exists today (dry-run/live flag gating unchanged).

---

## Answers to Structured Fields

- **P0O2_STATUS:** RFC_COMPLETE (design only, nothing implemented)
- **updated_thesis:** 4-pillar technical gate retained as core edge, wrapped with symmetric macro/sector conditioning on BOTH buy and sell sides, explicit numeric stop/target/R:R on every recommendation, existing-position re-underwriting each cycle, shadow-mode-first rollout gated by replay validation
- **recommendation_model:** New-position BUY/WAIT/AVOID with entry/stop/target/RR/size_tier/macro_adjustment/sector_exposure_check/reason_codes; existing-position HOLD/TIGHTEN_STOP/REDUCE/SELL_REVIEW/SELL_NOW with current_stop/recommended_stop/sector_relative_weakness/macro_risk_flag/concentration_flag/reason_codes
- **stop_algorithm:** 6 parallel candidates (ATR, Chandelier, technical support, EMA/MA invalidation, max-loss, macro-tightened); selection = tightest of {ATR, Chandelier, support, EMA} → apply macro-tightening if risk-off → floor at max-loss
- **data_requirements:** Existing OHLCV/ATR/EMA/MA/RSI/MACD/RVOL/Perme packet/Benzinga feed/bookkeeping state, PLUS new sector ETF proxy fetch (SMH/SOXX/XLK/XLF-class)
- **output_contract_summary:** Two JSON schemas (candidate + position recommendation) with reason_codes, confidence, requires_prof_approval=true by default in shadow mode
- **shadow_mode_plan:** Log-only new table, new separate "TFE SHADOW RECOMMENDATIONS" report section, zero live stop/broker effect, promotion requires explicit per-type Prof authorization after replay clearance
- **replay_validation_plan:** New replay module (does not exist today) backtests all 6 stop policies + re-underwriting verdicts against historical trades; measures profit factor/drawdown/win-loss/R-multiple/false-exits/missed-exits vs. baseline; non-degrading result required before promotion
- **files_likely_involved:** `atlas_manage.py`, `atlas_engine.py` (protected), `atlas_portfolio.py` (protected), `atlas_db.py`, report renderers, new replay module (net-new)
- **implementation_risk:** MEDIUM — new sector-proxy data dependency, protected-file read-accessor needs may require explicit Prof work orders under the Standing Alpha-Work Override, replay module is entirely new/unvalidated territory, and shadow-mode discipline must be strictly enforced to avoid any accidental live-path leakage during build
- **production changes:** NONE
