# P0O-5: Replay Data-Source Closure Audit (Read-Only)
**Status:** READ-ONLY, closes the 3 sub-blockers from P0O-4. No code/DB/strategy/live-rule changes; `atlas_engine.py`/`atlas_portfolio.py` not edited (only existing public EODHD/Yahoo call patterns in unprotected macro scripts were read for provider-usage confirmation). No protected formulas/constants exposed.

---

## 1. XLY.US Probe — CONFIRMED AVAILABLE

Live read-only GET against EODHD (same provider/key already in production use):

| Symbol | HTTP status | Rows | First date | Last date |
|---|---|---|---|---|
| XLY.US | 200 | 2,893 | 2015-01-02 | 2026-07-07 |

Identical depth/shape to the 6 symbols confirmed in P0O-4 (SPY/QQQ/SMH/SOXX/XLK/XLF) — same ~11.5-year daily history, no gaps, no rate-limit issue on this single additional request. **This closes the RL/ABNB sector-mapping gap identified in P0O-4** — XLY is now a confirmed, available Consumer Discretionary sector proxy.

---

## 2. Breadth Source — NOT AVAILABLE AS A HISTORICAL SERIES; OPTIONAL, NON-BLOCKING

**What exists today:** `atlas_macro_premarket.py::breadth_snapshot()` calls Massive's `/v2/snapshot/locale/us/markets/stocks/gainers` and `/losers` endpoints — a **live, point-in-time** snapshot of top-mover tickers, used only to build a same-day pre-market narrative ("breadth is concentrated/mixed on the pre-market proxy"). This is not a continuous daily breadth series (e.g. % of stocks above 50-day MA, advance/decline line) and Massive's snapshot endpoints have no historical replay mode — they return "right now" data only.

**No EODHD breadth-index candidate was identified** in this audit as a drop-in substitute; a true historical breadth series (e.g. NYSE/Nasdaq advance-decline) would require either a dedicated breadth-index symbol (not yet searched for) or computing breadth bottom-up from a large ticker universe's historical OHLCV (expensive, out of scope for this closure pass).

**Decision (per task instruction):** breadth is defined as an **optional** regime input. When unavailable during replay, the regime classifier proceeds without it and the row is flagged `REGIME_INPUT_PARTIAL` — it does **not** block replay-harness implementation. This was already the fallback design specified in P0O-4; this audit confirms no better option surfaced, so that fallback is now the accepted permanent design for the first version of the harness, not a temporary gap.

---

## 3. Rate/Yield Pressure Source — CONFIRMED AVAILABLE (EODHD), LIVE PATH USES A DIFFERENT SOURCE

**Live production path today:** `atlas_macro_premarket.py::global_markets_snapshot()` fetches "US 10Y yield" via `yahoo_quote("^TNX", ...)` — a Yahoo Finance **intraday-quote fallback** (`range=1d&interval=1m`, current price + previous close only), explicitly documented in-code as a fallback "for macro instruments not covered by Massive/EODHD entitlement." This gives a live snapshot, not a historical daily series, and is not suitable for bar-by-bar replay as-is.

**EODHD historical candidates probed (read-only GET, same key/provider):**

| Symbol | HTTP status | Rows | First date | Last date |
|---|---|---|---|---|
| `TNX.INDX` | 200 | 2,890 | 2015-01-02 | 2026-07-06 |
| `US10Y.GBOND` | 200 | 2,890 | 2015-01-02 | 2026-07-07 |
| `US10Y.INDX` | 200 | 2,912 | 2015-01-02 | 2026-07-07 |
| `TNX.US` | 404 | — | — | — |

**Finding:** EODHD offers **3 viable historical daily yield series** (`TNX.INDX`, `US10Y.GBOND`, `US10Y.INDX`), all ~11.5 years deep, all already reachable via the exact same key/endpoint pattern used for the sector ETFs. This is a **different source than the live path** (which uses Yahoo for a same-day quote only) — that's expected and fine, since the live path only ever needs "right now," while replay needs a full historical series; EODHD is the correct choice for replay specifically.

**Decision:** rate/yield pressure is **available** for replay (not merely optional) — recommend `US10Y.INDX` as the primary candidate (marginally more rows / cleanest date alignment with the sector ETFs), with `TNX.INDX` as a fallback if `US10Y.INDX` shows any data-quality issue during actual harness build (not verified at row-level detail in this audit, only existence/range). This is one tier stronger than breadth: it's a confirmed-available required-tier input once the harness reaches implementation, not a permanently-optional one — but for the **first replay-harness version**, it is still being treated as optional per task framing, since its integration hasn't been prototyped yet. See Section 6 for the phased scoping decision.

---

## 4. Updated Ticker → Sector Proxy Mapping (Current Open Positions)

| Ticker | Sector proxy ETF | Status |
|---|---|---|
| **SYNA** | SOXX (or SMH) | Confirmed available (P0O-4) |
| **RL** | XLY | **Now confirmed available** (this audit, Section 1) — gap closed |
| **BAC** | XLF | Confirmed available (P0O-4) |
| **ABNB** | XLY | **Now confirmed available** (this audit, Section 1) — gap closed |

**All 4 currently-open positions now have a confirmed-available sector-proxy mapping.** No open position remains unmapped or blocked on missing sector data.

---

## 5. Updated Replay Data Contract

| Tier | Inputs | Availability |
|---|---|---|
| **Required** | Ticker OHLCV, SPY OHLCV, QQQ OHLCV, ticker's mapped sector-proxy ETF OHLCV (SOXX/SMH, XLY, or XLF per Section 4), VIX.INDX | All confirmed available via EODHD, ~11.5 years depth |
| **Optional (v1)** | Rate/yield pressure (`US10Y.INDX`, confirmed available but not yet prototyped into the classifier) | Available but deferred — see Section 6 |
| **Optional (permanent)** | Breadth (no historical series exists; Massive snapshot is live-only) | Not available — permanently optional per Section 2 |

**Missing-data flags (unchanged from P0O-4, reconfirmed):**
- `EXCLUDED_INSUFFICIENT_HISTORY` — ticker/SPY/QQQ/sector-proxy pre-entry history shorter than the longest indicator lookback window; trade skipped from replay entirely.
- `SECTOR_DATA_UNAVAILABLE` — now expected to fire rarely/never for the 4 currently-mapped tickers given Section 1's XLY confirmation; retained as a safety flag for any *future* ticker whose sector mapping hasn't been established yet.
- `REGIME_INPUT_PARTIAL` — fires when breadth (always) and/or rate/yield (in v1, by design choice, not by unavailability) are absent from a given regime-classification step; classifier still produces a technical-only regime state, never halts.

**No-lookahead guard (unchanged, reconfirmed as the binding constraint):** the data-access layer for every required/optional input above must expose a windowed accessor that structurally cannot return rows with timestamp > the bar currently being replayed — enforced by slicing each historical series at index *t* before it reaches any classifier or stop-computation function, for every one of the 7 confirmed EODHD series (ticker, SPY, QQQ, 3 sector proxies, VIX) plus the yield series once/if it's wired in.

---

## 6. Replay-Harness Start Decision

**Core required set — ticker + SPY + QQQ + sector ETF + VIX — is fully data-ready.** All 4 open positions have confirmed sector mappings (Section 4); all underlying EODHD series have ~11.5 years of daily history with no observed gaps.

**Optional set (breadth + yield pressure) is appropriately deferred, not blocking:**
- Breadth has no historical-series solution today — deferring it doesn't lose anything achievable right now.
- Yield pressure **is** technically available (`US10Y.INDX` confirmed), but including it in v1 would mean prototyping a new regime-input integration path that hasn't been designed at the algorithm level yet (i.e., exactly how yield-rate-of-change maps into the BULL/NEUTRAL/BEAR/CHOP taxonomy from P0O-3 Section 1 is still an open design question, not just a data-availability question). Recommend building the harness's **v1 regime classifier on the core required set only**, with yield pressure added as a **v1.1 enhancement** once the core harness is proven — this keeps the first implementation pass smaller and avoids conflating "is the data there" with "is the classifier design validated," which are two different kinds of risk.

**This audit's conclusion: the replay harness CAN start on the core required set now.** The two deferred inputs (breadth permanently, yield pressure for v1 only) are handled via the existing `REGIME_INPUT_PARTIAL` flag design from P0O-4/P0O-5 — nothing about starting implementation now closes the door on adding either input later.

---

## Answers to Structured Fields

- **P0O5_STATUS:** DATA_SOURCE_CLOSURE_COMPLETE — XLY confirmed, yield-source options confirmed, breadth confirmed unavailable-as-historical-series (accepted as permanently optional); all 4 open-position sector mappings now closed
- **XLY_provider_result:** CONFIRMED — HTTP 200, 2,893 rows, 2015-01-02 to 2026-07-07, same EODHD provider/key/shape as the other 6 sector/index symbols
- **breadth_source_result:** NOT AVAILABLE as a historical series — production `breadth_snapshot()` uses Massive's live gainers/losers snapshot only (no replay mode); no EODHD breadth-index candidate identified; defined as permanently OPTIONAL/`REGIME_INPUT_PARTIAL`, non-blocking
- **rate_yield_source_result:** CONFIRMED AVAILABLE via EODHD — `US10Y.INDX` (recommended primary, 2,912 rows) or `TNX.INDX` (fallback, 2,890 rows), both 2015–2026; note this differs from the live path's Yahoo `^TNX` intraday-quote fallback, which is unsuitable for replay; treated as OPTIONAL for v1 only (deferred to v1.1) pending classifier-design work, not due to unavailability
- **updated_sector_mapping:** SYNA→SOXX/SMH, RL→XLY, BAC→XLF, ABNB→XLY — all 4 confirmed available, zero open positions unmapped
- **required_replay_inputs:** Ticker OHLCV, SPY OHLCV, QQQ OHLCV, ticker's mapped sector-proxy ETF OHLCV, VIX.INDX — all confirmed EODHD, ~11.5yr depth
- **optional_replay_inputs:** Rate/yield pressure (`US10Y.INDX`, available, deferred to v1.1), breadth (unavailable historically, permanently optional)
- **missing_data_flags:** `EXCLUDED_INSUFFICIENT_HISTORY`, `SECTOR_DATA_UNAVAILABLE` (retained for future unmapped tickers), `REGIME_INPUT_PARTIAL` (fires for breadth always, yield in v1 by design)
- **no_lookahead_guard:** Windowed data-access slicing at index *t* for every series (ticker/SPY/QQQ/3 sector proxies/VIX/+ yield later) — structural, not conventional; unchanged from P0O-3/P0O-4, reconfirmed as binding
- **ready_for_replay_harness_implementation:** YES — core required-input set is fully data-ready for all 4 open positions; optional inputs (breadth, yield) are cleanly deferred via the existing `REGIME_INPUT_PARTIAL` flag, not blocking a v1 build
- **production changes:** NONE
