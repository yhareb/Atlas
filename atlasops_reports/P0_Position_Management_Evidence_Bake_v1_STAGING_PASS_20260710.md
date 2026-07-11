# Position Management Evidence Bake v1 — Staging Evidence

## Status
- **STATUS = PASS**
- **production touched = NO**
- Staging: `/tmp/p0_position_management_evidence_bake_v1/`
- `evidence_bake_deployment_ready = YES` for the isolated shadow-capture mechanics only.
- Policy promotion: **NO**. No policy was selected, deployed, scheduled, or granted action authority.

## Shadow store

Append-only SQLite: `/tmp/p0_position_management_evidence_bake_v1/state/evidence_bake.sqlite`

Tables:
- `runs`: content-addressed capture runs and summaries.
- `evidence`: immutable observations, constrained to confirmed completed, anomalous/disputed, FILLED pullback, signal-only, and current-OPEN buckets.
- `policy_observations`: immutable advisory outputs linked to evidence rows.
- `high_water`: one non-regressing source timestamp per stream.
- `stale_observations`: stale payload digest and preserved prior high-water.

UPDATE/DELETE triggers reject changes to evidence and policy observations. A high-water trigger rejects timestamp regression. Event IDs and unique constraints prevent duplicates. SQLite integrity is `ok`; FK violations are `0`.

## Capture and update logic

The runner consumes immutable local snapshots under `raw/`, never production directly. It enriches each observation with entry/setup, original/current stop and target, current/high/low, ATR, EMA10/20/50, swing low, MFE/MAE, profit/giveback, catalyst, earnings, sector, regime, RVOL, momentum, source timestamp/provenance, and completeness conflicts.

Policy observations separately preserve old/new stop and method, old/new target and method, action, rejected alternatives, parameters, calculation version, and digest. Captures are content-addressed and restart-safe. Same input/capture key returns the existing run and leaves the SQLite file byte-identical. Stale events append to the stale ledger while the verified high-water remains unchanged.

## Evidence buckets

- Broker-confirmed completed: **8**.
- Anomalous/disputed: **4**.
- FILLED pullback candidates: **22**.
- Signal-only candidates: **2,099**; explicitly not real fills.
- Actual current OPEN positions: **5** — SYNA, BAC, ABNB, PENG, LASR.
- Fixture-only current rows: **2** WDFC catalyst A/B records.
- Policy observations: **7**.
- High-water streams: **2,140**; preserved stale observations: **1**.

Buckets are enforced structurally and tested for separation.

## Missing-catalyst A/B shadow

- **Variant A — target-only block:** WDFC stop `$28.00 → $29.601018` using `EMA10_1PCT`; target `$38.00 → INCOMPLETE`; action `TIGHTEN`.
- **Variant B — stop-and-target block:** stop and target both `INCOMPLETE`; action `INCOMPLETE`.

Both are fixture-only observations. Neither affects production or chooses the future rule.

## Research and promotion gates

- Minimum mechanically valid completed candidate paths: **50**; current completed broker-confirmed paths: **8**.
- Preferred broker-confirmed outcomes: **30**.
- Regime/setup/sector subgroup counts must be reported before claims.
- Promotion blocked whenever validation or chronological OOS PF is below `1`.
- Promotion blocked when drawdown, whipsaw, or premature exits materially worsen without compensating expectancy.

These are research gates, not trading rules. The previous calibration’s validation/OOS evidence remains below the gate, so policy promotion is NO.

## Automation design — prepared, not deployed

A future removable after-close package would have two explicit boundaries:

1. A read-only acquisition step, after final close data settles, atomically publishes immutable source snapshots with timestamps and SHA256.
2. The core runner consumes only those snapshots and writes only a dedicated shadow SQLite store.

It would capture all OPEN positions and eligible candidates, update outcomes chronologically, send no Telegram messages, expose no broker path, and remain removable by unloading its separately approved schedule and archiving its script/store. No launchd plist, cron entry, schedule, or production runner was created in this task.

## Tests and invariants

- `py_compile`: PASS.
- Tests: **10/10 PASS** — no-lookahead, idempotency/byte identity, non-regressing high-water, stale preservation, append-only enforcement, bucket separation, required fields/policy contract, fixture coverage, catalyst A/B, research gates, and production/external-mutation safety.
- Fixtures: PENG, WDFC, SYNA, BAC, ABNB, LASR.
- Production SQL writes: `0`; Telegram sends: `0`; broker actions: `0`; TFE/strategy mutations: `0`.
- Production DB SHA remains `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`; production source targets remained unchanged/Git-clean.

## Files and SHA256

- `src/evidence_bake.py` — `dd1563ac8d9d94205244c5ff63ca4a1ace873ddfe235d5c950d2d98528d8f4bf`
- `tests/test_evidence_bake.py` — `8fda4f995ad13567c495818f9a5f479b4cd21299696e1d18a63f11ede3aec641`
- `state/evidence_bake.sqlite` — `39b86bd805d515405f278d342607705fa258c33008c8f5068035e91fb9c8ba60`
- `design/future_after_close_runner.md` — `97b08540df5c546f7589b791dcedc8480646283cb7f702f0ce702316279617da`
- `output/test_results.txt` — `fbadf7334efca5eb76de6dbaa0f4f73a722fa14db8e632d82cb2a98f35fd9eaf`
- `output/staging_report.md` — `96736655778b4c057b8ea0f4b43eee248bece0737a05e913b20aee8d204e9038`
- `output/artifact_manifest.json` — `a966219ab79e63484b53c73d76af8c36580136273731961ee136703986b537fe`

## Future deployment scope

If separately authorized later: deploy one shadow acquisition runner, one append-only capture runner, one dedicated shadow-store directory, and one after-close schedule. No modifications to Atlas trading scripts, TFE, canonical DB schema/data, Telegram routing, broker integration, stops, targets, or trade status.

## Rollback design

Unload only the separately named shadow schedule, archive/remove only its runner and dedicated sidecar directory, and verify Atlas source/DB SHAs remain unchanged. Because the integration is additive and observation-only, rollback requires no trading-state migration.

`evidence_bake_deployment_ready = YES`
