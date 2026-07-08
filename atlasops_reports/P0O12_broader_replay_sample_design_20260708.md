# P0O-12: Broader Replay-Sample Design (Read-Only)

**Status:** READ-ONLY design document. No code/DB/production changes. `atlas_engine.py`/`atlas_portfolio.py` not touched. No protected formulas/constants exposed — findings below are DB facts (table schemas, row counts) and public design reasoning only.

---

## 1. Available Historical Universe Sources (Live-Queried, Read-Only)

| Source | Table | Row count | Date range | Notes |
|---|---|---|---|---|
| **Atlas scanned candidates / signal history** | `signals` | **27,284** | 2026-06-19 → 2026-07-07 (~3 weeks) | Every scan tick's pillar-score output per ticker, including `entry_price`, `stop_loss`, `atr`, RVOL, trend/RS/volume/catalyst sub-fields, `warnings` |
| **Pending pullbacks (armed limit orders)** | `pending_pullbacks` | 50 (22 FILLED, 15 EXPIRED, 13 WAITING) | Live table, rolling | Tracks tickers that passed the pillar gate and were armed at a specific EMA-pullback trigger price — `FILLED` rows represent the moment Atlas's logic decided to act, whether or not a broker fill or `trades` row ultimately resulted |
| **EMA retry candidates** | `ema_retry_candidates` | 0 (currently empty) | N/A | Structurally exists but has no historical rows right now — not a usable source today |
| **Current provider OHLCV** | EODHD (already confirmed available for 19+ symbols across P0O-4/5/7/9) | N/A (external) | 2015–2026 for most equities | The actual price series any expanded replay would need — already proven reliable |
| **Historical watchlists** | *(searched, not found)* | — | — | No dedicated watchlist table or file exists separately from `pending_pullbacks`/`signals` — this is not a distinct additional source, it's effectively covered by the two tables above |

**Headline finding: the `signals` table is the single richest untapped source.** 27,284 rows, 107 distinct tickers ever tagged BUY-type, spanning nearly 3 weeks of scan history — this dwarfs the 6-trade canonical closed-trade set used in P0O-10/P0O-11.

**Signal-type breakdown (for context, not a strategy disclosure — these are just the pillar-tier labels already visible in every live report):**

| Signal | Count |
|---|---|
| 🔴 AVOID | 15,855 |
| ⚪ WATCH | 7,468 |
| 🟡 BUY (Small) | 3,720 |
| 🟢 BUY | 194 |
| 🟠 BUY (Catalyst Override) | 47 |

## 2. Inclusion Criteria for Synthetic/Replay "Trades" — Without Fabricating Broker Fills

The critical constraint: **a `signals` row is Atlas *noticing* a setup, not evidence a trade happened.** Treating every BUY-tagged signal as a "trade" would fabricate history that never occurred. The design must draw a hard line between:

- **Real trades** (from `trades`, broker-confirmed — the only rows with genuine realized PnL)
- **Signal-only historical candidates** (from `signals`/`pending_pullbacks` — Atlas *would have* acted on these under its own logic, but no capital was ever risked)

**Proposed inclusion rule for a "signal-only replay candidate":**
1. Must be a `pending_pullbacks` row with `status='FILLED'` (i.e., the armed trigger price was actually touched — this is the closest analog to "Atlas's own logic decided this was actionable," using the exact entry price/trigger Atlas itself computed, not a re-derived one)
2. Must NOT be conflated with or presented as a real trade outcome — always tagged `SIGNAL_ONLY_HISTORICAL`, distinct from `broker_confirmed` trades, in any report or metric
3. The candidate's own recorded `trigger_price` (from `pending_pullbacks`) is used as the synthetic entry — never a fabricated or estimated price
4. Exit is determined purely by re-running the **already-approved, already-implemented replay stop-policy math** (ATR/Chandelier/swing-low/EMA/max-loss, per P0O-7 through P0O-11) against real OHLCV going forward from the trigger date — the "exit" is a mechanically-computed simulation outcome, not a fabricated broker fill
5. Excluded entirely if the ticker has no future OHLCV coverage past the trigger date (can't simulate an outcome) or if `status` is `WAITING`/`EXPIRED` (never actually triggered — including these would fabricate an entry that never happened)

This keeps the line bright: **signal-only candidates simulate "what if Atlas had traded this," using only Atlas's own already-computed trigger price and publicly-available forward price action — never inventing a fill, a broker reference, or a PnL outcome that didn't happen.**

## 3. Three-Way Separation (Formalized)

| Bucket | Source | Confidence level | Use in metrics |
|---|---|---|---|
| **Broker-confirmed trades** | `trades` table, `status='CLOSED'`, passes P0O-9 exclusion rules | Highest — real capital, real fills | Canonical metrics (unchanged from P0O-10/11) |
| **Signal-only historical candidates** | `pending_pullbacks` where `status='FILLED'`, simulated exit via replay stop-policy math | Medium — real entry trigger, simulated exit | **Separate, clearly-labeled exploratory bucket** — expands sample size for mechanics/robustness testing, never blended into the canonical broker-confirmed profit factor |
| **Forward-sim open positions** | `trades` table, `status='OPEN'` (SYNA/RL/BAC/ABNB) | Real entry, no exit yet | Unchanged, its own bucket (per P0O-10/11 design) |

This gives **3 buckets total** going forward (up from 2 in P0O-10/11), each with a distinct evidentiary weight, never merged.

## 4. Replaying Entry/Exit Logic Without Touching Protected Alpha Formulas

- **Entry price:** always taken directly from the existing recorded value (`trades.entry_price` for real trades, `pending_pullbacks.trigger_price` for signal-only candidates) — never recomputed from pillar-scoring internals. This is the same non-disclosure boundary already respected in P0O-7 through P0O-11.
- **Exit/stop logic:** continues to use only the 6 public-benchmark stop-policy methods (ATR, Chandelier, swing-low, EMA invalidation, max-loss floor, combined-selection) already built and validated — **zero new dependency on `atlas_engine.py`/`atlas_portfolio.py`** for either bucket type.
- **Pillar score / signal tier** (`score`, `signal` columns in `signals`/`pending_pullbacks`) can be read and reported as **metadata/context** (e.g. "this candidate was 🟢 BUY 4/4 Pillars") without that constituting exposure of the scoring formula itself — it's the same tier label already shown in every live Telegram report today, not a new disclosure.
- **No new read-accessor into the protected files is needed** for this expansion — everything required (`entry_price`, `stop_loss`, `signal`, `score`, `trigger_price`, `armed_at`, `filled_at`) already lives in plain DB columns already read in prior P0O tasks.

## 5. Minimum Sample Size Targets

| Purpose | Target | Rationale |
|---|---|---|
| **Mechanics/robustness review** (what P0O-11 already started) | **50+ combined trades** (broker-confirmed + signal-only) | Enough to move leave-one-out sensitivity away from "one trade swings everything" — at 50, a single trade is ≤2% of the sample instead of ≤17% (1/6, as seen in P0O-11's LRCX concentration finding) |
| **Parameter-confidence / promotion-candidate decisions** | **100+ preferred** | Standard rule-of-thumb minimum for trusting a parameter sweep's "best" result isn't noise; with the 27,284-row `signals` table and 22 FILLED `pending_pullbacks`, reaching 50–100 signal-only candidates alone looks achievable without needing new data collection — it may take longer to accumulate 100+ genuine broker-confirmed trades, which is fine since that bucket stays separate anyway |
| **Any live-effect promotion (per P0O-2/P0O-3's shadow-mode gate)** | Unchanged from prior RFCs — still requires non-degrading profit factor/drawdown vs. baseline, now measured against whichever bucket meets the size threshold above, never against a n=6 sample alone |

## 6. Overfitting Controls (Design)

| Control | Design |
|---|---|
| **Leave-one-out** | Already implemented (P0O-11) — extend unchanged to the larger sample; with 50+ trades, a single exclusion should move profit factor by single-digit percentage points, not the ~5x swing seen with n=6 |
| **Walk-forward split** | New for this phase: split the expanded sample chronologically (e.g. first 70% of candidates by trigger/entry date = "train" window for picking a parameter set, last 30% = "test" window to verify the chosen parameters still perform) — this directly tests whether a parameter set tuned on early data still works on later, unseen data, which the P0O-11 sweep did not test (it only tuned and measured against the same 6 trades) |
| **Per-sector split** | New: bucket trades/candidates by their mapped sector proxy (SOXX/XLY/XLF/XLI/XLC-class, extending the P0O-9 mapping) and report profit factor per sector separately — surfaces whether an apparently-robust result is actually just "this works great in semis and nowhere else" |
| **Winner-concentration threshold** | Formalize the informal flag P0O-11 already used ("LRCX = 83.9% of gross win, FLAG") into an explicit rule: **if any single trade contributes >40% of gross winning PnL, the bucket's profit factor is marked NOT-YET-TRUSTED regardless of its numeric value**, and must be re-evaluated once the sample grows past that concentration. 40% is chosen as roughly "no single trade should be worth more than 2.5x an equal-weighted share once n≥10" — an implementation parameter, adjustable by Prof, not a hard scientific constant |

## Answers to Structured Fields

- **P0O12_STATUS:** DESIGN_COMPLETE — read-only, no implementation
- **available_historical_sources:** `signals` (27,284 rows, ~3 weeks, 107 distinct BUY-tagged tickers — by far the richest source), `pending_pullbacks` (50 rows: 22 FILLED / 15 EXPIRED / 13 WAITING), `ema_retry_candidates` (0 rows, currently unusable), existing EODHD OHLCV provider (already proven reliable across P0O-4/5/7/9); no separate "historical watchlist" source exists beyond these two tables
- **replay_universe_options:** (1) broker-confirmed closed trades — unchanged, highest confidence; (2) signal-only historical candidates derived from `pending_pullbacks.status='FILLED'` using Atlas's own recorded `trigger_price` + simulated exit via existing public-benchmark stop policies — medium confidence, clearly labeled, never blended with (1); (3) open-position forward-simulation — unchanged
- **inclusion_exclusion_rules:** Include signal-only candidates only where `pending_pullbacks.status='FILLED'` AND forward OHLCV exists past the trigger date; exclude `WAITING`/`EXPIRED` rows (never triggered — including them would fabricate an entry); exclude any candidate ticker with no post-trigger price coverage; broker-confirmed bucket keeps the unchanged P0O-9 rules (no `broker_ref`, entry==exit, too-short hold, documented DB anomaly)
- **sample_size_target:** 50+ combined trades/candidates minimum for mechanics/robustness review; 100+ preferred before trusting any specific parameter set for promotion consideration; both realistically reachable from the signal-only bucket given 22 already-FILLED `pending_pullbacks` rows and the option to relax to earlier signal history if needed
- **protected_logic_constraints:** Entry prices/stop levels always read from existing plain-column DB values (`trades.entry_price`, `pending_pullbacks.trigger_price`), never recomputed from scoring internals; exit/stop simulation continues using only the 6 already-built public-benchmark methods; pillar tier labels may be shown as context (already-public report language) without exposing the underlying formula; zero new protected-file read-accessor required
- **overfitting_controls:** Leave-one-out (already built, P0O-11) + new walk-forward chronological train/test split + new per-sector profit-factor breakdown + a formalized winner-concentration threshold (>40% of gross win from one trade = NOT-YET-TRUSTED flag, adjustable by Prof)
- **recommended_next_phase:** A P0O-13 STAGING-ONLY implementation that (a) extracts `pending_pullbacks.status='FILLED'` rows into the new signal-only bucket, (b) re-runs the existing P0O-10/11 replay+sweep machinery against broker-confirmed + signal-only combined, (c) adds the walk-forward split and per-sector breakdown, (d) re-applies the winner-concentration threshold at the larger sample size — all before any shadow-recommendation live-adjacent work begins, consistent with the standing staging-first protocol
- **production changes:** NONE
