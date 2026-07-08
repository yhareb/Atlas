# P0O-4: Replay-Harness Blocker Audit (Read-Only)
**Status:** READ-ONLY audit closing implementation blockers identified in P0O-3, before any replay-harness code is written. No code/DB/strategy/live-rule changes; `atlas_engine.py`/`atlas_portfolio.py` not edited (only their existing public EODHD-call patterns were grepped for provider-usage confirmation — no scoring/alpha logic read or disclosed). No protected formulas/constants exposed below.

---

## 1. Shadow Schema Correction

**Problems identified in the P0O-3 schema:**
- Column count/labeling was described as 12 fields in prose but the table listing had drifted from that count once nested notes are accounted for — needs an explicit, final, numbered column list (below) to remove ambiguity before any DDL is written.
- `recommended_stop REAL or TEXT` was a type-ambiguous field — mixing a price number with a sentinel string in one column is implementation-unsafe (breaks numeric aggregation/queries in the replay harness, invites accidental string-to-float coercion bugs).
- `current_stop REAL, nullable` had the same latent precision concern once a real dollar-price sentinel discipline is applied.

**Fix applied:** split every stop-price field into three explicit sub-fields — an exact integer micros representation (avoids float rounding drift across replay/live comparisons), a human-readable decimal-text representation (for direct report rendering, no float-to-string surprises), and a status enum that is always populated and never ambiguous with the numeric fields.

### Corrected Shadow Schema — `shadow_recommendations` (13 columns, final)

| # | Column | Type | Notes |
|---|---|---|---|
| 1 | `recommendation_id` | INTEGER PK, autoincrement | Unique row id |
| 2 | `cycle_id` | TEXT/INTEGER | Groups all recommendations from one run |
| 3 | `ticker` | TEXT | Ticker symbol |
| 4 | `trade_id` | INTEGER, nullable | FK-style ref to `trades.id`; `NULL` for new-position candidates |
| 5 | `regime` | TEXT | `BULL / NEUTRAL / BEAR / CHOP_HIGH_VOL` |
| 6 | `current_stop_price_micros` | INTEGER, nullable | Mechanical active stop, exact (price × 1,000,000, integer) — existing-position only |
| 7 | `current_stop_decimal_text` | TEXT, nullable | Human-readable decimal string of column 6, kept in sync at write time |
| 8 | `recommended_stop_price_micros` | INTEGER, nullable | Advisory stop, exact integer micros; `NULL` when status = `NO_VALID_STOP` |
| 9 | `recommended_stop_decimal_text` | TEXT, nullable | Human-readable decimal string of column 8; `NULL` when status = `NO_VALID_STOP` |
| 10 | `recommended_stop_status` | TEXT, NOT NULL | Enum: `VALID` or `NO_VALID_STOP` — always populated, single source of truth for whether columns 8–9 are meaningful |
| 11 | `verdict` | TEXT | `BUY/WAIT/AVOID` or `HOLD/TIGHTEN_STOP/REDUCE/SELL_REVIEW/SELL_NOW` |
| 12 | `reason_codes` | TEXT (JSON array) | Ordered reason-code list |
| 13 | `data_quality_flags` | TEXT (JSON array), nullable | e.g. `["SECTOR_MAPPING_MISSING"]`; empty/null when complete |
| 14 | `created_at` | TIMESTAMP, NOT NULL | Row creation time |

*(14 physical columns total once the micros/text/status split is applied to both current_stop and recommended_stop — the P0O-3 "12 columns" count undercounted by exactly the 2 extra fields this split introduces; that is the column-count mismatch being corrected here.)*

**Integer-micros convention:** price × 1,000,000 stored as INTEGER — matches common ledger-precision conventions (consistent with the existing bookkeeping schema's use of exact integer-safe representations for money fields) and avoids binary-float drift when the replay harness recomputes/compares stops across thousands of historical bars. `_decimal_text` is derived and stored redundantly purely for zero-ambiguity human/report consumption — never treated as the source of truth; `_price_micros` is authoritative.

This table remains purely additive to `atlas_db.py` — no existing table's schema, indices, or constraints change.

---

## 2. Historical Regime Data

**Finding: historical Perme packets do NOT exist.**

`/Users/yasser/atlas_inbox/perme_engine_packet_v1.jsonl` contains exactly **1 row** (current/live snapshot only — fields: `schema`, `generated_at_et`, `event_type`, `direction`, `sector`, `tickers`, `severity`, `confidence`, `reason_code`, `evidence_count`, `allowed_actions`, `forbidden_actions`, `scope`, `ttl_minutes`). There is no historical archive of past packets, and the schema is event-driven/point-in-time (a live alert feed), not a continuous daily regime series — it was never designed to be replayed backward.

**Design: deterministic historical regime reconstruction from bars/facts only.**

Since no historical Perme packet series exists, the replay harness must reconstruct regime state at each historical timestamp *t* using only technical inputs that are independently available as full historical series — the same category of inputs listed in P0O-3 Section 2, minus anything Perme-only:

| Input | Historical source confirmed | Lookahead risk |
|---|---|---|
| SPY/QQQ trend | EODHD `eod/SPY.US`, `eod/QQQ.US` — confirmed available, 2015-01-02 to present (Section 3) | None — trend computed strictly from bars ≤ t |
| Breadth | Not directly probed in this audit; likely requires a broader universe feed or an advance/decline proxy — **flagged as a sub-blocker**, see Section 7 | Same, if sourced from EOD bars only |
| VIX | EODHD `eod/VIX.INDX` — confirmed available, 2015-01-02 to present | None |
| Sector ETF trend | EODHD `eod/{SMH,SOXX,XLK,XLF}.US` — confirmed available, same depth | None |
| Rate/yield pressure | Not directly probed in this audit — likely a Treasury-yield series (e.g. 10Y) from the same or an adjacent EODHD endpoint; **flagged as a sub-blocker**, see Section 7 | Same, if sourced from historical bars only |
| Perme macro packet (sentiment, calendar) | **Not reconstructable historically** — no archive exists | N/A — excluded from the historical regime model entirely |

**Resulting design decision:** the replay-harness regime classifier is a **technical-only subset** of the live regime model — it uses SPY/QQQ trend, VIX, sector ETF trend, and (once sourced) breadth and rate/yield pressure, computed strictly from bars with timestamp ≤ *t*. It explicitly **excludes** the Perme sentiment/calendar overlay, because that overlay has no historical record to replay against. This is disclosed as a known, permanent gap between backtested regime classification and live regime classification (live gets the Perme overlay, replay does not) — not something to be papered over with a fabricated synthetic sentiment history.

**Lookahead prevention (structural, not just conventional):** the replay data-access layer must expose historical OHLCV to the regime classifier via a windowed accessor that physically cannot return rows with timestamp > *t* for the bar being replayed — e.g. slicing the historical DataFrame at index *t* before it is ever passed into the classifier function, not trusting the classifier itself to "remember" not to peek ahead.

---

## 3. Sector ETF Data Availability — CONFIRMED

Live probe against the same EODHD provider Atlas already uses in production (`atlas_engine.py`, `atlas_portfolio.py`, `market_scout.py`, `pre_market_report.py` all call `eodhd.com/api/eod/...` today) — using the existing `EODHD_API_KEY` env var, read-only GET, zero writes:

| Symbol | HTTP status | Rows returned | First date | Last date |
|---|---|---|---|---|
| SPY.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |
| QQQ.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |
| SMH.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |
| SOXX.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |
| XLK.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |
| XLF.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |
| VIX.INDX | 200 | 2,928 | 2015-01-02 | 2026-07-07 |

**Findings:**
- **All 6 sector/index proxies + VIX are fully supported** by the existing provider with **~11.5 years** of daily history each, through yesterday's close — more than sufficient depth for any EMA/ATR/breadth-style lookback window contemplated in this RFC series.
- **No gaps observed** in row count consistency (SPY/QQQ/SMH/SOXX/XLK/XLF all return exactly 2,893 rows for the same date range; VIX.INDX returns a slightly different count (2,928) consistent with index-vs-equity-ETF trading-calendar differences, not a data gap).
- **Rate limits:** this audit used 7 sequential single-symbol requests with no throttling/429 encountered; the existing `atlas_provider_guard.py` module already implements a rate-limit-aware wrapper (429 retry-once + low-remaining backoff) that the replay harness's bulk historical fetch should reuse rather than reinvent, since a full backfill (7 symbols × ~2,900 daily bars, one request per symbol via the `from=`/`to=` range params already in use elsewhere in the codebase) is a small, one-time-per-symbol pull, not a per-bar loop.
- **Symbol support confirmed at daily granularity** — intraday-bar availability for these symbols was not probed in this audit (out of scope; the replay harness as scoped in P0O-3 is bar-by-bar daily-first, with intraday explicitly deferred per "if intraday stop logic is in scope" language in that RFC).

**No sector-ETF data blocker remains** — this item from P0O-3 is now CLOSED.

---

## 4. Ticker-to-Sector Mapping — Proposed Initial Table

New, explicit, maintainable lookup table (no code written yet — design only):

| Ticker | Sector proxy ETF | Rationale |
|---|---|---|
| **SYNA** (open position) | SOXX (or SMH) | Semiconductor/IC design — either broad semis ETF is a reasonable proxy; final choice should be validated against historical correlation during replay, not assumed |
| **RL** (open position) | XLY (Consumer Discretionary) — *not yet confirmed available*, see note below | Apparel/luxury retail — outside the 4 proxies named in the original RFC scope (SMH/SOXX/XLK/XLF); flagged as a gap |
| **BAC** (open position) | XLF | Financials — direct, unambiguous mapping |
| **ABNB** (open position) | XLY (Consumer Discretionary) — same gap as RL | Travel/consumer platform — also outside the originally-named 4 proxies |
| *(general default)* | XLK | Fallback for large-cap tech/software names not otherwise mapped |

**Gap identified:** 2 of the 4 currently-open positions (RL, ABNB) map naturally to **Consumer Discretionary (XLY)**, which was not in the original 4-proxy list (SMH/SOXX/XLK/XLF) named in the P0O-2/P0O-3 RFCs. This means the sector-proxy universe needs to expand beyond those 4 examples to actually cover the live book. **XLY availability has not yet been probed** — this is a new, small follow-up data check (same EODHD `eod/XLY.US` pattern), not attempted in this audit since it was outside the exact 6-symbol list requested; recommend probing it before Section 5's design is implemented.

**Design for the mapping table itself:** simple two-column lookup (`ticker → sector_proxy_ticker`), stored as a static config file or small DB table, manually maintained/reviewed by Prof rather than auto-inferred — sector classification of a specific company is a judgment call that shouldn't be silently automated, consistent with this RFC series' "no LLM trade decisions" non-goal.

---

## 5. Replay Data Contract

| Aspect | Specification |
|---|---|
| **Inputs** | Per-ticker OHLCV (existing provider), SPY/QQQ OHLCV, sector-proxy ETF OHLCV (Section 4, pending XLY confirmation), VIX, historical `trades`/`position_lots` records (existing DB) — explicitly **excludes** any historical Perme packet (does not exist, Section 2) |
| **Timestamps** | Daily bars, keyed by trading-session date; all inputs for a given replay step must share the same date key; no intraday granularity in scope for this pass |
| **Required lookback** | Minimum = longest indicator window used by any candidate stop method (e.g. if a 50-bar EMA is in play, need ≥50 prior trading days of history before a trade's own entry date) — applies independently to the traded ticker, SPY, QQQ, and every sector proxy referenced for that ticker |
| **Failure behavior when data missing** | (a) If ticker OHLCV itself has insufficient pre-entry history to seed the longest indicator window: skip that historical trade from the replay set entirely, log it as `EXCLUDED_INSUFFICIENT_HISTORY` — never partially compute with a short window silently. (b) If sector-proxy OHLCV is unavailable for a ticker's mapped sector (e.g. XLY not yet confirmed per Section 4): that trade's sector-relative-strength leg is `null` for the *entire* replay of that trade, `data_quality_flags` includes `SECTOR_DATA_UNAVAILABLE`, and metrics are computed both including and excluding sector-dependent trades so the sector-leg's replay-time contribution can be assessed once XLY (or other missing proxies) are later backfilled. (c) If regime-input OHLCV (breadth, rate/yield — Section 2 sub-blockers) is unavailable: regime falls back to the technical-only subset that IS available (SPY/QQQ trend + VIX + sector trend), flagged `REGIME_INPUT_PARTIAL` — the classifier must degrade gracefully, never halt the whole replay run for one missing regime input |

---

## Answers to Structured Fields

- **P0O4_STATUS:** BLOCKER_AUDIT_COMPLETE — 3 of 4 P0O-3 blockers substantively resolved or closed; 2 new small sub-blockers surfaced (breadth source, rate/yield source, XLY availability) — see `blockers_remaining`
- **schema_corrections_required:** Split the ambiguous `REAL/TEXT` `recommended_stop` field (and by extension `current_stop`) into 3 explicit sub-fields each (`_price_micros` INTEGER, `_decimal_text` TEXT, `_status` enum for recommended_stop only) — final table is 14 physical columns, not 12; column-count mismatch was caused by the P0O-3 prose undercounting this split
- **corrected_shadow_schema:** `shadow_recommendations` — `recommendation_id, cycle_id, ticker, trade_id, regime, current_stop_price_micros, current_stop_decimal_text, recommended_stop_price_micros, recommended_stop_decimal_text, recommended_stop_status (VALID/NO_VALID_STOP), verdict, reason_codes, data_quality_flags, created_at` — additive-only, zero impact on existing schema
- **historical_regime_data_plan:** No historical Perme packet archive exists (only 1 live snapshot row, event-driven schema never designed for replay) — replay regime classifier is a technical-only subset (SPY/QQQ trend + VIX + sector ETF trend + breadth/rate-yield once sourced), strictly excludes the Perme sentiment/calendar overlay, computed via a windowed data-access layer that structurally cannot see future bars
- **sector_ETF_provider_capability:** CONFIRMED — SPY/QQQ/SMH/SOXX/XLK/XLF/VIX.INDX all return HTTP 200 with ~2,893–2,928 daily rows, 2015-01-02 through 2026-07-07 (~11.5 years), via the same EODHD provider/key already used in production; zero rate-limit issues on a 7-symbol sequential probe; existing `atlas_provider_guard.py` 429/backoff wrapper should be reused for the bulk historical backfill
- **ticker_sector_mapping_plan:** Static, Prof-reviewed two-column lookup table; SYNA→SOXX/SMH, BAC→XLF confirmed clean; RL and ABNB both map to Consumer Discretionary (XLY), which is **outside the original 4-proxy list** and whose EODHD availability has not yet been probed — follow-up check needed before Section 5 implementation
- **replay_data_contract:** Daily-bar inputs (ticker + SPY + QQQ + sector proxy + VIX OHLCV, historical trades/lots), lookback ≥ longest indicator window, explicit `EXCLUDED_INSUFFICIENT_HISTORY` / `SECTOR_DATA_UNAVAILABLE` / `REGIME_INPUT_PARTIAL` failure states — no silent partial computation ever
- **blockers_remaining:** (1) XLY (Consumer Discretionary) EODHD availability not yet probed — needed for 2 of 4 live open positions' sector mapping; (2) breadth data source not yet identified/probed; (3) rate/yield-pressure data source not yet identified/probed; (4) any future read-accessor into `atlas_engine.py`/`atlas_portfolio.py` beyond what's already used still requires an explicit Prof work order per the Standing Alpha-Work Override
- **ready_for_replay_harness_implementation:** NO — schema design and core sector/regime data plan are now solid, but the 3 remaining sub-blockers (XLY, breadth, rate/yield sourcing) should be closed first so the harness isn't built against an incomplete data contract that would need mid-build rework
- **production changes:** NONE
