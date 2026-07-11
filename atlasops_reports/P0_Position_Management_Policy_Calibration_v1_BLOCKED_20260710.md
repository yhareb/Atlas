# Position Management Policy Calibration v1 — Staging Evidence

## Status
- **STATUS = BLOCKED**
- **production touched = NO**
- Staging: `/tmp/p0_position_management_policy_calibration_v1/`
- `forward_shadow_ready = NO`
- `deployment_ready = NO`
- Blocker: only 8 defensible canonical outcomes; chronological train/validation/OOS samples are 3/4/1.

## Expanded dataset
- Canonical broker-confirmed closed: 8.
- Anomalies kept separate: 4 — AAPL/PBXT/IBXT zero-duration artifacts and TSM’s documented wrong-target early exit.
- OPEN positions: 5, forward-shadow only.
- FILLED pullbacks: 22, separate and never called broker fills.
- Signals: 36,129 across 740 tickers; bounded ticker/day de-dup cohort: 2,099, never treated as fills or blended into canonical results.

## Replay methodology
Day-t decisions see completed bars strictly before t; swing lows require right-side confirmation. Chronological thirds were used. Costs are 10 bps entry, 10 bps exit, 5 bps stop slippage; gaps execute at the opening price less slippage. Same-bar stop/target ambiguity is resolved stop-first. Persisted, ATR, EMA, swing, giveback/breakeven, and hybrid stops were compared with original and R-multiple targets. Full policy/family/split/ticker metrics are in `output/calibration.json`.

## Provisional candidates

### Conservative
- ATR 2.0; EMA/swing buffer 0.5%; giveback 25%; review 10 sessions; target 1.5R.
- n=8: net −0.77%; expectancy +0.22%; PF 1.075; max DD 16.54%; average winner +12.85%; average loser −3.98%; MFE captured 22.02%; whipsaw 62.5%; target/stop hit 25%/75%; average hold 2.13 sessions.
- Train/validation/OOS PF: 3.808 / 0.692 / 0.000.

### Balanced
- ATR 2.5; EMA/swing buffer 1.0%; giveback 35%; review 15 sessions; target 2R.
- n=8: net −0.59%; expectancy +0.26%; PF 1.087; max DD 16.54%; average winner +12.99%; average loser −3.98%; MFE captured 21.55%; whipsaw 62.5%; target/stop hit 0%/75%; average hold 2.13 sessions.
- Train/validation/OOS PF: 4.223 / 0.596 / 0.000.

### Trend-following
- ATR 3.0; EMA/swing buffer 1.5%; giveback 50%; review 20 sessions; target 3R.
- n=8: net −0.59%; expectancy +0.26%; PF 1.087; max DD 16.54%; average winner +12.99%; average loser −3.98%; MFE captured 21.55%; whipsaw 50%; target/stop hit 0%/75%; average hold 2.50 sessions.
- Train/validation/OOS PF: 4.223 / 0.596 / 0.000.

All three fail validation/OOS. None is calibrated or optimal. If a longer bake is separately authorized, Balanced is only the middle-parameter research candidate—not an approved policy. Suggested evidence gate: at least 50 mechanically valid candidates and preferably 30 canonical completed outcomes.

## Current OPEN outputs — PROVISIONAL SHADOW ONLY

### SYNA
- Conservative: stop $113.35 → $126.44; target $156.61 → $146.075; ACTION PROTECT PROFIT.
- Balanced: stop $113.35 → $126.44; target $156.61 → $152.62; ACTION PROTECT PROFIT.
- Trend-following: stop $113.35 → $126.44; target $156.61 → $165.71; ACTION PROTECT PROFIT.

### BAC
- Conservative: stop $57.11 → $58.0085; target $60.62 → INCOMPLETE; ACTION PROTECT PROFIT.
- Balanced: stop $57.11 → $57.717; target $60.62 → INCOMPLETE; ACTION TIGHTEN.
- Trend-following: stop $57.11 → $57.4255; target $60.62 → INCOMPLETE; ACTION TIGHTEN.

### ABNB
- Conservative: stop $135.96 → $140.5338; target $157.17 → $153.635; ACTION TIGHTEN.
- Balanced: stop $135.96 → $139.8276; target $157.17 → $157.17; ACTION TIGHTEN.
- Trend-following: stop $135.96 → $139.1214; target $157.17 → $164.24; ACTION TIGHTEN.

### PENG
- All profiles: stop $75.71 → $75.71; target $100.01 → INCOMPLETE; ACTION PROTECT PROFIT.
- This directly challenges the prior HOLD despite major peak-profit giveback.

### LASR
- All profiles: stop $66.94 → INCOMPLETE; target $106.68 → INCOMPLETE; ACTION INCOMPLETE because catalyst freshness is missing.

Every row is advisory, non-persistent, timestamped in the raw JSON, and rechecked after close or when missing evidence becomes complete.

## Incident replays
- PENG, SYNA, BAC, ABNB, LASR: PASS named-position paths.
- WDFC earnings-gap reversal: PASS on 2026-07-10 bar O/H/L/C 292.093 / 298.899 / 261.4898 / 264.91.
- Volatility expansion/contraction, regime reversal, sector breakdown, gap-through-stop, and missing-evidence paths: PASS.
- PASS proves fixture execution and invariants, not profitable calibration.

## Sensitivity, safeguards, and tests
- Sweeps: ATR 2/2.5/3; buffers 0.5/1/1.5%; giveback 25/35/50%; review 10/15/20; targets 1.5/2/3R.
- Stop widening is rejected. Stops at/above current price become INCOMPLETE.
- Missing evidence fails closed; no target is invented.
- Same-input JSON and Markdown are byte-identical.
- `py_compile`: PASS; tests: 7/7 PASS.
- Telegram sends: 0; broker actions: 0; canonical writes: 0.
- Harness used the copied DB read-only. Production DB SHA remains `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`; integrity and FK checks are clean.

## Key artifacts and SHA256
- `src/calibrate.py` — `af7b877ba01b81a9a24998725ac080aca66b581745c7374b512b378464a419b1`
- `src/fetch_bars.py` — `df44b074880893fae6506e289e93b2717f47ae2fca5afb5c17453f7e1a678642`
- `tests/test_calibration.py` — `9bf1ac3937648c99a8d9e8b542f1671b46399f7385eeb7d0ab2514de8a12bfe7`
- `output/calibration.json` — `a1dbb8ec25fadd41b442bb6605e718c1cfccc47a2ad51dd4c12b9705d60c07e7`
- `cache/historical_daily_bars.json` — `b1ac5f00a2f692645d379317beb1e18161a38885789231f5876a279bba0f3a9d`
- `db/atlas_copy.db` — `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`

## Professor decisions required
1. Approve or reject a longer data-collection bake.
2. Set minimum sample gates for setup/sector/regime analysis.
3. Decide whether missing catalyst evidence blocks both stop and target advice or target only.
4. Any forward-shadow candidate requires separate approval.

`forward_shadow_ready = NO`

`deployment_ready = NO`
