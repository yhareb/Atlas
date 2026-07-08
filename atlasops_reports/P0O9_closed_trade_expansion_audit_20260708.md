# P0O-9: Closed-Trade Replay Expansion Audit (Read-Only)

**Status:** READ-ONLY audit. No code/DB/production changes. `atlas_engine.py`/`atlas_portfolio.py` not touched. Live production `atlas.db` queried read-only (same file already read in prior tasks, standard SELECT only, zero writes). No protected formulas/constants exposed — all findings are database facts and public EODHD availability checks.

---

## 1. Closed-Trade Inventory

11 rows with `status='CLOSED'` in production `trades`:

| id | Ticker | Entry | Exit | Entry→Exit | Hold (hrs) | broker_ref | Realized PnL |
|---|---|---|---|---|---|---|---|
| 1 | AAPL | 299.81 | 299.81 | same second | 0.003 | *(empty)* | 0.00 |
| 2 | PBXT | 102.33 | 102.33 | same second | 0.0006 | *(empty)* | 0.00 |
| 3 | IBXT | 101.00 | 101.00 | same second | 0.0006 | *(empty)* | 0.00 |
| 5 | TSM | 440.81 | 446.74 | 44 min | 0.74 | *(empty — ref only in notes text)* | +56.96 |
| 12 | LRCX | 368.39 | 433.01 | 6.2 days | 148.4 | `P781232751` | +866.64 |
| 16 | INTC | 129.78 | 112.12 | 12.1 days | 291.0 | `P780203310` | -125.72 |
| 17 | MS | 225.98 | 214.80 | 4.0 days | 95.4 | `P1104545791` | -53.56 |
| 44 | KLIC | 121.34 | 132.14 | 1.2 days | 27.7 | `3500451266` | +249.26 |
| 45 | IRDM | 53.76 | 52.02 | 7.8 days | 188.0 | `IRDM_ORDER_FILLED_SCREENSHOT_20260629` | -48.55 |
| 46 | ALGM | 65.55 | 61.46 | 2.7 days | 63.8 | `3501197274` | -62.40 |
| 84 | MSM | 125.96 | 119.96 | 4.8 days | 114.9 | `3504304030` | -142.90 |

## 2. Classification

**Backfill/demo artifacts (3):** AAPL(1), PBXT(2), IBXT(3) — entry price exactly equals exit price, hold time sub-second (2–12ms), zero realized PnL, no `broker_ref`. These are known historical backfill/demo rows (previously confirmed in earlier session work, not real trading activity).

**Real broker-confirmed trades (6):** LRCX(12), MS(17), KLIC(44), IRDM(45), ALGM(46), MSM(84) — all have a populated `broker_ref` and multi-day realistic hold times, with buy-fill and sell-confirmation evidence documented in `notes` (broker screenshots or reference numbers) for both legs.

**Stop-detected, broker-confirmation pending (1):** INTC(16) — buy-side broker-confirmed (`broker_ref P780203310`, "Broker fill confirmed" in notes), but per prior incident tracking (P0K/P0M series) the **sell side has no confirmed `BROKER_SELL_FILLED` event and no `cash_ledger` credit** — the recorded `exit_price`/`exit_at` reflect the mechanical stop-hit detection, not a confirmed broker execution. This is a real trade with an outstanding confirmation gap, not a backfill artifact.

**Borderline / anomaly-flagged (1):** TSM(5) — `broker_ref` column is empty (the reference number `P1104145955`/`P479872813` exists only inside free-text `notes`, not the structured field), and the hold time is anomalously short (44 minutes) with the notes explicitly documenting a **known DB bug**: *"engine fired early exit due to wrong target in DB ($440.83 instead of $501)"*. This trade's exit was driven by a data-entry error, not genuine stop/target logic — including it in profit-factor/win-loss metrics would inject a known-corrupted signal.

## 3. Recommended Replay Validity

| Trade | Recommendation | Reason |
|---|---|---|
| AAPL, PBXT, IBXT | **EXCLUDE** | Backfill artifacts — zero real market exposure |
| TSM | **EXCLUDE** | No structured `broker_ref` + documented DB-bug-driven exit (wrong target value) — not representative of real exit logic |
| LRCX, MS, KLIC, IRDM, ALGM, MSM | **VALID for replay** | Broker-confirmed both legs, realistic hold times, no known data anomalies |
| INTC | **CONDITIONAL — separate bucket** | Real trade, buy-confirmed, sell-confirmation pending — see Section 8 |

**Valid replay set: 6 unconditional trades + 1 conditional (INTC) = 7 usable, out of 11 closed rows.**

## 4/5. Sector Mapping + EODHD Availability Probe (Live, Read-Only)

Live GET against EODHD (same provider/key already in production use) for every valid-replay ticker plus 2 new candidate sector proxies:

| Ticker | Proposed sector proxy | Rationale | Proxy EODHD status |
|---|---|---|---|
| LRCX | SOXX | Semiconductor equipment | Confirmed (P0O-4/P0O-7) |
| MS | XLF | Financials (investment bank) | Confirmed (P0O-4/P0O-7) |
| KLIC | SOXX | Semiconductor equipment (Kulicke & Soffa) | Confirmed (P0O-4/P0O-7) |
| IRDM | **XLC** (new) | Communication Services (Iridium — satellite comms, GICS Communication Services) | **Confirmed this audit** — HTTP 200, 2,022 rows, 2018-06-19 → 2026-07-07 |
| ALGM | SOXX | Semiconductors (Allegro MicroSystems) | Confirmed (P0O-4/P0O-7) |
| MSM | **XLI** (new) | Industrials (MSC Industrial Direct — industrial distributor) | **Confirmed this audit** — HTTP 200, 2,893 rows, 2015-01-02 → 2026-07-07 |
| INTC (conditional) | SOXX | Semiconductors | Confirmed (P0O-4/P0O-7) |

**Ticker-level EODHD probe (all confirmed HTTP 200):**

| Ticker | Rows | First date | Last date |
|---|---|---|---|
| LRCX.US | 2,893 | 2015-01-02 | 2026-07-07 |
| INTC.US | 2,893 | 2015-01-02 | 2026-07-07 |
| MS.US | 2,893 | 2015-01-02 | 2026-07-07 |
| KLIC.US | 2,893 | 2015-01-02 | 2026-07-07 |
| IRDM.US | 2,893 | 2015-01-02 | 2026-07-07 |
| ALGM.US | 1,426 | 2020-10-29 | 2026-07-07 |
| MSM.US | 2,893 | 2015-01-02 | 2026-07-07 |
| TSM.US | 2,893 | 2015-01-02 | 2026-07-07 *(probed for completeness only — trade excluded, data not needed)* |

**All 7 valid-replay tickers (6 unconditional + INTC) plus both new sector proxies (XLI, XLC) are confirmed available.** ALGM has the shortest history (2020-10-29, ~1,426 daily rows) — still far more than the harness's `MIN_REQUIRED_LOOKBACK` (23 trading days), so no insufficient-history exclusion applies to any candidate.

## 6. Expanded Cache Symbol List (proposed, not yet implemented)

Existing 10 (P0O-7/P0O-8) + 8 new (6 tickers + 2 new sector proxies) + INTC (conditional, already in the existing-10-adjacent semis-proxy family) = **19 symbols total**:

`SPY.US, QQQ.US, VIX.INDX, SOXX.US, XLY.US, XLF.US, XLI.US, XLC.US, SYNA.US, RL.US, BAC.US, ABNB.US, LRCX.US, MS.US, KLIC.US, IRDM.US, ALGM.US, MSM.US, INTC.US`

(TSM.US intentionally excluded from this list — the TSM trade itself is excluded from replay per Section 3, so its OHLCV isn't needed.)

## 7. Exclusion Rules (applied + formalized for future automation)

| Rule | Trades it removes |
|---|---|
| No `broker_ref` populated | AAPL, PBXT, IBXT, TSM |
| `entry_price == exit_price` | AAPL, PBXT, IBXT |
| Too-short hold (sub-minute) | AAPL, PBXT, IBXT |
| Documented data/DB anomaly in notes (e.g. "wrong target in DB") | TSM |
| Insufficient EODHD history for indicator lookback | None currently — all valid-replay tickers confirmed with ≥1,426 rows, well above the ~23-day minimum |
| Missing sector proxy | None currently — all 7 valid-replay tickers now have a confirmed proxy (Section 4/5) |

These 4 concrete rules (empty `broker_ref` OR entry==exit OR hold < some minimum threshold OR notes flags a known anomaly) are sufficient to explain every exclusion in the current dataset — worth codifying as an automated pre-flight filter for future replay runs so new closed trades are auto-screened the same way.

## 8. INTC Treatment (Explicit Decision)

- **Include as a stop-detected real trade?** YES — it is not a backfill artifact; it has a real buy-side broker confirmation and a real mechanically-detected stop-hit exit.
- **Mark broker-confirmation pending?** YES — tag with an explicit `SELL_CONFIRMATION_PENDING` flag distinct from the 6 fully-confirmed trades, consistent with the already-existing pending-broker-confirmation report feature (P0M series) that surfaces this same gap in live reporting.
- **Include/exclude from profit-factor metrics?** **Recommend dual-bucket reporting, not a single blended number:** compute the core metrics (profit factor, win/loss, max drawdown, R-multiple) on the **6 unconditional trades only** as the canonical replay result, and separately compute the **same metrics with INTC included** as a clearly-labeled secondary/exploratory view. Rationale: INTC's recorded `exit_price` (112.12) reflects the mechanical stop-hit detection, not a confirmed broker fill — if the eventual broker confirmation shows a materially different fill price (slippage, gap-through), the "true" INTC realized loss could differ from what's currently in the DB. Baking an unconfirmed number into the canonical metric risks having to restate results later; keeping it in a clearly-flagged secondary bucket avoids that risk while still surfacing the data point.

## Answers to Structured Fields

- **P0O9_STATUS:** EXPANSION_AUDIT_COMPLETE
- **closed_trades_inventory:** 11 total — 3 backfill artifacts (AAPL/PBXT/IBXT), 1 anomaly-flagged (TSM, DB-bug-driven exit), 6 broker-confirmed valid trades (LRCX/MS/KLIC/IRDM/ALGM/MSM), 1 conditional (INTC, sell-confirmation pending)
- **valid_replay_trades:** LRCX(12), MS(17), KLIC(44), IRDM(45), ALGM(46), MSM(84) — 6 unconditional; INTC(16) conditional/dual-bucket per Section 8
- **excluded_trades_with_reasons:** AAPL/PBXT/IBXT — entry==exit price, sub-second hold, no broker_ref, zero PnL (backfill artifacts); TSM — no structured broker_ref (ref exists only in free-text notes) + notes explicitly document a DB bug causing an incorrect early exit (wrong target value in DB)
- **INTC_treatment:** Include as a real stop-detected trade; flag `SELL_CONFIRMATION_PENDING`; compute canonical metrics on the 6 unconditional trades only, with INTC reported separately in a secondary/exploratory metrics bucket rather than blended into the primary result
- **sector_mapping_for_valid_trades:** LRCX→SOXX, MS→XLF, KLIC→SOXX, IRDM→XLC (new), ALGM→SOXX, MSM→XLI (new), INTC→SOXX — all 7 confirmed available via live EODHD probe this audit
- **provider_availability_plan:** All 7 tickers + both new sector proxies (XLI, XLC) confirmed HTTP 200 via EODHD, same provider/key as production; depth ranges 1,426–2,893 rows (2015–2026 for most, 2020–2026 for ALGM, 2018–2026 for XLC) — all comfortably exceed the harness's minimum lookback requirement
- **expanded_cache_symbols:** 19 total — the existing 10 (SPY/QQQ/VIX.INDX/SOXX/XLY/XLF/SYNA/RL/BAC/ABNB) + LRCX/MS/KLIC/IRDM/ALGM/MSM/INTC + 2 new sector proxies (XLI/XLC); TSM intentionally excluded (its trade is excluded from replay)
- **replay_metrics_scope:** Primary/canonical metrics computed on 6 unconditional closed trades + continue forward-simulating the 4 open positions (unchanged from P0O-8); INTC reported in a separate secondary bucket pending broker sell confirmation; AAPL/PBXT/IBXT/TSM permanently excluded from all metrics
- **ready_for_closed_trade_replay_implementation:** YES — data availability, sector mapping, and exclusion rules are all resolved; only remaining step is the actual staged code expansion (not done in this read-only audit)
- **production changes:** NONE
