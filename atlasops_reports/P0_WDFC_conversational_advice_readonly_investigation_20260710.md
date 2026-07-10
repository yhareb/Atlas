# P0 WDFC Conversational Advice — Read-Only Investigation and Staging Design

**STATUS = CONFIRMED**  
**production touched = NO**

## Executive finding

The WDFC response was delayed **384.9 seconds (6m 24.9s)**, not primarily by the engine. The dominant delay was Hermes context compression on a severely oversized, long-lived Atlas session: **342.8 seconds / 89.1%** of wall time. The actual fresh WDFC engine command took **10.0 seconds**; the two model calls took **9.8s** and **14.4s**.

The recommendation was internally contradictory by design. The deterministic engine assigned `BUY (Small)` because WDFC passed 3 of 4 pillars. RSI 80.66, weak momentum, the ~22% gap, poor analyst-target reward/risk, and practical chase risk did not veto that raw signal. The conversational response led with the TFE BUY label while ending with the correct operator action—do not chase—without explicitly separating those two authorities.

Production had already generated sufficiently recent WDFC evidence before the question: an intraday snapshot at 14:06:28 UTC (5m32s old) showed BUY NOW at 4/4 with WDFC around $290, RSI 81, and contemporaneous signal rows existed at 14:04:42. No provider/engine output cache was found, but the DB and recent Telegram/session context were enough to answer a fast follow-up with exact provenance and a freshness caveat.

## Part A — exact latency trace

### Request and response timestamps

- Telegram text-batch flush: `2026-07-10 18:11:57.182 +04`
- Gateway inbound request: `18:11:57.191 +04` (`14:11:57.191 UTC`)
- User message persisted with rounded Telegram timestamp: `14:12:00 UTC`
- Gateway response ready: `18:18:22.105 +04`
- Telegram send began: `18:18:22.127 +04`
- Total gateway latency: **384.9s**

Source: Atlas `gateway.log:5336-5340` and `agent.log:15234-15260`.

### Per-step timeline

| Step | Evidence | Duration |
|---|---|---:|
| Gateway intake → first model request | inbound 18:11:57.191; model request 18:11:59.493 | 2.302s |
| First LLM routing/tool decision | API call #1; 831,078 input tokens, 418,666 cached; OpenRouter GPT-5.6 Sol Pro | 9.746s |
| Terminal setup + engine | environment ready 18:12:09.324; terminal completed 18:12:19.260 | 10.004s |
| Context compression | 168 messages, ~831,078 tokens; 18:12:19.726 → 18:18:02.537 | **342.811s** |
| Second LLM/final generation | 638,424 input tokens, 324,700 cached | 14.362s |
| Finalization/gateway handoff | API completion → response ready | 5.185s |
| **Total** | gateway measured | **384.914s** |

### Dominant delay

**Confirmed cause: oversized-session context compression.**

- Compression consumed 342.8s, **89.1%** of total latency.
- It attempted to compress an approximately **831k-token** context.
- Compression then warned: `no provider available for summary`; middle turns were dropped without a normal summary.
- The session split from `20260625_231225_74dc434c` to `20260710_181802_36507b`.
- The old session had 170 messages, 63 tool calls, 9.2M cumulative input tokens, 94.99M cache-read tokens, and a 25,040-character system prompt.

Not dominant:

- Engine/provider path: 10.0s.
- First model call: 9.8s.
- Final model call: 14.4s.
- No DNS error, retry storm, terminal queue delay, RAG query, web-search tool, or provider timeout appeared in this incident trace.
- Engine output did contain an unrelated deterministic bug warning: `_parse_earnings_date is not defined` for WDFC upcoming/recent earnings checks. It did not account for the five-minute delay.

### Current request-routing call chain

`Telegram inbound` → Hermes Atlas gateway → assemble/rebuild large Atlas system/session context → first GPT-5.6 Sol Pro call → SOUL/skill mandates fresh engine execution → terminal tool → `/Users/yasser/scripts/atlas_engine.py WDFC` → engine DB/provider helper calls → 14,026-character JSON result → automatic context compression/session split → second GPT-5.6 Sol Pro call → manually formatted response → gateway Telegram send.

Observed incident tool calls: one terminal call only. No RAG or web-search tool was invoked by Hermes. The engine internally fetched market/news/analyst/fundamental/indicator data.

## Available recent and cached data at request time

### Intraday report snapshots

Before the request at 14:12 UTC:

- Snapshot 84 at 13:46:49: WDFC Top Pick, 3/4, entry $288.00, now $294.12, RSI 81, momentum weak.
- Snapshot 85 at 13:56:00: WDFC BUY NOW, 4/4, around $294.87, gap +23.2%.
- Snapshot 86 at 14:06:28: WDFC BUY NOW, 4/4, entry $291.13, now $290.38, stop $275.22, RSI context present in the same run.

Snapshot 86 was **332 seconds (5m32s)** old when Professor asked.

### Signals

A fresh WDFC signal existed at 14:04:42, **438 seconds (7m18s)** old:

- `BUY`, 4/4
- entry `$291.13`
- stop `$275.22`
- RVOL `2.17`
- trend/relative-strength/volume/catalyst all passed

At 14:12:19 the conversational engine run wrote/returned:

- `BUY (Small)`, 3/4
- entry `$289.77`
- stop `$273.86`
- RVOL `2.27`
- relative strength changed to NO
- RSI `80.6649`
- momentum weak

The change from 4/4 to 3/4 within minutes demonstrates why freshness and conflict rules matter.

### Other sources

- Pending-entry cache: no current WDFC pending row exists now; a historical WDFC WAITING row existed July 6.
- Recent Telegram context: immediately prior conversation included full PENG engine/advisory analysis and already established the distinction between engine signal and operator action, but no reusable structured WDFC result.
- Provider cache: no active structured provider/engine-result cache for WDFC was found under the Atlas profile or production scripts. There are only model metadata caches and historical backup/cache artifacts.
- DB is the best current reusable source: `signals` + `report_snapshots`, with source timestamp and report SHA.

## Part B — WDFC deterministic path and gate results

### Exact deterministic function

`atlas_engine.analyze_ticker()` generated the raw label. At the incident timestamp, 3 satisfied pillars directly mapped to `BUY (Small)`.

Call chain:

`atlas_engine.py::__main__` → `analyze_ticker(WDFC)` → pillar helpers → 3/4 label → optional indicator/fundamental/analyst metadata → JSON.

For scheduled reports:

`atlas_intraday.run_intraday()` → `atlas_manage.run()` → `_analyze_ticker_worker()` → `atlas_engine.analyze_ticker()` → `atlas_portfolio.consider_buy()` → report reconstruction in `atlas_intraday.py`.

### Incident gate matrix

| Factor | Incident result | Current classification |
|---|---|---|
| Trend Stack | PASS | Hard pillar |
| Relative Strength | FAIL at 14:12; had passed at 14:04 | Hard pillar, but 3/4 still maps to BUY Small |
| Volume | PASS, RVOL 2.27 | Hard pillar |
| Catalyst | PASS | Hard pillar; analyst/news can satisfy it |
| RSI 80.66 | Overbought | Indicator/report context only; not a raw signal veto |
| Momentum weak | True | Warning/quality field; explicitly allowed, not a BUY veto |
| Gap ~22% | Extended | Not a core-pillar veto; only some breakout/portfolio extension paths enforce it |
| Analyst target $305 | Only +5.26% upside from $289.77 | Catalyst metadata; no minimum analyst-target upside gate |
| Downside to TFE stop | 5.49% | Risk card; no conversational minimum reward/risk gate |
| Analyst target reward/risk | ~0.96:1 | Absent as a decision gate |
| Too Hot | Report showed `TOO HOT (0)` | Hard only when extension state is successfully propagated/reconstructed; not a raw 3/4 signal gate |

### Relative-strength inconsistency

This was time-sensitive, not necessarily nondeterministic:

- 13:54 and 14:04 rows: relative strength YES; WDFC was 4/4 BUY.
- 14:12 row: relative strength NO; WDFC became 3/4 BUY Small.

The current label still remained bullish because 3/4 automatically qualifies. The operator-facing response did not explain that a pillar had just deteriorated within eight minutes.

### Why the answer was unsafe/contradictory

The final prose contained the correct cautionary facts but used the wrong authority structure:

1. It opened with `WDFC — BUY (Small)`, visually presenting an action.
2. It then showed RSI 81, weak momentum, +22% gap, and poor target headroom.
3. It ended with `do not chase` and `wait`.

Thus `BUY` and `do not buy now` coexist because the product currently treats the TFE classification as both a technical label and a practical recommendation. The LLM did not silently alter the TFE label—which is correct—but it also did not clearly state that the operator action overrides immediate execution while leaving TFE unchanged.

The correct formulation was available from the same facts:

> TFE QUALIFIES: BUY Small. ACTION NOW: WAIT / DO NOT CHASE. RECHECK: stabilization, pullback, or a fresh engine run after material price movement.

### Renderer exposure

Confirmed:

- TOP PICKS is reconstructed from current-cycle raw BUY signal rows, not only from portfolio-approved buys.
- The report repeatedly promoted WDFC as a Top Pick while simultaneously displaying `RSI 81` and `Momentum Weak`.
- BUY NOW requires 4/4 and has more extension checks, but WDFC appeared in BUY NOW at 13:56 and 14:06 despite a +23% gap and `TOO HOT (0)`.
- Later 3/4 rows moved WDFC to TOP PICKS, where the contradiction remained.
- The top-pick suppression path does not reliably consume the same momentum/extension state it displays.

### Similar recent exposure

Current DB evidence shows WDFC is the clearest confirmed recent example:

- 14 WDFC BUY-family signals from 13:39–15:24.
- 12 were BUY Small; 2 were BUY.
- 10 BUY-family rows had relative strength NO.
- Price fell from the high-$290s into the low-$270s while WDFC remained 3/4 BUY Small and continued to be promoted as a Top Pick with RSI 81/momentum weak.

The architecture exposes any ticker with a technically qualifying 3/4/4/4 row plus practical quality warnings, even if WDFC is the only confirmed recent relative-strength-fail cluster in the audited window. Normal recent Top Picks such as ELV also displayed momentum-weak warnings, proving this is a class-level presentation issue, not ticker-specific hindsight.

## Part C — conversational routing assessment

### Exact SOUL/skill constraints causing rigidity

Atlas SOUL:

- `SOUL.md:5`: MUST run `python3 .../atlas_engine.py TICKER` for **EVERY ticker analysis**.
- `SOUL.md:12`: format results exactly according to the Telegram card.
- `SOUL.md:13`: no conversational fluff/bias; exact card only.

Atlas trading skill:

- `SKILL.md:18-21`: ticker question → fresh engine command → exact card/no fluff.
- `SKILL.md:192`: for stale-signal challenges, fresh engine truth is required.
- `SKILL.md:120-136`: canonical card leads with `[TICKER] - [SIGNAL]` and has no separate advisory-action field.

These rules correctly prevent invented numbers, but they collapse every query type into full deterministic analysis and make the raw signal visually dominant.

### Recommended two-layer query classifier

#### 1. Deterministic analysis mode

Force a fresh TFE run when any is true:

- No structured result exists.
- Professor asks for current score, pillars, price, entry, stop, target, RSI, MACD, RVOL, signal, or exact numbers.
- Cached result exceeds TTL.
- Current quote moved beyond the price invalidation threshold.
- Latest report and latest signal conflict.
- Catalyst/news state changed.
- Regime changed.
- Professor explicitly says `rerun`, `fresh`, `current`, or equivalent.

TFE remains authoritative for all deterministic numbers and raw BUY/AVOID qualification.

#### 2. Conversational confirmation mode

Use a fresh structured result without re-running when Professor asks a follow-up such as:

- “Would you buy it now?”
- “Is that still sensible?”
- “Should I chase?”
- “What is the risk?”

This mode must:

- quote exact cached TFE numbers and timestamps;
- perform no recalculation of TFE fields;
- optionally obtain targeted current news/current quote when needed;
- assess act-now suitability;
- separate raw classification from operator action;
- trigger deterministic mode if freshness/conflict rules fail.

The WDFC question “is a buy?” is ambiguous and should be classified as **operator action requested**. If a result is fresh, answer in conversational confirmation mode; if not, rerun TFE, then still produce the separated advisory contract.

## Part D — freshness and invalidation policy

Recommended initial evidence-based rules for staging—not production policy yet:

### Market-hours TTL

- **Structured TFE signal TTL: 5 minutes** during regular market hours.
- **Follow-up conversational TTL: 3 minutes** for act-now advice if the result was generated during a volatile gap/breakout condition.
- **Pre/post-market TTL: 15 minutes**, but force rerun at regular-session open.
- Never reuse a prior-day result for act-now advice.

Rationale: WDFC changed from 4/4 to 3/4 within 7m37s and moved materially. Five minutes would have made snapshot 86 borderline/stale at request time and forced either a lightweight current-price invalidation check or a fresh run.

### Price-movement invalidation

Rerun if either:

- absolute move from result price ≥ **1.0%** during regular hours; or
- move ≥ **0.25 ATR**; or
- price crosses the stored entry, stop, target, gap-breakout level, EMA trigger, or relative-strength boundary.

For unusually extended/gap names, use the stricter of 1% and 0.25 ATR.

### Catalyst/news invalidation

Rerun if:

- a new earnings release/guidance item, analyst action/target, FDA/regulatory item, merger/legal event, or materially new company headline appears after `generated_at`;
- prior catalyst was `unknown`, failed, or produced an error;
- the result's catalyst source date changes.

### Regime invalidation

Rerun when the stored regime differs from the latest regime snapshot or when a `RISK_ON ↔ RISK_OFF/CAUTION` transition occurs. Annotation-only macro changes may refresh advisory text without altering TFE numbers, but any deterministic gate input change requires TFE.

### Conflicting snapshots

- Never silently choose one.
- Authoritative deterministic result: **newest successfully completed full TFE result with complete provenance**, provided it passes TTL and invalidation checks.
- `signals` is authoritative for raw score/pillars at its timestamp.
- `report_snapshots` is authoritative only for what Professor was shown, not for current TFE truth.
- Pending pullbacks are order/watch state, not current signal truth.
- Recent Telegram prose is never numeric authority.
- If two fresh sources disagree, disclose conflict and rerun TFE.

### Cache design

Add a read-only structured sidecar/result envelope, not a second scoring engine:

```json
{
  "ticker": "WDFC",
  "generated_at": "...",
  "market_session": "regular",
  "source": "atlas_engine.analyze_ticker",
  "source_sha256": "...",
  "signal_id": 33645,
  "report_snapshot_id": 87,
  "price_at_analysis": 289.77,
  "raw_tfe": {"signal": "BUY Small", "score": "3/4", "entry": 289.77, "stop": 273.86},
  "context": {"rsi": 80.66, "momentum_weak": true, "gap_pct": 22.0},
  "freshness": {"ttl_seconds": 300, "invalidation_reasons": []}
}
```

The LLM may consume but never modify this envelope.

## Part E — operator-facing safety contract

This can be implemented entirely in the operator-facing orchestration/prompt layer without changing TFE scoring.

Required response schema:

1. **TFE CLASSIFICATION** — exact signal, score, timestamp, source.
2. **ACTION NOW** — `BUY NOW`, `WAIT`, `DO NOT CHASE`, `AVOID`, or `REVIEW`; advisory only.
3. **WHY** — explicit facts from the deterministic envelope and targeted news.
4. **RECHECK CONDITION** — precise invalidation/re-entry condition.
5. **DATA FRESHNESS** — age and whether a fresh run occurred.

WDFC replay target:

> **TFE QUALIFIES:** BUY Small (3/4) at $289.77; stop $273.86.  
> **ACTION NOW:** WAIT — DO NOT CHASE.  
> **WHY:** +22% gap, RSI 81, weak momentum, relative strength failed, analyst target upside 5.3% versus 5.5% downside to the TFE stop.  
> **RECHECK:** stabilization/consolidation, pullback that improves reward/risk, or a fresh TFE run after material price/news change.

The conversational layer must not rewrite `BUY Small` to `AVOID`; it supplies a separate action judgment.

## Files/configuration likely requiring staged changes

No changes were made. Likely future staged scope:

- `/Users/yasser/.hermes/profiles/atlas/SOUL.md` — replace unconditional every-query engine execution with query classification while preserving deterministic authority.
- `/Users/yasser/.hermes/profiles/atlas/skills/atlas_trading/SKILL.md` — add two-layer routing, freshness envelope, and advisory contract.
- A new unprotected operator-facing module such as `/Users/yasser/scripts/atlas_conversation_router.py` — read-only classifier/cache resolver; no trading writes.
- Optional read-only DB helper in `/Users/yasser/scripts/atlas_db.py` to retrieve latest complete signal/report envelope without writes.
- Atlas gateway/session operational config: reduce runaway per-chat context or proactively start a fresh session before compression thresholds. This is Hermes configuration work and must be staged/approved separately.
- `/Users/yasser/scripts/atlas_intraday.py` report renderer may need a separate future staging work order to prevent raw technically-qualified but practically unbuyable rows from being called TOP PICKS/BUY NOW. That is report-layer behavior, not necessarily a TFE strategy change.

## Focused staging plan

### Stage 0 — evidence fixtures

Under `/tmp/p0_conversational_advisory_v1/` create immutable JSON fixtures from:

- Exact WDFC incident engine result.
- Pre-request report snapshot 86 and signals 33609/33645.
- A large-gap/high-RSI/momentum-weak case.
- Weak analyst-target reward/risk case.
- A normal unextended valid BUY.
- A stale result.
- A conflicting report-vs-signal case.

No production DB writes; production DB opened `mode=ro` only.

### Stage 1 — pure query classifier

Test deterministic vs conversational mode for:

- first ticker question;
- exact-number request;
- fresh follow-up;
- stale cache;
- material price move;
- new catalyst;
- regime change;
- source conflict.

### Stage 2 — immutable provenance envelope

- Validate schema.
- Hash exact TFE payload.
- Reject altered/missing numeric fields.
- Ensure response numbers are byte-for-byte sourced from envelope.
- Never infer stop/target/RSI/RVOL.

### Stage 3 — advisory contract renderer

Replay WDFC and assert:

- raw TFE label remains `BUY Small`;
- `ACTION NOW=WAIT/DO NOT CHASE`;
- no phrase implies immediate purchase;
- reward/risk and warnings are clearly explained;
- recheck condition is present.

Additional cases:

- gap chase;
- overbought RSI;
- weak reward/risk;
- momentum weak;
- normal valid buy where action may remain BUY NOW;
- AVOID signal (operator layer cannot promote it to BUY).

### Stage 4 — latency and context tests

Measure:

- prompt/system/session character and token estimates;
- first-model latency;
- cache lookup latency;
- engine/provider calls by family and duration;
- final-generation latency;
- compression incidence.

Acceptance targets:

- fresh cached follow-up, no engine call: p95 < **5s** excluding Telegram transport;
- forced fresh single-ticker TFE: p95 < **30s** under healthy providers;
- zero automatic compression in a ticker follow-up;
- prompt size bounded below an agreed threshold; context over threshold triggers a controlled fresh session, not an in-turn 5-minute compression.

### Stage 5 — no-side-effect proof

- Telegram sender mocked/blocked.
- Production DB SHA/counts before/after unchanged.
- Copy DB read-only where possible.
- No `log_signal`, pending-pullback, trade, cash, handoff, or report-snapshot writes.
- No scoring, BUY/AVOID, stop, target, Too Hot, sizing, or broker changes.
- Production SOUL/skill/config SHAs unchanged.

## Strategy changes requiring separate Professor approval

The operator-facing two-layer design does **not** require a strategy change.

Separate approval would be required for any of these:

- making RSI a TFE hard gate;
- making momentum weakness a hard veto;
- introducing a minimum reward/risk gate;
- changing gap/extension or Too Hot thresholds;
- changing 3/4 → BUY Small mapping;
- changing relative-strength definition;
- changing analyst-target use in scoring;
- suppressing deterministic BUY labels inside TFE.

Those are Fat Engine/strategy changes and are out of scope for this read-only investigation.

## Production-touch verification

- No code, SOUL, skill, DB, cache, schedule, gateway, or Telegram configuration was modified.
- No engine command was executed during this investigation.
- Production DB was read via SQLite read-only mode.
- Production DB SHA during evidence capture: `2f28523d7b9af9376a9dd3898561123c1c0e721315b2607a444993dff295e485`; final verification SHA: `0a6657741ed5fc7e3f89c70a51f60730f6b9fc2296393cd813f90854d61a5e81`. The drift came from normal scheduled Atlas activity while this read-only investigation ran, not from AtlasOps.
- Atlas SOUL SHA: `52a8442bc560fa0626ae761741a3d56670aeea23d693f697fad8f2a13ab74324`.
- Atlas trading skill SHA: `9fbb9e34d5c13ba7f0d714c4d5e939d998972fbad30bc8db5ac322be2d44d240`.

**production touched = NO**
