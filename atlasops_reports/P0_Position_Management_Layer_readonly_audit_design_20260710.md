# P0 deterministic Position Management Layer — read-only audit and design

## Required return

**STATUS = CONFIRMED**  
**production touched = NO**

Atlas does **not** currently perform a complete daily re-underwriting of every OPEN position’s thesis, target, stop, volatility, catalyst, sector state, and regime. It does run recurring exit evaluation, reconstructs a limited post-entry high-water series, can ratchet a stop upward under narrow peak/regime rules, and performs advisory time/earnings/event checks. It does not maintain a durable original-plan record plus daily deterministic advisory state, does not persist MFE/MAE/peak giveback, and does not deterministically review or revise targets as conditions evolve.

The requested Position Management Layer is feasible as an additive, advisory-only deterministic module without changing Fat Engine strategy or canonical trade fields in Phase 1.

---

## Scope and evidence discipline

Read-only sources:

- `/Users/yasser/scripts/atlas_engine.py`
- `/Users/yasser/scripts/atlas_portfolio.py`
- `/Users/yasser/scripts/atlas_db.py`
- `/Users/yasser/scripts/atlas_manage.py`
- `/Users/yasser/scripts/atlas_intraday.py`
- `/Users/yasser/scripts/atlas_profit_protection_advisory.py`
- canonical DB `/Users/yasser/scripts/atlas.db`, opened read-only
- read-only Massive/EODHD market/reference calls using existing runtime credentials without printing values

Protected source was inspected under Professor’s standing alpha-work authorization. This report contains bounded function/line evidence only, not broad source, alpha formulas, weights, or proprietary scoring internals.

No code/config/SOUL/skill/DB/schedule was changed. No process was restarted. No Telegram action occurred.

---

# Part A — current production lifecycle

## Initial stop and target origin

### Standard entry

- `atlas_engine.py::analyze_ticker()` lines **1759–1961** creates the scan-time ATR risk card and logs its stop to `signals`; this is signal history, not yet canonical trade authority.
- `atlas_portfolio.py::consider_buy()` lines **1784–2036** selects the actual entry stop from the applicable entry context, including catalyst/opening-range/scan-risk/fallback paths. It creates the initial target from actual fill and selected risk at lines **1980–1981**.
- Live persistence occurs through `atlas_db.open_trade()` at `atlas_portfolio.py` lines **2022–2031**.
- `atlas_db.py::open_trade()` lines **564–593** writes `stop_loss`, `target_price`, and `manual_stop_lock=0` to `trades`. If target is absent while stop exists, it synthesizes the target before insertion.

### Special entries

- `consider_gap_up_breakout()` lines **1263–1333** persists breakout stop/target.
- `consider_intraday_breakout_continuation()` lines **1702–1778** persists prior-high-derived stop/target.
- `consider_sector_catalyst_peer_breakout()` lines **1638–1699** returns a candidate only; it does not persist a trade.
- `evaluate_pending_pullback()` lines **711–852** eventually routes an eligible trigger through normal `consider_buy()` persistence.

### Broker fill confirmation

- `atlas_db.py::confirm_trade_fill()` lines **644–699** converts `PENDING_FILL` to `OPEN`, updates fill price/quantity/fees, and normally retains the planned stop/target.
- It repairs a missing/invalid stop from preserved notes through `_preserved_fill_stop()` lines **629–641**.
- If the target is absent, it derives one from the confirmed fill and retained stop; an already-present target is not generally re-underwritten after a fill-price change.

### Manual-registration exception

- `atlas_manage.py::handle_register()` lines **1052–1086** can directly create an OPEN trade without a stop or target when no pending trade exists.

## Canonical authority

- `trades.stop_loss` and `trades.target_price` are the current production authority.
- `signals.stop_loss` is point-in-time scan history, not the active position stop.
- `position_lots` is an additive ledger/read-model, but current reconciliation defects mean it cannot yet replace `trades` as OPEN-position truth.

## Recurring OPEN-position evaluation

- `atlas_portfolio.py::run_exits()` lines **1135–1141** evaluates every OPEN trade using one regime tuple.
- `evaluate_exit()` lines **876–1096**:
  - reads persisted stop/target;
  - computes runtime fallback values if missing;
  - retrieves price;
  - reconstructs a limited post-entry high-water series;
  - considers target, hard stop, effective raised stop, and time exit;
  - returns advisory SELL/HOLD/ALERT output.
- Exit detection is advisory-only after the P0 exit gate; the row remains OPEN until broker-confirmed closure.

This is **recurring exit evaluation**, not complete re-underwriting. The target, original thesis, catalyst quality, sector state, and broader trend structure are not rebuilt into a new authoritative position plan each day.

## Every relevant value: read/mutation map

### `stop_loss`

Reads:

- `evaluate_exit()` lines **914–917**
- `get_open_positions()` lines **1102–1130**
- close/split bookkeeping in `atlas_db.close_trade()` lines **720–827**
- report/authority renderers

Writes:

- initial `open_trade()` lines **564–593**
- fill repair in `confirm_trade_fill()` lines **644–699**
- automatic tightening via `evaluate_exit()` lines **1040–1042** → `update_trade_stop()` lines **1029–1057**
- explicit Professor-approved replacement via `approve_official_atlas_stop_update()` lines **1710–1716**

### `target_price`

Reads:

- `evaluate_exit()` lines **918–919**, **1065–1066**
- OPEN-position/report renderers
- close/split bookkeeping

Writes:

- initial `open_trade()`
- missing-target creation in `confirm_trade_fill()` or `update_trade_stop()`
- explicit Professor-approved replacement through `approve_official_atlas_target_update()` lines **1701–1707**

There is no automatic target-extension or target-reduction engine after entry.

### `manual_stop_lock`

- defaults unlocked in `open_trade()`
- changed through `atlas_db.set_manual_stop_lock()` lines **1060–1073**
- CLI path in `atlas_manage.py` lines **1089–1115**
- read in `evaluate_exit()` lines **928–946**

It suppresses both peak-based and regime-based automatic tightening. Therefore it blocks safe tightening as well as unsafe movement. It does not disable the persisted hard stop, target, time exit, or explicit approved replacement.

### `current_price`, `last_price`, `last_price_at`

- live exit evaluation uses `_last_price()` (`atlas_portfolio.py` lines **281–290**) and daily-close fallback (`evaluate_exit()` lines **910–913**).
- `atlas_intraday.py::_ensure_trade_price_cache_columns()` lines **2080–2095** defines cache columns.
- `_cache_open_trade_prices()` lines **2098–2134** can write current/last price and timestamp, plus a valuation mark.
- Repository evidence found that writer dormant/unwired in the current intraday file.
- `_cached_open_trade_prices()` lines **2137–2152** does not select `last_price_at`, while a downstream footer asks for it; timestamp authority is therefore incomplete in that path.
- primary `get_open_positions()` does not expose these cache columns to every report authority path.

## Existing policy coverage

| Policy/review | Current production behavior |
|---|---|
| Static initial stop | Yes, persisted at entry/fill |
| Static initial target | Yes, persisted; can remain unchanged indefinitely |
| Breakeven ratchet | Yes, conditional peak/regime logic |
| Profit-lock ratchet | Yes, narrow effective-stop rule |
| ATR trailing after entry | No general Chandelier/ATR trail |
| EMA10/20/50 trailing | No; EMA is primarily entry timing |
| Confirmed swing-low trailing | No |
| Peak-profit giveback rule | No standalone rule |
| Historical MFE/MAE persistence | No |
| Target extension | No automatic deterministic review |
| Target reduction | No automatic deterministic review |
| Time exit | Yes, advisory SELL review |
| Catalyst invalidation | No post-entry stop/target mutation; limited advisory context |
| Earnings review | Warning/advisory only |
| FDA/event review | Warning/advisory only |
| Sector invalidation | No post-entry position-management gate |
| Regime review | Limited tightening branch; current regime semantics reduce reachability |
| Profit Protection P0P2a | Current-snapshot advisory only; no stored historical maximum favorable excursion |

## Stop widening

- Normal automatic path cannot widen a long stop: `update_trade_stop()` rejects equal/lower values at lines **1039–1042**.
- Explicit approved stop replacement helper directly writes the approved numeric value and does not independently enforce non-widening/manual-lock/status constraints. This is acceptable only as a separately authorized correction path; a future Position Management Layer must not use it automatically.

## Can a stale target remain forever?

**Yes.** Unless target is reached or Professor explicitly approves a replacement, the original target can remain displayed indefinitely. There is no scheduled deterministic KEEP/LOWER REVIEW/EXTEND REVIEW assessment with provenance.

---

# Part B — current OPEN-position evidence

## Retrieval and definitions

Provider retrieval: **2026-07-10 17:36:50 UTC**.

- latest price: read-only Massive current/in-progress bar
- ATR14: simple mean of latest 14 true ranges, Atlas-compatible
- EMA: standard chronological recursive EMA
- MFE/MAE: minute bars strictly after DB entry timestamp, with entry timestamps interpreted as UTC because the DB has no timezone column
- confirmed swing low: strict daily pivot below two preceding and two following daily lows
- market regime: SPY versus 50-day SMA using adjusted daily data

These values were calculated read-only outside production state. They are evidence for the design audit, not new canonical levels or recommendations.

## OPEN inventory

Five `trades.status='OPEN'` rows exist: SYNA, BAC, ABNB, PENG, LASR.

| Ticker | Age* | Entry | Persisted stop | Persisted target | Latest price | Gain | Risk/share** | Dist. stop | Dist. target |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SYNA | 14.14d | 126.44 | 113.35 | 156.61 | 127.2775 | +0.66% | 13.09 | 10.94% | 23.05% |
| BAC | 10.16d | 57.10 | 57.11 | 60.62 | 59.835 | +4.79% | **invalid -0.01** | 4.55% | 1.31% |
| ABNB | 9.93d | 143.03 | 135.96 | 157.17 | 148.60 | +3.89% | 7.07 | 8.51% | 5.77% |
| PENG | 2.04d | 75.70 | 75.71 | 100.01 | 79.705 | +5.29% | **invalid -0.01** | 5.01% | 25.48% |
| LASR | 1.11d | 75.61 | 66.94 | 106.68 | 72.095 | -4.65% | 8.67 | 7.15% | 47.97% |

\* Calendar age at provider retrieval; trading-session age should be the production design field.  
\** Entry minus current persisted stop. BAC/PENG stops sit one cent above entry, so “original risk” cannot be reconstructed from the current stop. Original stop must be preserved separately.

## Volatility, structure, and excursion

| Ticker | ATR14 | EMA10 / EMA20 / EMA50 | EMA stack | Confirmed swing low | MFE | MAE | Peak price | Giveback from peak |
|---|---:|---|---|---|---:|---:|---:|---:|
| SYNA | 9.1538 | 125.7648 / 127.3247 / 121.9890 | No | 115.98 (Jul 7) | +7.40% | -8.38% | 135.79 | 6.27% |
| BAC | 1.1375 | 58.7377 / 57.6061 / 55.3097 | Yes | 58.30 (Jul 8) | +6.52% | -0.72% | 60.825 | 1.63% |
| ABNB | 4.6987 | 145.9296 / 143.4507 / 139.4590 | Yes | 141.24 (Jul 8) | +4.92% | -1.25% | 150.07 | 0.98% |
| PENG | 9.5308 | 72.1991 / 68.1917 / 57.5690 | Yes | 58.63 (Jul 2; pre-entry) | +18.71% | -2.58% | 89.86 | 11.30% |
| LASR | 6.2028 | 66.5772 / 66.7477 / 67.7218 | No | 56.81 (Jul 8; pre-entry) | +1.09% | -7.87% | 76.43 | 5.67% |

Peak open-profit and profit giveback in percentage points:

- SYNA: peak +7.40%, current +0.66%, giveback **6.74 points**
- BAC: peak +6.52%, current +4.79%, giveback **1.73 points**
- ABNB: peak +4.92%, current +3.89%, giveback **1.03 points**
- PENG: peak +18.71%, current +5.29%, giveback **13.42 points**
- LASR: peak +1.09%, current -4.65%, giveback **5.74 points**

### Highest close since entry

**UNAVAILABLE in the captured evidence bundle.** Daily histories were used for ATR/EMA/pivots and minute histories for MFE/MAE, but the audit did not preserve a separately verified highest-close scalar. Phase 1 must calculate and provenance-tag it explicitly; it must not infer it from peak intraday price.

## Catalyst, earnings, sector, regime

| Ticker | Latest tagged news / age | Earnings evidence | Sector |
|---|---|---|---|
| SYNA | Jun 30 15:06Z / 242.5h; ticker relevance questionable | projected Aug 6 | Technology / Semiconductors |
| BAC | Jul 9 09:14Z / 32.4h | confirmed Jul 14 06:45 | Financial Services / diversified banks |
| ABNB | Jul 6 15:41Z / 97.9h | confirmed Aug 6 16:05 | Consumer Cyclical / travel services |
| PENG | Jul 9 16:38Z / 25.0h | Jul 7 confirmed beat; next projected Oct 6 | Technology / IT services |
| LASR | Jun 7 00:24Z / 809.2h | projected Aug 6 | Technology / Semiconductors |

Regime evidence at retrieval: SPY `754.205` versus 50-day SMA `741.2225` → **RISK-ON**. July 10 bar was still in progress.

Catalyst freshness is not presently stored as a durable publication timestamp tied to each OPEN thesis. Ticker-tagged provider news can also be irrelevant; provider tagging alone is insufficient authority.

## Current data-quality/reconciliation defects

1. `position_lots` contains an OPEN RL lot linked to a CLOSED legacy trade: orphan/ghost lot.
2. PENG trade 111 is OPEN but has no `position_lots` row.
3. LASR stop disagrees across stores:
   - `trades.stop_loss = 66.94`
   - `position_lots.stop_loss_decimal_text = 59.82`
4. Current/last-price cache values in `trades` were stale relative to provider retrieval.
5. BAC and PENG current stops no longer expose original risk; original stops are recoverable only from notes/events and must become first-class immutable fields.
6. No applicable manual override, broker display snapshot, or broker reconciliation row existed for these five positions.

These defects reinforce that Phase 1 should be a sidecar advisory state, not a rewrite of canonical ledger authority.

## Stale-target/stale-stop risk assessment

This audit does not label a level “wrong” merely because conditions changed. It identifies review risk:

- **SYNA:** target remains far away while peak gain largely reverted and EMA stack is no longer aligned. Deterministic EXIT/TRIM review evidence is absent today.
- **BAC:** price is close to target, trend remains aligned, and current stop is already above entry. The system cannot determine whether to KEEP, mark TARGET REACHED, or review extension based on a formal continuation contract. It must not automatically raise the target because price is near it.
- **ABNB:** target is moderately close with aligned EMA structure; no deterministic KEEP/EXTEND/LOWER assessment exists.
- **PENG:** large MFE and large giveback demonstrate the exact missing historical peak-profit state. The target itself may still be valid, but Atlas has no durable deterministic review to distinguish KEEP from TRIM/EXIT review.
- **LASR:** weak current result, no EMA stack, very wide distance to target, and a stop disagreement between stores require data-quality review before any position-management output can be authoritative.

Verdict: **stale-plan exposure is confirmed; specific replacement levels are not authorized or selected by this audit.**

---

# Part C — gap matrix against benchmark policies

| Candidate policy | Current Atlas | Data needed | Main discipline/risk |
|---|---|---|---|
| Static stop + target | Current baseline | original immutable plan | Stable but can become stale |
| Breakeven ratchet | Partial | original risk, verified high-water | Must never activate from bad original-risk data |
| ATR Chandelier | Absent | chronological highs/closes, ATR | Candidate must never lower current stop |
| EMA support stop | Absent | EMA10/20/50, ATR buffer | Avoid ordinary-noise whipsaw |
| Swing-low + ATR buffer | Absent | confirmed pivots only | No unconfirmed/lookahead pivot |
| Peak-profit giveback | Absent | durable MFE/peak profit | Advisory escalation, not automatic exit |
| Tiered profit management | Absent | deterministic R/MFE/structure states | Trim rules require separate strategy approval |
| Time stop | Partial advisory | trading-session age, progress metric | Distinguish stalled thesis from slow valid trend |
| Catalyst decay/invalidation | Partial warning | thesis catalyst ID/time/status | Provider failure cannot imply invalidation |
| Regime/sector review | Partial/absent | dated regime + sector-relative series | Advisory only in Phase 1 |
| Hybrid strongest protection | Absent | all valid candidate levels | Highest valid candidate for long, capped by non-widening invariant |

## Threshold discipline

No new multiplier, holding-period threshold, giveback percentage, or trim tier is chosen here. Candidate grids must be specified before replay, tested chronologically, and promoted only after train/validation/out-of-sample evidence and Professor approval. “Best on all trades” is prohibited.

---

# Part D — hard invariants for the design

1. `advisory_stop >= current_persisted_stop` for a long, or status `NO_VALID_ADVISORY_STOP`; never lower it.
2. Candidate must be below current verified price for a long; otherwise reject, never clamp.
3. Preserve immutable original entry, stop, target, risk, thesis, and entry provenance.
4. Never extend a target solely because price approaches it.
5. Extension review requires a complete deterministic evidence vector: continuation structure, confirmed breakout, sustained volume, valid catalyst, acceptable volatility, and acceptable forward reward/risk.
6. Weakening may produce `LOWER REVIEW`, `TRIM REVIEW`, or `EXIT REVIEW`; Phase 1 never writes the level.
7. Profit Protection remains advisory-only.
8. No broker stop, `trades.stop_loss`, `trades.target_price`, status, cash, or trade execution mutation without a separate explicit Professor authorization.
9. LLM renders/explains only. Python computes every value and enum.
10. Missing/stale/conflicting provider data preserves the last verified advisory state and returns `STALE`/`INCOMPLETE`; it cannot silently substitute or reset high-water state.
11. Every field carries `as_of`, provider/source, transformation version, and missing/conflict flags.
12. Current canonical-trade versus position-lot conflicts fail closed to `DATA_RECONCILIATION_REQUIRED`.

---

# Part E — proposed deterministic output

One machine-readable record and one renderer per OPEN trade:

```text
POSITION STATUS:
HOLD | TIGHTEN | PROTECT PROFIT | TRIM REVIEW | EXIT REVIEW | DATA RECONCILIATION REQUIRED

ORIGINAL PLAN:
Entry; immutable original stop; immutable original target; original risk; thesis/catalyst provenance.

CURRENT STATE:
Verified price; P/L; peak P/L; giveback; ATR; EMA/trend state; catalyst state; sector/regime; trading-session age.

ADVISORY STOP:
Exact candidate; policy method; source bars; as-of timestamp; rejected candidate reasons.

TARGET STATUS:
KEEP | LOWER REVIEW | EXTEND REVIEW | TARGET REACHED | INCOMPLETE

REASON:
Plain-English rendering of deterministic reason codes only.

RECHECK:
Exact deterministic trigger or next after-close review.

DATA FRESHNESS:
Per-source timestamp, provider, latency, missing/conflicting fields, review version.
```

### Suggested machine enums

- `position_status`: `HOLD`, `TIGHTEN`, `PROTECT_PROFIT`, `TRIM_REVIEW`, `EXIT_REVIEW`, `DATA_RECONCILIATION_REQUIRED`, `INCOMPLETE`
- `target_status`: `KEEP`, `LOWER_REVIEW`, `EXTEND_REVIEW`, `TARGET_REACHED`, `INCOMPLETE`
- `advisory_stop_method`: `CURRENT_STOP`, `BREAKEVEN`, `ATR_CHANDELIER`, `EMA_BUFFER`, `CONFIRMED_SWING_LOW_BUFFER`, `HYBRID_STRONGEST_VALID`, `NO_VALID_ADVISORY_STOP`

No natural-language parser may create these states.

---

# Part F — historical replay methodology

## Data buckets

Keep separate:

1. fully broker-confirmed closed trades — canonical results;
2. confirmation-pending/anomalous trades — secondary only;
3. FILLED pending pullbacks — signal-only historical candidates, never blended with broker results;
4. current OPEN positions — forward simulation only.

Current substrate:

- 12 CLOSED legacy trades
- 22 FILLED pullback rows
- 35,109 signal rows, from 2026-06-19 through 2026-07-10
- five OPEN trades

This is too small/short for promotion claims. The replay is initially a mechanism and safety study.

## Chronological no-lookahead simulation

For each trade/candidate:

1. freeze the immutable entry plan available at entry time;
2. expose market/news/regime/sector data only through `as_of(timestamp)` accessors;
3. update high-water, low-water, ATR, EMA, pivots, catalyst age, and regime chronologically;
4. do not confirm a swing pivot until future confirmation bars have actually occurred;
5. model gap-through-stop at next available executable price where evidence permits;
6. include broker commissions/fees and slippage assumptions as explicit scenario inputs, not hidden constants;
7. never expose actual historical exit fields to candidate policy calculations before the exit timestamp;
8. record every policy transition and rejected stop-widening attempt.

## Policy variants

- baseline static stop/static target
- static target + breakeven
- ATR Chandelier variants
- EMA10/20/50 support-buffer variants
- confirmed swing-low variants
- peak-giveback advisory variants
- tiered review variants
- time-stop variants
- catalyst/sector/regime review variants
- hybrid highest-valid-protection variant

Threshold grids must be predeclared. Parameter selection uses training only.

## Split discipline

Because the current production history is short:

- use expanding-window chronological walk-forward splits;
- maintain separate train, validation, and final chronological out-of-sample windows;
- do not tune on validation/OOS;
- report samples and confidence intervals per bucket/regime/setup;
- require a future minimum-sample promotion gate approved before implementation; this audit does not invent that threshold.

## Required metrics

For every policy and evidence bucket:

- total return
- expectancy/trade
- profit factor
- win rate
- average winner/loser
- maximum drawdown
- MFE captured
- average peak-profit giveback
- premature-exit rate
- target-hit rate
- stop-hit rate
- average holding period
- turnover
- whipsaw count
- results by bull/neutral/bear/shock regime
- setup type
- volatility bucket
- sector
- data-quality completeness

Include gross and net-of-cost variants.

## Required replay cases

Fixtures must include:

1. PENG approximately +18% MFE then near +9%/lower current gain;
2. WDFC post-earnings gap/reversal;
3. price approaches stale target while continuation strengthens;
4. price approaches target while catalyst/momentum deteriorate;
5. volatility expansion;
6. volatility contraction;
7. sector breakdown;
8. market-regime transition;
9. missing/stale provider data;
10. naive recalculation produces a lower long stop and must return `REJECTED_WOULD_WIDEN_STOP`;
11. conflicting `trades`/`position_lots` authority;
12. gap through advisory stop;
13. split/partial-close continuity;
14. manually locked stop where advisory tightening may still be calculated but never persisted.

---

# Part G — recommended architecture

## Phase 1 module

Proposed new module:

`/Users/yasser/scripts/atlas_position_management.py`

Responsibilities:

- pure deterministic position-state computation;
- read-only canonical trade adapter;
- provider snapshots with provenance;
- chronological high-water/low-water state;
- stop-policy candidates and non-widening selector;
- target KEEP/LOWER/EXTEND/TARGET_REACHED review enum;
- structured output and plain renderer;
- no Telegram, broker, or canonical DB mutation.

## Scheduling model

- authoritative review once after market close, after final daily bars are available;
- intraday only when deterministic thresholds are crossed or data authority changes;
- no full daily target “reset”;
- unchanged state should emit no duplicate alert;
- provider failures retain last verified state and mark freshness failure.

## Sidecar state

A new additive sidecar store is eventually justified, but **must not be created now**. Required logical fields:

- `legacy_trades_id`, ticker, position identity/version
- immutable `original_entry`, `original_stop`, `original_target`, `original_risk`
- original thesis/catalyst evidence ID and timestamps
- `peak_price`, `peak_price_at`
- `peak_close`, `peak_close_at`
- `trough_price`, MFE, MAE
- `peak_profit_pct`, current profit, giveback
- current ATR/EMA/swing/trend/sector/regime state
- `latest_advisory_stop`, method, rejected candidates
- `latest_target_zone`, target status
- review state/reason/recheck
- reviewed-at and per-source timestamps
- data-quality flags, calculation version, input digest, idempotency key

Prefer append-only review snapshots plus a derived latest-state view, rather than overwriting history.

## Authority hierarchy

1. canonical `trades` OPEN status/entry/current persisted stop/target;
2. immutable original-plan sidecar facts reconstructed once and then locked;
3. verified market/provider inputs;
4. deterministic advisory calculation;
5. LLM renderer only;
6. Professor separately authorizes any canonical/broker change.

`position_lots` cannot be promoted to primary authority until RL/PENG/LASR reconciliation defects are resolved under a separate work order.

---

# Files likely involved later

Phase 1 staging candidates:

- new `atlas_position_management.py`
- new focused tests and immutable fixtures under `/tmp/.../tests/`
- copied-DB replay harness, not production
- optional standalone file-output runner for after-close review
- optional report renderer integration in a later separately approved phase

Read-only adapters may reference:

- `atlas_db.py` for SELECT-only access
- provider guard/client modules for approved read-only bars/news
- `atlas_time.py` for trading-session age
- Perme structured context only as annotated provenance, never as numeric authority

Not required for Phase 1:

- `atlas_engine.py` modification
- `atlas_portfolio.py` modification
- `trades` schema mutation
- launchd/schedule change
- Telegram routing

---

# Strategy decisions requiring separate Professor approval

1. any breakeven activation threshold;
2. ATR/Chandelier multiplier and high-vs-close basis;
3. EMA choice and volatility buffer;
4. pivot definition/buffer;
5. peak-giveback percentage or R threshold;
6. trim tiers and quantities;
7. time-stop sessions/progress rule;
8. catalyst expiry semantics;
9. sector/regime downgrade effects;
10. target-extension evidence thresholds;
11. whether any advisory state can later become a canonical stop/target write;
12. whether `manual_stop_lock` semantics should be split into “prevent automatic mutation” versus “allow advisory tightening.”

No such decision is made by this audit.

---

# Proposed staging plan

## Stage 1 — deterministic state calculator

Create `/tmp/p0_position_management_v1/` with:

- source module
- immutable OPEN-position fixtures
- PENG/WDFC scenario fixtures
- copied DB opened read-only
- cached historical bars/news with provenance
- no-send file-only output

Acceptance:

- compile clean;
- zero protected imports required;
- zero SQL write statements;
- production DB/file SHAs unchanged;
- exact original-plan preservation;
- all calculations reproducible byte-for-byte;
- every numeric output traced to source+timestamp;
- missing/conflicting data produces explicit incomplete state.

## Stage 2 — policy replay

- chronological accessor with structural no-lookahead enforcement;
- baseline plus candidate variants;
- train/validation/OOS separation;
- costs/gaps scenarios;
- metrics by regime/setup/volatility/sector;
- robustness sweeps, leave-one-out, concentration checks;
- no parameter promotion from the same sample used for evaluation.

Acceptance:

- no-lookahead self-test PASS;
- naive stop widening rejected in every policy/grid combination;
- candidate stop below verified price for a long;
- historical trigger values never masquerade as current recommendations;
- canonical/secondary/signal-only/open buckets never blended;
- required PENG/WDFC and degradation fixtures pass.

## Stage 3 — advisory state prototype

Use a standalone `/tmp` SQLite sidecar or JSONL append-only store, never production DB.

Acceptance:

- idempotent same-input rerun;
- high-water cannot regress;
- provider failure retains last verified snapshot;
- review transitions are fully reason-coded;
- no canonical trade, cash, broker, stop, target, or status mutation;
- no Telegram send.

## Stage 4 — copied-report integration

Only after Professor approves Stage 1–3 evidence:

- copied report renderer consumes structured advisory output;
- exact requested POSITION STATUS contract;
- LLM prohibited from calculating/changing levels;
- zero changes to TFE signal/scoring/BUY/AVOID.

Production deployment and scheduling would require later separate approvals.

---

# Final conclusions

- **Daily full re-underwriting exists: NO.**
- **Recurring exit review exists: YES, but limited.**
- **Static target can become a ghost target: YES.**
- **Normal automated stop widening: blocked.**
- **Manual stop lock also blocks safe automatic tightening: YES.**
- **Profit Protection stores historical MFE: NO.**
- **Phase 1 can be advisory-only without strategy change: YES.**
- **New sidecar state eventually required: YES, additive and append-only preferred.**
- **Current ledger/read-model reconciliation must be addressed before using `position_lots` as authority.**

**STATUS = CONFIRMED**  
**production touched = NO**
