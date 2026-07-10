# Deterministic Position Management Layer v1 — staging evidence

## Required return

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = NO**

Staging path:

`/tmp/p0_position_management_v1/`

No production source/config/SOUL/skill/schedule was modified. No production DB write was made. No process was restarted. No Telegram or broker path exists in the package.

`deployment_ready=NO` is deliberate: Phase 1 behavior is proven, but all policy thresholds are test-only and remain unapproved; the outputs use immutable synthetic evidence rather than a production-wired provider adapter; and current position-lot reconciliation defects intentionally fail closed.

---

# Files and SHA256

## Core source

- `src/atlas_position_management.py`
  - `b141095f72a48dec3bc0b32ac7537fc9074e568f9e6e006e5e59c41dcad88751`
- `src/position_management_replay.py`
  - `9eb7663f07f20c2afab5a26d8d399c54181ddf9584df60df11bc80c464d422db`

## Runners/tests

- `generate_outputs.py`
  - `57a971f53b180308a11bc3729603efeefaee83ba0a03a7b60b347700f4423e3f`
- `generate_sidecar.py`
  - final SHA listed in the generated manifest
- `tests/test_core.py`
  - `a5cc54f7e755c5696d047cca23bf162279fc12a734c42707e7ff279b828bd0a4`
- `tests/test_render_contract.py`
  - `5e19cfa6401b63ed36a9fd5dd532ea43fcc457296ec6491066cf8f8d7f534269`
- `tests/replay_test_harness.py`
  - `4fed367cd69382f914a7d40b051714fe52fe8e72510ca0265b25cecef9958949`

## Fixtures

- `fixtures/positions.json` — `903b669c8ed21bf305bb8b29137d136279f144bbdcdc7d69372c004b6b405036`
- `fixtures/bars.json` — `134ba1f054fcf68f46f5353a7c158e77cf92fcd20bb71cb2e24531e255ab3c54`
- `fixtures/replay_test_only_policies.json` — `fdffb8f32886d6b0127c31c264e815a1c5d09a7b602ad69189eea091f97f9d40`

## Generated output

- `output/SYNA.json` — `45969a64d36ab23f6760d034ec55707b612e6c3eea925d92d01dae55c2ecbb00`
- `output/BAC.json` — `b99d03bb8eed04b95833b27b178f3adbbcf34c45dea66d3d6dd6cfd340fee29e`
- `output/ABNB.json` — `7cb7c1524c35c88051a68e8a2b2f6c7def5227652c84c003840f2c87afb82294`
- `output/PENG.json` — `5217ffe78c0a8599612d142993e0bdfc5b94a232c3ab43d2faba4f4ce10f626f`
- `output/LASR.json` — `25f440236251f43edb60d407ce515105d94a3b001511006853e84ba6ccb4c11f`
- `output/WDFC.json` — `1ad2d623df39ae8150229f3ff62e30a87a53cb9bbb5f8647cb3bb9f27edaef1c`
- `output/replay.json` — `42efc38975c440256c03c5763049773bde56b616092c08c6ef1c4d9fd5ccc93e`

A final artifact manifest includes the sidecar and report-adjacent files.

---

# Deterministic architecture

## Package 1 — position-state calculator

`atlas_position_management.py` provides:

- canonical `trades` reader using SQLite `mode=ro` and `PRAGMA query_only=ON`;
- immutable original-plan reconstruction with explicit entry-time evidence precedence;
- current verified price and trading-session age;
- highest price/close and timestamps;
- lowest price and timestamp;
- MFE, MAE, MFE-R, MAE-R;
- peak/current open profit and giveback;
- ATR;
- EMA10, EMA20, EMA50;
- delayed confirmed swing low without lookahead;
- trend state;
- catalyst freshness;
- earnings proximity;
- sector state;
- market regime;
- volatility state;
- per-source timestamps, received-at time, input digest, and provenance.

Missing provider evidence means no `TechnicalState`; output becomes `INCOMPLETE`.

## Package 2 — advisory policy engine

Exact candidates:

1. `CURRENT_STOP`
2. `BREAKEVEN`
3. `ATR_CHANDELIER`
4. `EMA_BUFFER`
5. `CONFIRMED_SWING_LOW_BUFFER`
6. `PEAK_PROFIT_GIVEBACK`
7. `TIME_REVIEW`
8. `CATALYST_REVIEW`
9. `SECTOR_REGIME_REVIEW`
10. `HYBRID_STRONGEST_VALID`

Every threshold in `PolicyConfig()` defaults to `None`. A candidate without an explicitly supplied staging-test threshold is `INCOMPLETE`; no final threshold is promoted.

Hard controls:

- below-current-stop candidates → `REJECTED_WIDENING`;
- candidates at/above current verified price → `REJECTED_AT_OR_ABOVE_PRICE`;
- manual stop lock still permits advisory computation but forces `persistence_permitted=false`;
- all candidates are advisory and `persistence_permitted=false` in Phase 1;
- hybrid chooses the highest valid non-widening candidate for a long;
- reconciliation conflict blocks all candidates.

## Package 3 — target review

Exact statuses:

- `KEEP`
- `TARGET_REACHED`
- `LOWER_REVIEW`
- `EXTEND_REVIEW`
- `INCOMPLETE`

`EXTEND_REVIEW` requires all six exact evidence flags, present and true:

- trend continuation
- confirmed breakout
- sustained volume
- valid catalyst
- acceptable volatility
- acceptable forward reward/risk

No replacement target is calculated or persisted.

## Package 4 — position status

Exact states:

- `HOLD`
- `TIGHTEN`
- `PROTECT_PROFIT`
- `TRIM_REVIEW`
- `EXIT_REVIEW`
- `DATA_RECONCILIATION_REQUIRED`
- `INCOMPLETE`

The deterministic renderer emits all required sections:

- POSITION STATUS
- ORIGINAL PLAN
- CURRENT STATE
- ADVISORY STOP
- TARGET STATUS
- REASON
- RECHECK
- DATA FRESHNESS
- INPUT DIGEST

## Package 5 — sidecar prototype

Append-only JSONL:

`state/position_reviews.jsonl`

Tracks:

- immutable original plan;
- peak price/close and timestamps;
- trough and timestamp;
- MFE/MAE and R values;
- peak/current profit and giveback;
- advisory and rejected stop candidates;
- target and position statuses;
- reviewed-at;
- provenance/version/input digest/idempotency key.

Verification:

- five records generated;
- rerun record count remained five;
- rerun file was byte-identical;
- high-water must increase for a new record;
- stale provider failure preserves the latest verified payload and marks the new record stale.

---

# Original-plan reconstruction

The module does not equate a tightened current stop with the immutable original stop.

Precedence:

1. supplied immutable entry evidence with source timestamp/digest;
2. explicit entry-plan text in notes;
3. current canonical values only when they remain valid as original-plan evidence;
4. otherwise `INCOMPLETE`.

Fixture proof:

- BAC current stop `54`, immutable original stop `46`, entry `50`, original risk `4`.
- PENG current stop `82`, immutable original stop `70`, entry `75.70`, original risk `5.70`.
- removing reliable entry evidence while the current stop is above entry makes the plan incomplete rather than inventing original risk.

Original-plan dataclasses are frozen; tests prove entry evidence outranks mutable current stop and no evaluation mutates the plan.

---

# Five-position staged outputs

These are synthetic immutable replay fixtures shaped from the audited identities. They are not live recommendations or production-wired provider outputs.

| Position | Position status | Target status | Original risk | Key staged finding |
|---|---|---|---:|---|
| SYNA | `PROTECT_PROFIT` | `KEEP` | 7 | Large peak giveback fixture activates configured test-only review |
| BAC | `TIGHTEN` | `KEEP` | 4 | Healthy near-target continuation; no automatic extension |
| ABNB | `TIGHTEN` | `KEEP` | 8 | Aligned-trend fixture |
| PENG | `DATA_RECONCILIATION_REQUIRED` | `TARGET_REACHED` | 5.7 | +18% peak/giveback state calculated, but missing position lot blocks authority |
| LASR | `DATA_RECONCILIATION_REQUIRED` | `KEEP` | 2 | Quantity/authority conflict blocks all management candidates |

PENG’s policy behavior without the intentional lot conflict is separately tested and returns `PROTECT_PROFIT` or `TRIM_REVIEW` under the explicitly configured test policy. Canonical-authority mode correctly prioritizes the reconciliation failure in the generated five-position output.

WDFC is a separate required replay fixture:

- position status `PROTECT_PROFIT`;
- target status `LOWER_REVIEW`;
- deterministic earnings-gap/reversal bar shape;
- no production TFE/BUY label changed.

---

# Reconciliation failures

The module treats `trades` as canonical OPEN source and compares, but never promotes, `position_lots`.

- missing PENG lot → `DATA_RECONCILIATION_REQUIRED`;
- LASR lot mismatch → `DATA_RECONCILIATION_REQUIRED`;
- orphan/missing/quantity mismatch reason codes supported;
- all ten policy candidates become `BLOCKED` on conflict;
- no overwrite or silent reconciliation occurs.

The audited orphan RL lot remains a known production defect; this staging package does not modify it.

---

# Chronological replay

## Policies

Nine configurable variants:

- current static stop/target baseline;
- breakeven;
- ATR Chandelier;
- EMA buffer;
- confirmed swing-low buffer;
- peak-profit giveback;
- time review;
- catalyst/sector/regime review;
- hybrid strongest valid.

All values are stored in `replay_test_only_policies.json`, explicitly marked TEST-ONLY and not production defaults.

## Replay discipline

- cursor-gated sequential bar visibility;
- future index/slice/time access raises `LookaheadError`;
- a swing low appears only after right-side confirmation bars are visible;
- stop gaps execute at adverse bar open;
- fees/slippage explicit;
- stop wins ambiguous same-bar stop/target cases;
- chronological train/validation/OOS allocation;
- canonical, anomalous, signal-only, and OPEN buckets are structurally separate and explicitly tested.

## Metrics

Every variant reports:

- total return/net P&L;
- expectancy and expectancy-R;
- profit factor;
- win rate;
- average winner/loser;
- maximum drawdown;
- MFE captured;
- average MFE/MAE;
- peak giveback;
- premature-exit rate;
- target/stop-hit rate;
- average holding period;
- turnover;
- whipsaw rate;
- regime/setup/volatility/sector breakdowns;
- train/validation/OOS counts.

All nine variants report:

- `assessment = needs_more_data`
- `optimality_claimed = false`

The 12-trade synthetic result is a harness proof only. Infinite synthetic profit factor serializes as strict JSON `null`, never `Infinity`/`NaN`.

---

# Required fixture coverage

Verified:

- PENG ~+18% then major giveback;
- WDFC gap and reversal;
- BAC near target with healthy continuation;
- ABNB aligned trend;
- SYNA peak giveback;
- LASR authority conflict;
- volatility expansion/contraction;
- sector breakdown;
- regime change;
- missing provider data;
- stop widening rejection;
- gap through advisory stop;
- manual stop lock computes advisory tightening but never persists.

---

# Test and safety evidence

## Compile

All staged source, tests, generators compiled successfully.

## Tests

Core + rendering:

```text
Ran 10 tests
OK
```

Replay:

```text
Ran 7 tests
OK
```

Total: **17/17 PASS**.

## Static safety

Both core modules:

- zero Telegram imports/strings/send paths;
- zero broker imports/actions;
- zero `atlas_engine`, `atlas_portfolio`, or `atlas_db` imports;
- zero network-client imports;
- zero SQL INSERT/UPDATE/DELETE/REPLACE statements;
- standard library only.

## Numeric provenance

Every evaluation includes:

- frozen source plan provenance;
- supplied-bar digest;
- price and received timestamps;
- policy-config digest;
- calculation version;
- deterministic full input/output digest.

The sidecar records payload and record SHA256 digests.

---

# Production invariants

Production source SHAs remained unchanged:

- `atlas_engine.py` — `a3908a609b37533e6daa106ade23f3a886c1ad628cb6c847ea4c5bc6448a071a`
- `atlas_portfolio.py` — `8fed8d2985bb6ff4ac661dfa75f447f5d30b7325f335dede60232329a90b1444`
- `atlas_db.py` — `8ae022d2d0c0b8cbfe0320661cc48529b00aa33ab665a583f2d36bf5dbedf3f1`
- `atlas_intraday.py` — `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_manage.py` — `d7df29af75fa3ae073556cde2c531406e07910a61206f92b85c31d590d7f7ca7`

Production DB integrity remained `ok`; `trades`, cash, ledger, pending rows, and position-lot counts were unchanged. `signals` and `report_snapshots` grew during the long staging window due to normal scheduled production cycles, not this package. The package contains no production DB path and no SQL write statement.

No canonical stop/target/status/cash/broker field was changed.

---

# Decisions still requiring Professor approval

1. ATR period and Chandelier multiple.
2. EMA selection and buffer.
3. Swing windows and volatility buffer.
4. Breakeven trigger in R.
5. Giveback trigger.
6. Time-review sessions.
7. Catalyst-expiry definition.
8. Earnings proximity window.
9. Sector/regime escalation semantics.
10. Lower/extend target-review evidence thresholds.
11. Trim/exit escalation consequences.
12. Minimum sample/promotion gates.
13. Production provider adapter and freshness TTLs.
14. Sidecar schema/location and scheduling.
15. Any future canonical or broker mutation permission.

No decision above is promoted in v1.

---

## Final

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = NO**

The advisory-only deterministic architecture, provenance, reconciliation blocking, sidecar behavior, strict chronological replay, required fixtures, and safety invariants are implemented and exercised. Production deployment is not ready until Professor separately approves policy thresholds, live provider/freshness wiring, and a production-release design.
