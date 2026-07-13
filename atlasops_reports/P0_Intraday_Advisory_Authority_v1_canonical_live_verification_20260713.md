# P0 Intraday Advisory Authority v1 — Canonical Live Verification

Professor,

## Verdict

STATUS: FAIL
intraday_advisory_authority_complete: NO
production_touched_by_verification: NO
verification_mode: READ-ONLY, except creation of this evidence report
canonical_db: `/Users/yasser/scripts/atlas.db`
deployment_completed_utc: `2026-07-10T20:11:45Z`
verification_observed_utc: `2026-07-13T13:50:40Z` onward

Failure reasons:

1. Two production files do not match the Prof-supplied expected release SHA256 values.
2. The cycle-bounded WATCH cohort is not completely reconciled by the rendered WATCHING section: `RPRX` and `ROIV` are current-cycle WATCH rows but appear neither in the 15 displayed entries nor in the explicit eight-item omission list.
3. Because of those failures, this run cannot certify the named canonical-routing release complete, even though the BUY-family diagnostic equation and most routing invariants pass.

No deployment, patch, restart, process kill, scheduler change, DB write, manual scan, Telegram test, or Telegram credential/config access occurred.

## 1. Production SHA gate

Expected and observed SHA256:

- `/Users/yasser/scripts/atlas_intraday.py`
  - expected: `8094a472b8f60faf7d2e791bfa4cb65056cb3b430f20de227e030adece428fee`
  - observed: `9c6269b1ab67f0b953a4fb7497851f792c6a31ad7a0740e61e6aa82dfbb50b5b`
  - result: FAIL
  - observed mtime: `2026-07-12T02:32:20+0400`
- `/Users/yasser/scripts/atlas_intraday_advisory.py`
  - expected: `25715b07f17df58b509304cb88ff1cea3712f5aa5fdeb941515e6917cc7125d7`
  - observed: `27a9230513daf4bca5c98a75bb97b1093bef34719cebb67192d39c78d2695ad6`
  - result: FAIL
  - observed mtime: `2026-07-12T01:15:44+0400`
- `/Users/yasser/scripts/atlas_report_blocks.py`
  - expected/observed: `c19c84ab13f823838d7c4e1993685675a05a7d13db8a65ae04df9627c7c3564e`
  - result: PASS
  - observed mtime: `2026-07-10T23:30:17+0400`

This was a status-only comparison. No source file was modified.

## 2. First completed real report after deployment

Selected snapshot:

- `report_snapshots.id`: 122
- `report_type`: `intraday`
- `generated_at`: `2026-07-13 13:47:45` UTC / 09:47:45 ET
- `dry_run`: 0
- body length: 5,906 characters
- stored SHA256: `c63d9ce4faef2a70751449003e1663e623d672188e6e2e8e61c289497b87621c`
- independently recomputed body SHA256: `c63d9ce4faef2a70751449003e1663e623d672188e6e2e8e61c289497b87621c`
- body hash result: PASS

Why this is the correct report:

- The deployment completed after the regular session on Friday, July 10.
- Snapshot 121 was generated at `2026-07-10 19:56:22Z`, before deployment completion.
- Snapshot 122 is the first subsequent persisted live intraday snapshot and is the Monday 09:30 ET cycle's completed report.
- A later 09:50 ET process was active during observation, but snapshot 122 was already complete and independently hash-valid; no wait or intervention was needed.

## 3. BUY-family canonical routing

Rendered equation:

`Current BUY-family 7 = BUY NOW 0 + TOP PICKS 0 + QUALIFIED WAIT 3 + EXCLUDED 4`

Arithmetic check:

`7 = 0 + 0 + 3 + 4`

Result: PASS

Cycle-bounded BUY-family rows (signal IDs 36284–36370, timestamps 13:43:49–13:47:42 UTC):

- ELV — BUY (Small), 3/4, RVOL 0.03 → EXCLUDED: pending entry/WAITING
- PSMT — BUY (Small), 3/4, RVOL 0.03 → EXCLUDED: pending entry/WAITING
- SEIC — BUY (Small), 3/4, RVOL 0.04 → EXCLUDED: pending entry/WAITING
- BAC — BUY (Small), 3/4, RVOL 0.05 → EXCLUDED: open position
- JPM — BUY (Small), 3/4, RVOL 0.06 → TECHNICALLY QUALIFIED — WAIT
- USB — BUY (Small), 3/4, RVOL 0.02 → TECHNICALLY QUALIFIED — WAIT
- KO — BUY (Small), 3/4, RVOL 0.06 → TECHNICALLY QUALIFIED — WAIT

Routing checks:

- BUY/BUY Small actionable → BUY NOW or TOP PICKS: no actionable rows were rendered; counts are zero.
- BUY/BUY Small blocked → TECHNICALLY QUALIFIED — WAIT: PASS for JPM, USB, KO, with explicit low-RVOL/data-validity blockers.
- Explicit reason for every exclusion: PASS. All four exclusions name a reason.
- BUY-family mutually exclusive destinations: PASS. The seven rows reconcile exactly once across the rendered equation.
- AVOID promoted to BUY NOW/TOP PICKS/QUALIFIED WAIT: none; PASS.

## 4. WATCH routing

Cycle-bounded classification counts:

- all signal rows: 87
- BUY-family: 7
- WATCH: 28
- AVOID: 52

Rendered WATCHING summary:

- header: `15 shown of 23`
- configured cap: 15 (production renderer default/current summary fallback)
- displayed: 15
- explicitly omitted: 8
- displayed + omitted: 23
- cap/count arithmetic: PASS

Displayed WATCHING tickers:

`AAPL, AMAT, CADL, CNS, CSCO, DAL, DSGN, INDB, JNJ, MRK, MS, QTTB, SPCX, TSM, UAL`

Explicit omissions:

`UMC, V, VEEE, HON, ILMN, INCY, RVMD, SBUX`

Open-position WATCH rows omitted from WATCHING as expected:

`ABNB, LASR, PENG`

Unreconciled current-cycle WATCH rows:

- `RPRX` — WATCH, 2/4, RVOL 0.01, signal timestamp `2026-07-13 13:46:47Z`
- `ROIV` — WATCH, 2/4, RVOL 0.06, signal timestamp `2026-07-13 13:47:42Z`

Both precede snapshot generation at 13:47:45Z, are not open positions, and appear neither in the displayed list nor the explicit omission list. Therefore the full rule `WATCH => WATCHING only` is not completely proven for the bounded current cohort.

WATCH routing result: FAIL

No WATCH ticker was promoted into BUY NOW, TOP PICKS, or QUALIFIED WAIT; that narrower non-promotion invariant passes.

## 5. Required ticker evidence

### WDFC

- current-cycle raw row: none in the bounded snapshot-122 cycle
- current destination: none
- current-cycle raw signal/score/RVOL: N/A / N/A / N/A
- note: the latest DB row is from July 10 and was deliberately not treated as a current July 13 classification.

### ELV

- current-cycle signal row id: 36286
- timestamp: `2026-07-13 13:44:07Z`
- raw signal: BUY (Small)
- score: 3/4 Pillars
- RVOL: 0.03
- current destination: EXCLUDED
- explicit reason: pending entry/WAITING

### KO

- current-cycle signal row id: 36347
- timestamp: `2026-07-13 13:45:07Z`
- raw signal: BUY (Small)
- score: 3/4 Pillars
- RVOL: 0.06
- current destination: TECHNICALLY QUALIFIED — WAIT
- explicit blockers: RVOL below 1.5; mandatory `data_timestamp_valid` and `rvol_eligible` gates failed

## 6. Render hygiene

Forbidden token counts in the persisted report body:

- `[PROVIDER]`: 0
- `[DB]`: 0
- `[TFE]`: 0
- `[RENDER-CALC]`: 0
- `Perme Engine Packet`: 0
- `STRUCTURED_MACRO_FACTS`: 0

Result: PASS

Regime-label check:

- canonical header regime label: `RISK-OFF`
- canonical header regime-label count: 1
- result: PASS

Earnings wording:

- earnings references in this report: 0
- result: PASS / not applicable; there are no conflicting earnings statements.

## 7. Numeric-level provenance check

The report's HOLDING entry/stop/target values were reconciled against canonical OPEN trades:

- SYNA: entry 126.44, stop 113.35, target 156.61 — match
- BAC: entry 57.10, stop 58.77, target 60.62 — match
- ABNB: entry 143.03, stop 135.96, target 157.17 — match
- PENG: entry 75.70, stop 76.44, target 87.96 — match
- LASR: entry 75.61, stop 66.94, target 106.68 — match

Result: PASS for stable canonical entry/stop/target levels. No invented holding level was found. Live/current prices are identified as market data or unavailable/reference-only; they were not independently re-queried because this verification was strictly read-only and prohibited a manual scan.

## 8. Stable DB comparison against available baseline

Baseline present:

`/tmp/p0_intraday_advisory_authority_v1/output/canonical_live_before.json`

Baseline contents support direct comparison of `account`, `cash_ledger`, and selected stable `trades` fields. It does not contain `position_lots` or `portfolio_event_journal`, so no before/after equality claim is made for those two tables.

Direct comparisons:

- account: unchanged — PASS
- cash_ledger: unchanged, 25 rows — PASS
- baseline trades: 105
- current trades: 108
- baseline trade IDs removed: none
- added rows: JPM id 137, USB id 138, KO id 139; all `PENDING_FILL`
- stable-field changes on baseline rows:
  - BAC id 47 stop: 57.11 → 58.77
  - PENG id 111 stop: 75.71 → 76.44
  - PENG id 111 target: 100.01 → 87.96

The changed BAC/PENG levels are represented by later Professor-approved `MANUAL_CORRECTION` journal events dated July 11, after this baseline. The report renders the current canonical values exactly. The added pending rows are normal live trading-state evolution and are not attributed to this read-only verification.

Current-only integrity evidence where the baseline lacks rows:

- position_lots: 69 rows, max id 69
- portfolio_event_journal: 97 rows, max id 97

No before-comparison is claimed for those tables.

## 9. Database integrity

- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: 0 violations
- result: PASS

## 10. Final acceptance

Passing controls:

- first real post-deployment report identified and body hash verified
- BUY-family diagnostic equation balances
- every BUY-family exclusion has an explicit reason
- BUY-family destinations are mutually exclusive
- no WATCH/AVOID promotion into actionable/qualified BUY destinations
- forbidden render artifacts absent
- one canonical header regime label
- earnings wording non-conflicting/not applicable
- WATCHING cap/count/omission arithmetic internally balances
- canonical holding entry/stop/target levels match the DB
- account and cash ledger match the available baseline
- DB integrity and foreign keys pass

Blocking failures:

- two expected production SHA values do not match
- two current-cycle WATCH rows (`RPRX`, `ROIV`) are missing from both displayed WATCHING and its explicit omission list

FINAL STATUS: FAIL
intraday_advisory_authority_complete: NO
production_touched_by_verification: NO
verification_report_only_file_created: `/Users/yasser/scripts/atlasops_reports/P0_Intraday_Advisory_Authority_v1_canonical_live_verification_20260713.md`
