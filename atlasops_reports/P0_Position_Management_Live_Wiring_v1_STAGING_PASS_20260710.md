# Position Management Live Wiring v1 — Staging-Only Shadow Review

## Status

- **STATUS = PASS**
- **production touched = NO**
- Staging path: `/tmp/p0_position_management_live_wiring_v1/`
- `shadow_ready = YES`
- `deployment_ready = NO`
- Reviews are advisory-only; no canonical stop/target/trade/cash/broker mutation occurred.

## Provider wiring map

- Current price: latest completed Massive intraday aggregate.
- Daily and 30-minute bars since entry: Massive adjusted aggregates through `atlas_provider_guard.massive_get_json()` with bounded timeout/retry.
- ATR/EMA/high-low/MFE/MAE/giveback/swing/trend/RVOL: deterministic local `Decimal` Python over sourced bars.
- Catalyst: Massive `/v2/reference/news`; source timestamps retained. Missing catalyst returns INCOMPLETE rather than invention.
- Earnings: Massive-hosted Benzinga earnings; identified EODHD fundamentals fallback only where needed.
- Sector: Massive ticker details mapped to Massive sector ETF bars; EODHD is the identified fallback.
- Regime: Massive SPY daily bars.
- Yahoo: not used.

Provider call latency: min `814.792 ms`, max `3736.469 ms`, 29 timed calls. The first catalyst endpoint attempt returned HTTP 404 and was replaced in staging with the existing approved Massive reference-news path; no silent fallback occurred. LASR returned no current catalyst row and therefore fails closed as INCOMPLETE.

## Threshold discipline

All thresholds are explicitly **TEST-ONLY**, not production policy: ATR `[2.0,2.5,3.0]`; EMA/swing buffers `[0.5%,1.0%,1.5%]`; breakeven R `[1.0,1.5,2.0]`; giveback `[25%,35%,50%]`; time review `[10,15,20]`; extension RVOL `[1.2,1.5]`, ATR/price `[6%,8%]`, forward R/R `[1.5,2.0]`. No optimality claim is made from limited Atlas history.

## SYNA

**STATUS:** TIGHTEN

**OLD STOP:** $113.35  
**PROPOSED NEW STOP:** $125.98  
**STOP METHOD:** EMA_BUFFER

**METHOD CANDIDATES:**
  - CURRENT_STOP: 113.35 — VALID — canonical floor
  - BREAKEVEN: INCOMPLETE — INCOMPLETE — requires configured TEST-ONLY MFE/R trigger
  - ATR_CHANDELIER: 112.91 — REJECTED_WIDENING — highest price minus TEST-ONLY ATR multiple
  - EMA_BUFFER: 125.98 — VALID — EMA20 less TEST-ONLY buffer
  - CONFIRMED_SWING_LOW_BUFFER: 114.82 — VALID — confirmed swing low less TEST-ONLY buffer
  - PEAK_PROFIT_PROTECTION: 132.52 — REJECTED_AT_OR_ABOVE_PRICE — locks TEST-ONLY fraction after giveback trigger
  - HYBRID_STRONGEST_VALID: 125.98 — VALID — highest valid non-widening candidate

**OLD TARGET:** $156.61  
**PROPOSED NEW TARGET:** $156.61  
**TARGET DECISION:** KEEP  
**TARGET EVIDENCE:** `{"acceptable_forward_reward_risk": true, "acceptable_volatility": false, "confirmed_breakout": false, "sustained_volume": false, "trend_continuation": false, "valid_catalyst": false}`

**CURRENT STATE:** Price $126.74; gain/loss $2.37 (0.0024); highest $135.79; highest close $129.50; lowest $115.98; MFE $9.35; MAE $10.46; peak gain $73.95; giveback $71.58 (0.9679); ATR $9.15; EMA10/20/50 $125.67/$127.25/$119.05; swing low 115.98; RVOL 0.6437; trend MIXED; catalyst STALE; next earnings 2026-11-05; sector SEMICONDUCTORS & RELATED DEVICES (STRONG); regime RISK-ON; holding sessions 10.

**WHY:** TIGHTEN, TEST_ONLY_THRESHOLDS, KEEP  
**RECHECK:** next after-close review or candidate trigger crossing  
**DATA FRESHNESS:** VERIFIED; missing `none`. Full field-level provider timestamps are in `output/live_shadow.json`.

**SENSITIVITY:** `[{"policy": "ATR_CHANDELIER", "threshold": "2.0", "value": "117.48"}, {"policy": "ATR_CHANDELIER", "threshold": "2.5", "value": "112.91"}, {"policy": "ATR_CHANDELIER", "threshold": "3.0", "value": "108.33"}, {"policy": "EMA_BUFFER", "threshold": "0.005", "value": "126.62"}, {"policy": "EMA_BUFFER", "threshold": "0.010", "value": "125.98"}, {"policy": "EMA_BUFFER", "threshold": "0.015", "value": "125.34"}]`  
**POLICY AGREEMENT:** CONFIRMED_SWING_LOW_BUFFER, CURRENT_STOP, EMA_BUFFER.

## BAC

**STATUS:** TIGHTEN

**OLD STOP:** $57.11  
**PROPOSED NEW STOP:** $57.98  
**STOP METHOD:** ATR_CHANDELIER

**METHOD CANDIDATES:**
  - CURRENT_STOP: 57.11 — VALID — canonical floor
  - BREAKEVEN: INCOMPLETE — INCOMPLETE — requires configured TEST-ONLY MFE/R trigger
  - ATR_CHANDELIER: 57.98 — VALID — highest price minus TEST-ONLY ATR multiple
  - EMA_BUFFER: 57.02 — REJECTED_WIDENING — EMA20 less TEST-ONLY buffer
  - CONFIRMED_SWING_LOW_BUFFER: 57.72 — VALID — confirmed swing low less TEST-ONLY buffer
  - PEAK_PROFIT_PROTECTION: INCOMPLETE — INCOMPLETE — locks TEST-ONLY fraction after giveback trigger
  - HYBRID_STRONGEST_VALID: 57.98 — VALID — highest valid non-widening candidate

**OLD TARGET:** $60.62  
**PROPOSED NEW TARGET:** $60.62  
**TARGET DECISION:** KEEP  
**TARGET EVIDENCE:** `{"acceptable_forward_reward_risk": false, "acceptable_volatility": true, "confirmed_breakout": false, "sustained_volume": false, "trend_continuation": true, "valid_catalyst": true}`

**CURRENT STATE:** Price $59.60; gain/loss $21.92 (0.0438); highest $60.83; highest close $59.90; lowest $56.84; MFE $3.73; MAE $0.26; peak gain $32.62; giveback $10.70 (0.3279); ATR $1.14; EMA10/20/50 $58.71/$57.60/$55.19; swing low 58.30; RVOL 0.6121; trend ALIGNED_UP; catalyst FRESH; next earnings 2026-10-14; sector NATIONAL COMMERCIAL BANKS (STRONG); regime RISK-ON; holding sessions 8.

**WHY:** TIGHTEN, TEST_ONLY_THRESHOLDS, KEEP  
**RECHECK:** next after-close review or candidate trigger crossing  
**DATA FRESHNESS:** VERIFIED; missing `none`. Full field-level provider timestamps are in `output/live_shadow.json`.

**SENSITIVITY:** `[{"policy": "ATR_CHANDELIER", "threshold": "2.0", "value": "58.55"}, {"policy": "ATR_CHANDELIER", "threshold": "2.5", "value": "57.98"}, {"policy": "ATR_CHANDELIER", "threshold": "3.0", "value": "57.41"}, {"policy": "EMA_BUFFER", "threshold": "0.005", "value": "57.31"}, {"policy": "EMA_BUFFER", "threshold": "0.010", "value": "57.02"}, {"policy": "EMA_BUFFER", "threshold": "0.015", "value": "56.74"}]`  
**POLICY AGREEMENT:** ATR_CHANDELIER, CONFIRMED_SWING_LOW_BUFFER, CURRENT_STOP.

## ABNB

**STATUS:** TIGHTEN

**OLD STOP:** $135.96  
**PROPOSED NEW STOP:** $142.04  
**STOP METHOD:** EMA_BUFFER

**METHOD CANDIDATES:**
  - CURRENT_STOP: 135.96 — VALID — canonical floor
  - BREAKEVEN: INCOMPLETE — INCOMPLETE — requires configured TEST-ONLY MFE/R trigger
  - ATR_CHANDELIER: 138.32 — VALID — highest price minus TEST-ONLY ATR multiple
  - EMA_BUFFER: 142.04 — VALID — EMA20 less TEST-ONLY buffer
  - CONFIRMED_SWING_LOW_BUFFER: 139.83 — VALID — confirmed swing low less TEST-ONLY buffer
  - PEAK_PROFIT_PROTECTION: INCOMPLETE — INCOMPLETE — locks TEST-ONLY fraction after giveback trigger
  - HYBRID_STRONGEST_VALID: 142.04 — VALID — highest valid non-widening candidate

**OLD TARGET:** $157.17  
**PROPOSED NEW TARGET:** $157.17  
**TARGET DECISION:** KEEP  
**TARGET EVIDENCE:** `{"acceptable_forward_reward_risk": false, "acceptable_volatility": true, "confirmed_breakout": false, "sustained_volume": false, "trend_continuation": true, "valid_catalyst": true}`

**CURRENT STATE:** Price $148.50; gain/loss $114.73 (0.0382); highest $150.07; highest close $148.93; lowest $141.24; MFE $7.04; MAE $1.79; peak gain $147.66; giveback $32.93 (0.2230); ATR $4.70; EMA10/20/50 $145.95/$143.48/$140.45; swing low 141.24; RVOL 0.6870; trend ALIGNED_UP; catalyst FRESH; next earnings 2026-08-06; sector SERVICES-TO DWELLINGS & OTHER BUILDINGS (STRONG); regime RISK-ON; holding sessions 8.

**WHY:** TIGHTEN, TEST_ONLY_THRESHOLDS, KEEP  
**RECHECK:** next after-close review or candidate trigger crossing  
**DATA FRESHNESS:** VERIFIED; missing `none`. Full field-level provider timestamps are in `output/live_shadow.json`.

**SENSITIVITY:** `[{"policy": "ATR_CHANDELIER", "threshold": "2.0", "value": "140.67"}, {"policy": "ATR_CHANDELIER", "threshold": "2.5", "value": "138.32"}, {"policy": "ATR_CHANDELIER", "threshold": "3.0", "value": "135.97"}, {"policy": "EMA_BUFFER", "threshold": "0.005", "value": "142.76"}, {"policy": "EMA_BUFFER", "threshold": "0.010", "value": "142.04"}, {"policy": "EMA_BUFFER", "threshold": "0.015", "value": "141.32"}]`  
**POLICY AGREEMENT:** ATR_CHANDELIER, CONFIRMED_SWING_LOW_BUFFER, CURRENT_STOP, EMA_BUFFER.

## PENG

**STATUS:** HOLD

**OLD STOP:** $75.71  
**PROPOSED NEW STOP:** $75.71  
**STOP METHOD:** CURRENT_STOP

**METHOD CANDIDATES:**
  - CURRENT_STOP: 75.71 — VALID — canonical floor
  - BREAKEVEN: INCOMPLETE — INCOMPLETE — requires configured TEST-ONLY MFE/R trigger
  - ATR_CHANDELIER: 66.03 — REJECTED_WIDENING — highest price minus TEST-ONLY ATR multiple
  - EMA_BUFFER: 67.34 — REJECTED_WIDENING — EMA20 less TEST-ONLY buffer
  - CONFIRMED_SWING_LOW_BUFFER: INCOMPLETE — INCOMPLETE — confirmed swing low less TEST-ONLY buffer
  - PEAK_PROFIT_PROTECTION: 84.90 — REJECTED_AT_OR_ABOVE_PRICE — locks TEST-ONLY fraction after giveback trigger
  - HYBRID_STRONGEST_VALID: 75.71 — VALID — highest valid non-widening candidate

**OLD TARGET:** $100.01  
**PROPOSED NEW TARGET:** $100.01  
**TARGET DECISION:** KEEP  
**TARGET EVIDENCE:** `{"acceptable_forward_reward_risk": true, "acceptable_volatility": false, "confirmed_breakout": false, "sustained_volume": true, "trend_continuation": true, "valid_catalyst": true}`

**CURRENT STATE:** Price $78.45; gain/loss $72.66 (0.0363); highest $89.86; highest close $81.39; lowest $63.76; MFE $14.16; MAE $11.94; peak gain $374.11; giveback $301.45 (0.8058); ATR $9.53; EMA10/20/50 $71.95/$68.02/$55.96; swing low None; RVOL 1.5014; trend ALIGNED_UP; catalyst FRESH; next earnings 2026-10-06; sector SEMICONDUCTORS & RELATED DEVICES (STRONG); regime RISK-ON; holding sessions 3.

**WHY:** HOLD, TEST_ONLY_THRESHOLDS, KEEP  
**RECHECK:** next after-close review or candidate trigger crossing  
**DATA FRESHNESS:** VERIFIED; missing `none`. Full field-level provider timestamps are in `output/live_shadow.json`.

**SENSITIVITY:** `[{"policy": "ATR_CHANDELIER", "threshold": "2.0", "value": "70.80"}, {"policy": "ATR_CHANDELIER", "threshold": "2.5", "value": "66.03"}, {"policy": "ATR_CHANDELIER", "threshold": "3.0", "value": "61.27"}, {"policy": "EMA_BUFFER", "threshold": "0.005", "value": "67.68"}, {"policy": "EMA_BUFFER", "threshold": "0.010", "value": "67.34"}, {"policy": "EMA_BUFFER", "threshold": "0.015", "value": "67.00"}]`  
**POLICY AGREEMENT:** CURRENT_STOP.

## LASR

**STATUS:** INCOMPLETE

**OLD STOP:** $66.94  
**PROPOSED NEW STOP:** $66.94  
**STOP METHOD:** CURRENT_STOP

**METHOD CANDIDATES:**
  - CURRENT_STOP: 66.94 — VALID — canonical floor
  - BREAKEVEN: INCOMPLETE — INCOMPLETE — requires configured TEST-ONLY MFE/R trigger
  - ATR_CHANDELIER: 60.92 — REJECTED_WIDENING — highest price minus TEST-ONLY ATR multiple
  - EMA_BUFFER: 66.06 — REJECTED_WIDENING — EMA20 less TEST-ONLY buffer
  - CONFIRMED_SWING_LOW_BUFFER: INCOMPLETE — INCOMPLETE — confirmed swing low less TEST-ONLY buffer
  - PEAK_PROFIT_PROTECTION: 76.14 — REJECTED_AT_OR_ABOVE_PRICE — locks TEST-ONLY fraction after giveback trigger
  - HYBRID_STRONGEST_VALID: 66.94 — VALID — highest valid non-widening candidate

**OLD TARGET:** $106.68  
**PROPOSED NEW TARGET:** INCOMPLETE  
**TARGET DECISION:** INCOMPLETE  
**TARGET EVIDENCE:** `{"acceptable_forward_reward_risk": true, "acceptable_volatility": false, "confirmed_breakout": false, "sustained_volume": false, "trend_continuation": false, "valid_catalyst": false}`

**CURRENT STATE:** Price $72.00; gain/loss $-133.69 (-0.0477); highest $76.43; highest close $74.71; lowest $60.12; MFE $0.82; MAE $15.49; peak gain $30.37; giveback $164.05 (5.4024); ATR $6.20; EMA10/20/50 $66.57/$66.73/$69.90; swing low None; RVOL 1.1125; trend MIXED; catalyst INCOMPLETE; next earnings 2026-11-05; sector SEMICONDUCTORS & RELATED DEVICES (STRONG); regime RISK-ON; holding sessions 2.

**WHY:** INCOMPLETE, TEST_ONLY_THRESHOLDS, INCOMPLETE, CATALYST_FRESHNESS  
**RECHECK:** next after-close review or candidate trigger crossing  
**DATA FRESHNESS:** INCOMPLETE; missing `CATALYST_FRESHNESS`. Full field-level provider timestamps are in `output/live_shadow.json`.

**SENSITIVITY:** `[{"policy": "ATR_CHANDELIER", "threshold": "2.0", "value": "64.02"}, {"policy": "ATR_CHANDELIER", "threshold": "2.5", "value": "60.92"}, {"policy": "ATR_CHANDELIER", "threshold": "3.0", "value": "57.82"}, {"policy": "EMA_BUFFER", "threshold": "0.005", "value": "66.40"}, {"policy": "EMA_BUFFER", "threshold": "0.010", "value": "66.06"}, {"policy": "EMA_BUFFER", "threshold": "0.015", "value": "65.73"}]`  
**POLICY AGREEMENT:** CURRENT_STOP.

## Tests and invariants

- `py_compile` all staged Python: PASS.
- Six focused tests: **6/6 PASS**.
- Production DB opened URI `mode=ro` with `query_only=ON`; zero SQL writes.
- Same-input rerun: byte-identical JSON.
- Stop widening and stop-at/above-price: always rejected.
- Stale/missing packet fixture: INCOMPLETE with no invented stop/target.
- High-water regression fixture: prior maximum preserved.
- Every review carries provider, source timestamps, freshness, input digest, method evidence, and TEST-ONLY threshold set.
- Telegram sends `0`; broker actions `0`; canonical writes `0`.
- Reconciled authority: PENG one OPEN lot; LASR shadow stop `66.94`; RL OPEN lot count `0`.
- Production DB SHA remained `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`; integrity `ok`; FK clean; complete counts unchanged during the staging run.
- Production stops/targets/status for all five OPEN trades remain unchanged.
- Production source targets are Git-clean; Intraday Advisory Authority SHAs remain `8094a472...`, `25715b07...`, `c19c84ab...`.

## Files and SHA256

- `/tmp/p0_position_management_live_wiring_v1/src/atlas_position_management.py` — `b141095f72a48dec3bc0b32ac7537fc9074e568f9e6e006e5e59c41dcad88751`
- `/tmp/p0_position_management_live_wiring_v1/src/atlas_provider_guard.py` — `105d47cb32ecc12eb88d1236fbb358c7a4d80c07e46083bff1de8465162740a2`
- `/tmp/p0_position_management_live_wiring_v1/src/live_shadow_review.py` — `4050b9d30ea9f72fff0920f61b91fe37c815706844af5aad1b7dfd83379c17b3`
- `/tmp/p0_position_management_live_wiring_v1/tests/test_live_shadow.py` — `48630520762c5aed4ec20ce986512721edbe412ac25cc494cdb92dec6e2b918b`
- `/tmp/p0_position_management_live_wiring_v1/raw/live_packet.json` — `08e99fd18367f85ae939bfe88e9621e2a2c46d9495e3299680f4a0badb47ddb7`
- `/tmp/p0_position_management_live_wiring_v1/output/live_shadow.json` — `1fa73b696c39088ca7c67643fd9310e2179700c81acd5faf91093561e12054c5`
- `/tmp/p0_position_management_live_wiring_v1/output/live_shadow.md` — `4761d0e5e6ed50a96d67a7a3a876e1ad92a10a579a3b27d5961093a375af593f`
- `/tmp/p0_position_management_live_wiring_v1/output/test_results.txt` — `ba136685a7ebcd4811b298fc50506579598ac046838adec94eba9e29ec967457`
- `/tmp/p0_position_management_live_wiring_v1/output/final_evidence.json` — `19acbd3e67f1b9b9cc1d9cf1cf86799e0bb7292a706fc9536207bccd545b2b57`

## Remaining Professor approvals

1. Select or reject permanent stop-policy thresholds; all current proposals are TEST-ONLY.
2. Define permanent target-lowering and target-extension formulas. No numeric target is invented when extension/lowering evidence is incomplete.
3. Approve any future production integration, persistence/sidecar location, report rendering, scheduling, or canonical stop/target action separately.
4. Decide whether catalyst absence should remain a hard INCOMPLETE gate or allow a separately specified no-catalyst evidence policy.

`shadow_ready = YES`  
`deployment_ready = NO`
