# P0O-3: RFC Hardening — Macro-Conditioned TFE Recommendation Engine
**Status:** READ-ONLY implementation-ready architecture spec. Builds directly on P0O-2. No code/DB/strategy/live-rule changes; `atlas_engine.py`/`atlas_portfolio.py` not touched; no protected alpha formulas/constants disclosed — only public TA benchmarks and new orchestration-layer design.

---

## 1–3. Hardened Regime Model

**Taxonomy (deterministic, 4-state):**

| Regime | Definition intent |
|---|---|
| **BULL** | Broad uptrend confirmed across index + breadth, low-to-normal volatility |
| **NEUTRAL** | Mixed/rangebound signals, no strong directional confirmation either way |
| **BEAR** | Broad downtrend confirmed across index + breadth |
| **CHOP / HIGH-VOL** | Elevated volatility regardless of direction (VIX spike, wide daily ranges, whipsaw) — treated as its own state because it changes *risk*, not direction |

**Inputs (all facts, sourced via Perme packet — TFE never fetches raw macro data itself):**

| Input | Role |
|---|---|
| SPY/QQQ trend (e.g. price vs. multi-EMA stack) | Primary direction signal |
| Breadth (advance/decline, % above 50/200-MA) | Confirms whether trend is broad or narrow/fragile |
| VIX level + rate-of-change | Drives CHOP/HIGH-VOL classification and stop-tightening trigger |
| Sector ETF trend (SMH/SOXX/XLK/XLF-class) | Feeds sector-relative-strength model (Section 5) and sector block/penalty |
| Rate/yield pressure (e.g. 10Y trend, rate-of-change) | Secondary regime confirmation — macro headwind/tailwind flag |
| Perme macro packet (sentiment, calendar proximity) | Overlay flags on top of the technical regime signals above |

**Regime classification is deterministic and rule-based** (e.g. index trend + breadth threshold table), never an LLM judgment — consistent with Non-Goal #1 in P0O-2.

**Regime effect matrix:**

| Regime | BUY/WAIT/AVOID bias | Size tier | ATR multiplier | Stop tightening | SELL_REVIEW urgency | Sector blocks | Cash preference |
|---|---|---|---|---|---|---|---|
| **BULL** | BUY bias for pillar-tier-1/2 passes | Full size eligible | Standard (wider) ATR multiplier | None beyond baseline | Low — routine cadence | None unless sector itself weak | Low cash preference |
| **NEUTRAL** | WAIT bias unless tier-1 pillar pass + strong catalyst | Half size default | Standard | Slight tighten on tier-2/3 passes | Moderate | Penalty (not block) for weak sectors | Moderate |
| **BEAR** | AVOID bias except tier-1 pillar pass with confirmed catalyst | Quarter size or SKIP | Tightened ATR multiplier | Active tighten on all open positions | High — accelerated re-underwriting cadence | Block for sectors confirmed in sector-level downtrend | High cash preference |
| **CHOP/HIGH-VOL** | WAIT bias broadly (noise risk > signal) | Half size max, regardless of pillar tier | Widened ATR multiplier (avoid noise-driven stop-outs) — but see min-distance guard in Section 4 | Only tighten if BEAR-like breadth also confirms | Moderate-high (volatility itself is a risk flag) | Penalty for high-beta sectors | Elevated cash preference |

Exact numeric thresholds (breadth %, VIX levels, ATR multiplier values) are implementation parameters to be set during build and validated in replay (Section 6) — not fixed in this RFC, consistent with P0O-2's stance that stop/size mechanics are new orchestration logic, not protected alpha math.

---

## 4. Implementation-Safe Stop Algorithm Rules

1. **Long-position invariant:** `recommended_stop` MUST be strictly below current price for any long position. If a computed candidate stop is ≥ current price (e.g. stale data, gap-up not yet reflected), that candidate is discarded, not clamped — clamping could silently produce a misleadingly-tight number.
2. **Noise guard — must not tighten inside normal noise:** a new `recommended_stop` may only tighten relative to the *previous cycle's* `recommended_stop` if the proposed move exceeds a minimum meaningful distance (see guard #3 below). Sub-noise-threshold moves are suppressed — the system re-emits the prior `recommended_stop` unchanged rather than chattering every cycle.
3. **Min ATR-distance guard:** `recommended_stop` must be at least `k × ATR` away from current price (k = implementation parameter, tuned in replay). Any candidate stop violating this minimum distance is rejected in favor of the next-tightest valid candidate from Section 5 of P0O-2's 6-method list. This prevents the algorithm from ever recommending a stop so tight that normal intraday noise would trigger it.
4. **Mechanical vs. advisory separation (hard rule, no exception):** the *mechanical active stop* (the one that can actually auto-close a position today, unchanged, lives in `atlas_portfolio.py`/`atlas_db.py`) and the *advisory recommended stop* (this RFC's new output) are **always two distinct fields**, never merged, never auto-synced. `recommended_stop` is written only to the new shadow storage (Section 7); it has zero write-path to the mechanical stop field unless and until Prof explicitly promotes that specific behavior out of shadow mode (per P0O-2 Section 8).
5. **Explicit no-signal state:** if no candidate stop passes both the long-position invariant (#1) and the min-distance guard (#3) — e.g. due to missing/stale OHLCV, ATR undefined (insufficient history), or all candidates collapsing above current price — the algorithm outputs the literal sentinel `recommended_stop: "NO_VALID_STOP"` plus a `data_quality_flag` explaining why, rather than guessing or falling back silently to the mechanical stop. Downstream consumers (report renderer, replay harness) must treat `"NO_VALID_STOP"` as a first-class value, not an error to be swallowed.

---

## 5. Hardened Sector-Relative-Strength Design

**Four relative-strength legs computed per ticker, each independently:**

| Leg | Comparison | Purpose |
|---|---|---|
| Ticker vs. SPY | Ticker return − SPY return, lookback window | Absolute market-relative strength |
| Ticker vs. QQQ | Ticker return − QQQ return, lookback window | Growth/tech-relative strength (relevant for tech-heavy book) |
| Ticker vs. sector ETF | Ticker return − sector-proxy ETF return (e.g. SMH for semis) | Direct peer-group relative strength — the most specific signal |
| Sector ETF vs. SPY | Sector-proxy return − SPY return | Confirms whether the *sector itself* is in/out of favor, independent of the individual ticker — feeds the sector block/penalty logic in Section 3 |

**Sector-ticker mapping:** each ticker requires a defined sector-proxy ETF mapping (e.g. semis → SMH/SOXX, software → XLK, financials → XLF). This mapping is a new, explicit, maintainable lookup table — not inferred.

**Missing sector data behavior (must degrade safely, never silently):**
- If a ticker has **no defined sector-proxy mapping**: `sector_relative_weakness` is emitted as `null`, `data_quality_flags` includes `SECTOR_MAPPING_MISSING`, and Section 3's sector block/penalty logic is skipped for that ticker (no penalty applied blind) — verdict computation falls back to the non-sector-dependent fields only, with `confidence` reduced accordingly.
- If the sector-proxy ETF's OHLCV is **temporarily unavailable** (fetch failure, stale bar): same `null` + `data_quality_flags: ["SECTOR_DATA_STALE"]` treatment — never substitute SPY or QQQ as a silent stand-in for a missing sector-specific comparison, since that would misrepresent the leg as sector-specific when it isn't.
- Both cases reduce `confidence` in the output contract (P0O-2 Section 7) rather than blocking the entire recommendation — a missing sector leg degrades signal quality, it does not invalidate the whole verdict.

---

## 6. Hardened Replay / Backtest Design

- **Bar-by-bar replay:** the harness must step forward one bar (day, or intraday bar if intraday stop logic is in scope) at a time, recomputing all indicators, regime state, and candidate stops using only data available *as of that bar* — never the full historical series at once.
- **No lookahead bias (hard requirement):** at replay step *t*, the harness may only use OHLCV/indicator data with timestamp ≤ *t*. Any regime classification, ATR, EMA, or sector-proxy value computed for step *t* must be verifiably computable from data available at or before *t* — this must be enforced structurally (e.g. the data-access layer physically cannot see future rows), not just by convention, to prevent an easy-to-introduce accidental leak.
- **Historical OHLCV requirements:** sufficient lookback per ticker to seed the longest indicator window in use (e.g. if a 50-EMA is used, need ≥50 bars of pre-trade history before the trade's own entry date) — both for the traded ticker and for SPY/QQQ.
- **Sector ETF historical data:** same OHLCV depth requirement extended to every sector-proxy ETF referenced in Section 5's mapping table — this is a new historical-data pull, not currently sourced anywhere in the pipeline.
- **Parameter sweeps:** the ATR multiplier, min-distance guard constant (k), and regime thresholds (breadth %, VIX levels) must each be swept across a defined grid during replay, with metrics (below) computed per parameter combination — this is how the "implementation parameter" values referenced in Sections 1–4 get empirically chosen rather than guessed.
- **Open-position forward simulation:** for currently-open positions (SYNA/RL/BAC/ABNB as of this RFC), the replay harness must also run a forward simulation from each position's actual entry point to today using the candidate stop policies, to sanity-check what each policy *would have* recommended at every historical cycle for these specific live trades — a direct bridge between backtest and current book, without affecting the live mechanical stop.
- **Metrics (per stop policy / parameter combination):** R-multiple distribution, profit factor, max drawdown, false-exit count (policy would have exited a trade that then continued favorably), missed-exit count (policy would have avoided/reduced a loss the actual mechanical stop didn't catch in time) — computed against the same historical trade set, same entry/exit-signal timing, varying only the stop policy, exactly as scoped in P0O-2 Section 9.

---

## 7. Shadow Recommendation Storage Schema

New, additive-only table (proposed name: `shadow_recommendations`) — write-only from the new recommendation module, read-only from the report renderer and replay harness, zero foreign-key coupling that could affect existing bookkeeping tables:

| Column | Type | Notes |
|---|---|---|
| `recommendation_id` | INTEGER PK, autoincrement | Unique row id |
| `cycle_id` | TEXT/INTEGER | Identifies which run (e.g. timestamp or intraday-tick id) produced this recommendation — enables grouping all recommendations from one pass |
| `ticker` | TEXT | Ticker symbol |
| `trade_id` | INTEGER, nullable | FK-style reference to `trades.id` for existing-position recommendations; `NULL` for new-position candidates that have no trade yet |
| `regime` | TEXT | One of `BULL / NEUTRAL / BEAR / CHOP_HIGH_VOL`, snapshot at recommendation time |
| `current_stop` | REAL, nullable | Mechanical active stop at time of recommendation (existing-position only; `NULL` for new-position candidates) |
| `recommended_stop` | REAL or TEXT | Numeric value, or the literal string `"NO_VALID_STOP"` per Section 4 rule #5 |
| `verdict` | TEXT | One of `BUY/WAIT/AVOID` (new-position) or `HOLD/TIGHTEN_STOP/REDUCE/SELL_REVIEW/SELL_NOW` (existing-position) |
| `reason_codes` | TEXT (JSON array) | Ordered reason-code list, per P0O-2 Section 7 |
| `data_quality_flags` | TEXT (JSON array), nullable | e.g. `["SECTOR_MAPPING_MISSING", "SECTOR_DATA_STALE"]`; empty/null when all data was complete |
| `created_at` | TIMESTAMP | Row creation time |

This schema is purely additive to `atlas_db.py` — no existing table's schema, indices, or constraints change. It is designed to be queryable both by the live report renderer (latest `cycle_id` per ticker) and by the replay harness (full historical `shadow_recommendations` history, once shadow mode has been running long enough to accumulate its own track record).

---

## 8. Implementation Phases (strict order)

1. **Replay harness first** — build and validate the bar-by-bar, no-lookahead backtest engine (Section 6) against existing closed-trade history, before any live-adjacent code exists. This validates the stop-selection *methodology* itself is sound before it ever touches a real cycle.
2. **Sector proxy data second** — wire up sector ETF OHLCV fetch + ticker→sector mapping table (Section 5), and extend the replay harness to consume it, so sector-relative-strength can be backtested alongside the stop policies, not bolted on after the fact.
3. **Shadow recommendation module third** — build the live orchestration module that computes candidate/position recommendations each cycle and writes to `shadow_recommendations` (Section 7). By this phase, the stop algorithm and sector logic have already been replay-validated in phases 1–2, so this module is implementing an already-tested design, not inventing untested logic live.
4. **Report section fourth** — add the additive "TFE SHADOW RECOMMENDATIONS" render block to existing reports (staging-first, per standing protocol), surfacing shadow data for Prof's review. Only at this phase does anything become human-visible.
5. **Live promotion last** — only after (a) sufficient shadow-mode history has accumulated, (b) replay validation shows non-degrading profit factor / drawdown per P0O-2's promotion gate, and (c) Prof explicitly authorizes promotion for a *specific* recommendation type — never a blanket "turn it all live" step.

---

## Answers to Structured Fields

- **P0O3_STATUS:** RFC_HARDENED (implementation-ready architecture spec; still zero code/DB/live changes)
- **hardened_regime_model:** 4-state deterministic taxonomy (BULL/NEUTRAL/BEAR/CHOP-HIGH-VOL), inputs = SPY/QQQ trend + breadth + VIX + sector ETF trend + rate/yield pressure + Perme packet, full effect matrix across BUY/WAIT/AVOID, size tier, ATR multiplier, stop tightening, SELL_REVIEW urgency, sector blocks, cash preference
- **hardened_stop_rules:** 5 hard rules — long-stop-below-price invariant, noise-suppression on chatter, min-ATR-distance guard, strict mechanical/advisory field separation with no auto-sync, explicit `"NO_VALID_STOP"` sentinel instead of silent fallback
- **sector_RS_model:** 4 independent legs (ticker-vs-SPY, ticker-vs-QQQ, ticker-vs-sector-ETF, sector-ETF-vs-SPY) with explicit ticker→sector-proxy mapping table; missing/stale data degrades to `null` + `data_quality_flags` + reduced confidence, never silently substituted
- **replay_harness_requirements:** bar-by-bar stepping, structurally-enforced no-lookahead, full historical OHLCV depth for tickers + SPY/QQQ + sector ETFs, parameter sweeps for ATR multiplier/min-distance/regime thresholds, forward simulation against the 4 currently-open live positions, standard metrics (R-multiple, profit factor, drawdown, false/missed exits)
- **shadow_storage_schema:** new additive `shadow_recommendations` table — 12 columns (recommendation_id, cycle_id, ticker, trade_id, regime, current_stop, recommended_stop, verdict, reason_codes, data_quality_flags, created_at), zero impact on existing schema
- **implementation_phases:** replay harness → sector proxy data → shadow recommendation module → report section → live promotion (strict order, each phase gated on the prior)
- **remaining_blockers:** (1) exact numeric thresholds/multipliers for regime classification and stop guards are undetermined until replay parameter sweeps run — this is expected, not a defect; (2) historical OHLCV depth/availability for sector-proxy ETFs not yet verified against the current data provider; (3) ticker→sector-proxy mapping table does not exist yet and needs to be built/maintained; (4) any read-accessor needed inside `atlas_engine.py`/`atlas_portfolio.py` for pillar tier/current-stop values not already exposed would require an explicit Prof work order under the Standing Alpha-Work Override before implementation can proceed into those files
- **production changes:** NONE
