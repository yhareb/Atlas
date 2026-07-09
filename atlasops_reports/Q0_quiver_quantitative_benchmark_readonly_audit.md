# Phase Q0 — Quiver Quantitative Benchmark Package

**Scope:** read-only benchmark/audit + benchmark design only  
**Generated:** 2026-07-09 14:27:41 +04  
**Operator:** AtlasOps / Hermes  
**Production DB:** `/Users/yasser/scripts/atlas.db` opened read-only via SQLite URI `mode=ro`

## 1. Hard-constraint compliance

- Production DB writes: **NO**
- Production script patches/deployment: **NO**
- Scoring changes: **NO**
- Fat Engine math changes: **NO**
- Telegram sends/tests/config access: **NO**
- Broker actions: **NO**
- Env/secret values printed: **NO**
- Quiver lookahead rule: **filing/report/upload/publication date only; never transaction date**

Evidence:

```text
atlas.db SHA256 pre-audit: 545fe1a1d381536e524e1c0aec519ca91f71c8331723659f35b1f3ee347754da
atlas_manage.py SHA256:   96693d72175920c728cf63756784942f831f541f4272f07a0f9e962edc0e4f10
atlas_db.py SHA256:       cd7825fd319239ae36982b1cfdd7a5e8a0684252a4ba008e72a28be442873b11
Quiver env var names found in current shell: NONE
Quiver live endpoint probe: /beta/live/congresstrading -> HTTP 401 Unauthorized
Quiver docs/schema probe: https://api.quiverquant.com/docs/schema.json -> HTTP 200
```

Boundary note: an initial broad content search over `/Users/yasser/scripts` returned small incidental matches from protected files. I stopped using those protected hits, did not read further into those files, and did not base this design on protected source internals.

## 2. Atlas benchmark substrate available now

Read-only DB inventory:

```text
table_count: 17
signals: 30280
trades: 80
pending_pullbacks: 52
portfolio_event_journal: 86
ledger_postings: 49
valuation_marks: 74
report_snapshots: 45
cash_ledger: 23
broker_reconciliation: 0
```

Benchmark-relevant Atlas rows:

```text
signals date range: 2026-06-19 15:35:27 -> 2026-07-08 19:55:14
signals rows / tickers: 30,280 / 678
BUY-tagged rows / tickers: 4,224 / 112
4/4 rows / tickers: 215 / 28
3/4 rows / tickers: 3,962 / 99
closed real-ish trades: 8 / 8 tickers
filled pullbacks: 22 / 22 tickers
```

Signal distribution:

```text
🔴 AVOID: 17,912
⚪ WATCH: 8,144
🟡 BUY (Small): 3,962
🟢 BUY: 215
🟠 BUY (Catalyst Override): 47
```

Useful DB columns for replay joins:

- `signals(timestamp, ticker, signal, score, rvol, entry_price, stop_loss, atr, trend_stack, relative_strength, volume, catalyst, warnings)`
- `pending_pullbacks(ticker, status, score, signal, signal_json, armed_at, trigger_price, filled_at, expired_at)`
- `trades(ticker, status, quantity, entry_price, entry_at, exit_price, exit_at, realized_pnl, stop_loss, broker_ref)`

**Assessment:** Atlas has enough signal rows to design the Q0 package immediately. Real broker-confirmed outcomes are still small-n; Q0 should treat filled pullbacks and signal-only candidates as exploratory buckets, never blended with canonical broker outcomes.

## 3. Quiver datasets available from provider schema

Quiver API docs were reachable read-only; data endpoints require authorization. No Quiver credential variable name is present in the current shell, and no local Quiver data/cache files were found under Atlas production paths.

| Dataset | Endpoint evidence | Atlas usability | No-lookahead date rule |
|---|---|---:|---|
| Congress trading | `/beta/historical/congresstrading/{ticker}`, `/beta/live/congresstrading` | **High once credentialed** | use `Filed` / `ReportDate`; ignore `TransactionDate` / trade date |
| House trading | `/beta/historical/housetrading/{ticker}` | **High once credentialed** | use `ReportDate`; ignore `Date` if transaction date |
| Senate trading | `/beta/historical/senatetrading/{ticker}` | **High once credentialed** | use `ReportDate`; ignore `Date` if transaction date |
| Insider Form 4 | `/beta/live/insiders` | **Medium**; Atlas already has EODHD Form-4 tag, so Quiver is cross-check not primary | use `fileDate` or `uploaded`; ignore transaction `Date` |
| Government contracts | `/beta/historical/govcontracts/{ticker}`, `/beta/historical/govcontractsall/{ticker}` | **Medium-high** for defense/industrial catalysts | use source publication/report quarter availability; never backdate to action date without lag |
| Lobbying | `/beta/historical/lobbying/{ticker}` | **Medium**; slower signal, sector/regulatory context | use public filing/report date if supplied; otherwise use Quiver upload/ingest date |
| Patents | `/beta/historical/allpatents/{ticker}`, `/beta/live/allpatents` | **Medium**; useful for tech/biotech/AI themes | use grant/publication date, not application/priority date |
| SEC 13F / fund changes | `/beta/live/sec13f`, `/beta/live/sec13fchanges` | **Medium-low for short horizon** due filing lag | use filing/report availability date only |
| Off-exchange | `/beta/historical/offexchange/{ticker}` | **Exploratory**; may be noisy | use reported date available to Quiver |
| Quiver News / tickerdata | `/beta/live/quivernews`, `/beta/tickerdata` | **Exploratory**; headline/context only | use article datetime / upload time |

**Availability verdict:** provider datasets are available at the API/schema level but **not currently usable by Atlas runtime** until a Quiver credential/cache path is added in a later approved staging task. For Q0 design, the available endpoints and schema are sufficient.

## 4. Proposed deterministic Quiver Evidence Score — provisional only

Purpose: add a **separate evidence overlay** for benchmarking, not a live scoring change. Output is a sidecar field only: `quiver_evidence_score` in Q0 result JSON/CSV.

### Event normalization

Every Quiver row becomes:

```json
{
  "ticker": "XYZ",
  "dataset": "congress|house|senate|insider|gov_contract|lobbying|patent|13f|off_exchange|news",
  "event_available_at": "YYYY-MM-DD",
  "direction": "bullish|bearish|neutral",
  "magnitude_bucket": 0,
  "freshness_days": 0,
  "source_quality": "high|medium|low",
  "lookahead_safe": true
}
```

Rows are excluded if `event_available_at > atlas_signal_timestamp` or if the only available date is a transaction/action date that precedes public filing/report availability.

### Provisional score components

Compute on an as-of basis per `(ticker, atlas_signal_timestamp)` using only rows with `event_available_at <= signal_timestamp`:

| Component | Range | Rule |
|---|---:|---|
| political_disclosure | -3..+3 | net disclosed purchases/sales from Congress/House/Senate using filing/report dates only |
| insider_confirmation | -2..+2 | Quiver Form 4 buys/sells by filing/upload date; cross-check only if EODHD already tags insider activity |
| federal_revenue_tailwind | 0..+2 | gov contract/lobbying intensity if fresh and ticker-relevant |
| innovation_tailwind | 0..+2 | patent count/momentum by grant/publication date |
| institutional_context | -1..+1 | 13F/fund change context, discounted for lag |
| flow_context | -1..+1 | off-exchange/news/tickerdata, exploratory only |
| stale_penalty | 0..-2 | subtract for evidence older than configured freshness window |
| conflict_penalty | 0..-2 | subtract if high-quality datasets disagree directionally |

Final provisional score:

```text
quiver_evidence_score = clamp(sum(components), -5, +8)
quiver_evidence_bucket:
  +5..+8  = STRONG_SUPPORT
  +2..+4  = SUPPORT
  -1..+1  = NEUTRAL
  -4..-2  = CONTRADICTS
  -5      = STRONG_CONTRADICTION
```

Promotion rule for later phases: Quiver may only be considered useful if it reduces false BUYs without materially increasing missed winners. It must not become an authority layer in Q0.

## 5. Proposed deterministic Market Regime Gate — provisional only

Observed current orchestrator behavior from unprotected call sites: `atlas_manage.py` calls a regime check before candidate scoring and prints a SPY/50SMA-style risk-on/risk-off gate; macro context is passed along as an overlay. Q0 should benchmark a **separate deterministic regime classifier**, not alter the current live gate.

### Inputs

Recommended replayable daily series:

- SPY close vs 50SMA and 200SMA
- QQQ close vs 50SMA
- VIX level and 5-day change
- HYG vs LQD relative trend or HYG 20-day return
- SOXX or XLK leadership vs SPY
- Optional breadth only if historical breadth is actually available; otherwise omit rather than synthesize

### Gate states

```text
RISK_ON:
  SPY > 50SMA and 50SMA slope >= 0, VIX not elevated, credit not deteriorating

CAUTION:
  mixed trend, elevated VIX, weak credit, or semis/tech leadership deterioration

RISK_OFF:
  SPY < 50SMA or SPY < 200SMA, with confirming VIX/credit weakness
```

### Benchmark gating policy

- `TFE only`: no additional gate.
- `TFE + market regime`: allow BUY candidates in `RISK_ON`; mark as suppressed in `RISK_OFF`; keep `CAUTION` as half-weight/flagged in benchmark metrics, not a live rule.
- `TFE + Quiver + market regime`: Quiver can rescue only from `CAUTION`, not from `RISK_OFF`, during Q0 analysis.

## 6. Four benchmark variants

| Variant | Entry universe | Evidence sidecar | Regime sidecar | Q0 action |
|---|---|---|---|---|
| 1. TFE only | Existing Atlas BUY rows/candidates | none | none | baseline |
| 2. TFE + Quiver | Existing Atlas rows | Quiver score as-of signal timestamp | none | compare evidence uplift/suppression |
| 3. TFE + market regime | Existing Atlas rows | none | deterministic regime as-of date | compare macro suppression |
| 4. TFE + Quiver + market regime | Existing Atlas rows | Quiver score | regime gate | combined overlay benchmark |

Important: all four variants use the same historical Atlas candidate set. Q0 must not rerun or change TFE scoring.

## 7. Backtest plan using Atlas historical candidates/signals

### Buckets

1. **Canonical broker-confirmed trades** — highest confidence; small-n now.
2. **Filled pending pullbacks** — signal-only historical candidates; entry is recorded `trigger_price` at `filled_at`.
3. **BUY signal rows** — broad benchmark set; synthetic entry uses recorded `entry_price` at signal timestamp; de-duplicate per ticker/day to avoid scan-frequency overweight.
4. **Open-position forward-sim** — separate only; never blend with completed outcomes.

### No-lookahead accessor

For every data source:

```text
as_of(ticker, asof_timestamp): return only rows where event_available_at <= asof_timestamp
```

Forbidden:

- Quiver `TransactionDate`/politician trade date for Congress/House/Senate timing.
- Trade `exit_price` or `exit_at` in any entry-time decision calculation.
- Any full-series OHLC value beyond the signal date for regime classification.

### Outcome measurement

For each candidate row, compute forward returns using market data after the signal/fill date:

```text
forward_return_5d  = close[t+5]  / entry_price - 1
forward_return_10d = close[t+10] / entry_price - 1
forward_return_20d = close[t+20] / entry_price - 1
R_multiple = (exit_or_forward_price - entry_price) / (entry_price - stop_loss)
```

If stop loss is missing or invalid, row is excluded from R metrics but remains eligible for forward-return metrics.

### Required Q0 metrics

- Hit rate: `% candidates with positive forward return` by 5/10/20d horizon.
- Average R: mean R multiple by variant and bucket.
- Max drawdown: equity curve drawdown by chronological candidate sequence; signal-only and canonical separate.
- False BUY reduction: baseline BUYs with negative 10d/20d return suppressed by overlay ÷ baseline false BUYs.
- Missed winner rate: baseline winners suppressed by overlay ÷ baseline winners.
- 5/10/20-day forward returns: mean, median, win rate, p25/p75 by variant.

### Acceptance thresholds for “useful”

Provisional, not a live rule:

```text
useful if:
  false BUY reduction improves by >= 15%
  AND missed winner rate <= 10%
  AND average R does not deteriorate
  AND max drawdown improves or stays flat
  AND effect persists in walk-forward split

not useful if:
  false BUY reduction < 5%
  OR missed winner rate > 20%
  OR gains come from one ticker/sector/date cluster only

needs more data if:
  canonical n < 30 or signal-only n < 50 after exclusions
```

## 8. Implementation package design for a later approved Q0 harness

Staging-only layout:

```text
/tmp/atlas_q0_quiver_benchmark/
  src/q0_quiver_benchmark.py
  db/atlas.db                 # copied DB, opened read-only
  cache/quiver/*.json         # API results, keyed by endpoint+ticker+retrieved_at
  cache/market/*.json         # OHLC/regime inputs
  output/q0_results.json
  output/q0_report.md
```

Required safety checks:

- Copy production DB to `/tmp`; verify SHA matches production before reading.
- Open copied DB with `mode=ro`.
- Quiver fetcher writes only to `/tmp/.../cache`, never production.
- Import ban: no `atlas_engine` / `atlas_portfolio` imports.
- Telegram sender stubs not needed; no Telegram imports allowed.
- Emit a provenance manifest listing endpoint, ticker, retrieval time, row count, and date field used.
- Post-run verify production DB SHA unchanged.

## 9. Current blockers / caveats

1. **No Quiver credential in shell** — provider schema reachable, but data endpoints return `401 Unauthorized`.
2. **No existing local Quiver cache** found in Atlas production paths.
3. **Short Atlas outcome window** — DB has many signal rows but only 8 real-ish closed trades and 22 filled pullbacks; early verdict must rely mostly on signal-only forward returns.
4. **Market OHLC source still needs live preflight** for all tickers and regime instruments before running the actual benchmark.
5. **Quiver date semantics need endpoint-by-endpoint enforcement** — especially Congress/House/Senate, where transaction date must be ignored.

## 10. Phase Q0 verdict

**Verdict: needs more data / ready for staged benchmark harness design, not ready for live use.**

- Quiver datasets are provider-available and conceptually usable for Atlas as deterministic evidence overlays.
- Atlas has enough historical `signals` rows for an exploratory benchmark.
- Canonical realized trade history is still too small for a decisive “useful/not useful” production conclusion.
- The correct next step is a staging-only Q0 harness under `/tmp`, using copied DB + Quiver credential/cache if Prof approves, with strict filing/report-date as-of joins.
- No deployment or production patch should occur from Phase Q0.
