# FDA P0B2 Stage 1 — Staging Implementation Report

Generated: 2026-07-09

## Status

`STAGING_STATUS = PASS`

`approval_required = YES`

Staging only under `/tmp`. No production patch, no production DB write, no Telegram, no Vault, no broker action, no Quiver, no Fat Engine scoring change, no BUY/AVOID impact.

## Staging root

```text
/tmp/p0b2_fda_selective_wiring/
```

## Staged files + SHAs

| file | staged path | SHA256 | status |
|---|---|---|---|
| `atlas_fda_calendar.py` | `/tmp/p0b2_fda_selective_wiring/src/atlas_fda_calendar.py` | `1621c6fd0a99a78e1bb295c8dc41b4ce74d24bd21a96c114e1fe4c6c89cffb50` | new helper |
| `market_scout.py` | `/tmp/p0b2_fda_selective_wiring/src/market_scout.py` | `2dfaf7f9969a05020a0a1d63ae8410a866a7ea47b1f580182bf1323259b500f0` | patched |
| `atlas_manage.py` | `/tmp/p0b2_fda_selective_wiring/src/atlas_manage.py` | `d7df29af75fa3ae073556cde2c531406e07910a61206f92b85c31d590d7f7ca7` | patched |
| `pre_market_report.py` | `/tmp/p0b2_fda_selective_wiring/src/pre_market_report.py` | `0fa9ce57b9e3ee312ec6bf5c88b7dd3e077a9095c399bc30ff769ade620588f9` | copied unchanged |
| `atlas_intraday.py` | `/tmp/p0b2_fda_selective_wiring/src/atlas_intraday.py` | `06f8d0666c0e71523b6741c6a62ffbcf2d9aebc56f1ad8b5dc36c906516c5a41` | copied unchanged |

Diff summary:

| file | added | removed | diff |
|---|---:|---:|---|
| `market_scout.py` | 17 | 2 | `/tmp/p0b2_fda_selective_wiring/output/market_scout.py.diff` |
| `atlas_manage.py` | 44 | 0 | `/tmp/p0b2_fda_selective_wiring/output/atlas_manage.py.diff` |
| `pre_market_report.py` | 0 | 0 | unchanged |
| `atlas_intraday.py` | 0 | 0 | unchanged |

## Implemented Stage 1 behavior

### New `atlas_fda_calendar.py`

Implements:

- direct Benzinga FDA endpoint only: `benzinga_direct_fda_calendar_v2_1` label;
- key status as `SET/MISSING` only;
- `fetch_fda_calendar_window(days=60)`;
- `normalize_fda_rows()`;
- `build_ticker_index()`;
- `load_or_refresh_fda_cache()` with TTL/cache files;
- `discover_fda_tickers(days=60, limit=10)`;
- `should_check_fda()` selective gating;
- `get_fda_metadata_for_ticker()` metadata sidecar;
- API/cache stats with endpoint call count.

### `market_scout.py`

Adds FDA discovery bucket:

- `fda_order = atlas_fda_calendar.discover_fda_tickers(days=60, limit=10)`
- bucket stored in `_LAST_DISCOVERY_BUCKETS["fda"]`
- FDA bucket included in dedupe/final candidate order
- fallback universe no longer fires if FDA bucket has tickers
- no score/scoring/catalyst-pillar change

### `atlas_manage.py`

Adds Stage 1 sidecar only:

- loads FDA cache once after ticker loop;
- attaches FDA metadata to `high_candidates` rows only;
- stores `LAST_RUN_SUMMARY["fda_scan_stats"]`;
- does not change `score`, `signal`, `action`, `entry`, `stop`, `target`, `BUY/AVOID`.

## Verification evidence

Full JSON evidence:

```text
/tmp/p0b2_fda_selective_wiring/output/verification.json
```

| gate | result |
|---|---|
| `py_compile` | PASS (`exit_code=0`) |
| static scan | PASS: no forbidden added/helper hits; no Vault hits |
| direct FDA endpoint | reachable (`HTTP 200`) |
| direct FDA response shape | top key `fda`; sample keys include `commentary`, `companies`, `created`, `date`, `drug`, `event_type`, `id`, `status`, `target_date`, `updated` |
| live normalized rows | 91 rows / 74 tickers in 60-day window |
| fixture normalized rows | 3 rows / tickers `FATE`, `QNRX`, `JPM` |
| discovery sample | `FATE`, `QNRX`, `JPM` |
| endpoint call count proof | PASS: mixed multi-ticker test used `endpoint_calls = 1` |
| copied DB counts | unchanged |
| copied DB SHA | unchanged |
| production DB SHA/counts | unchanged during verification window |
| no signal writes | PASS |
| Stage 1 score/signal/action invariant | PASS |
| sample FDA candidate metadata | present for `FATE` |

## Gating proof

| ticker | metadata / condition | result |
|---|---|---|
| `FATE` | FDA calendar match | `FDA_CHECK_ALLOWED_CALENDAR_MATCH` |
| `CRSP` | healthcare/biotech classification | `FDA_CHECK_ALLOWED_HEALTHCARE_CLASSIFICATION` |
| `BAC` | bank/financial | `FDA_CHECK_BLOCKED_NON_FDA_SECTOR` |
| `NVDA` | semiconductor | `FDA_CHECK_BLOCKED_NON_FDA_SECTOR` |
| `MSFT` | software | `FDA_CHECK_BLOCKED_NON_FDA_SECTOR` |
| `SPY` | ETF/proxy | `FDA_CHECK_BLOCKED_ETF_OR_PROXY` |
| `JPM` | normally bank, but fixture calendar match | `FDA_CHECK_ALLOWED_CALENDAR_MATCH` |

Calendar match override is proven by the synthetic `JPM` fixture row.

## Runtime/API call count proof

Fixture test sequence:

1. Force-refresh FDA cache once using fixture fetcher.
2. Build normalized rows and ticker index.
3. Query mixed tickers: `FATE`, `CRSP`, `BAC`, `NVDA`, `MSFT`, `SPY`, `JPM`, `QNRX`.
4. Per-ticker checks read cache only.

Observed stats:

```json
{
  "endpoint_calls": 1,
  "cache_hits": 0,
  "cache_misses": 1,
  "last_row_count": 3,
  "last_ticker_count": 3
}
```

Pass condition `endpoint_calls <= 1`: **PASS**.

## Sample FDA candidate metadata

Candidate: `FATE`

Baseline fields stayed unchanged:

```json
{
  "score": "2/4 Pillars",
  "signal": "WATCH",
  "action": "WAIT",
  "entry": 12.34,
  "stop": 11.11,
  "target": 15.0
}
```

FDA metadata added:

```json
{
  "ticker": "FATE",
  "fda_relevant": true,
  "fda_relevance_reason": "FDA_CHECK_ALLOWED_CALENDAR_MATCH",
  "fda_event_count": 1,
  "fda_source_endpoint": "benzinga_direct_fda_calendar_v2_1",
  "fda_next_event": {
    "event_type": "FDA Clearance",
    "target_date": "2026-07-09",
    "availability_date": "2026-07-09T15:13:20Z",
    "source_id": "fixture_fate_1"
  }
}
```

## DB safety proof

Verification copied `/Users/yasser/scripts/atlas.db` to:

```text
/tmp/p0b2_fda_selective_wiring/db/atlas_validation.db
```

Observed unchanged in copied DB and production DB during the verification window:

- `signals`
- `trades`
- `pending_pullbacks`
- `handoff`
- `cash_ledger`
- `portfolio_event_journal`
- `report_snapshots`

`no_signal_writes = true`

## Gaps / limitations

1. Stage 1 is sidecar metadata/report/discovery only; protected engine’s existing internal FDA calls are not removed or gated yet.
2. Existing protected `analyze_ticker()` FDA behavior remains partially wired until Stage 2/protected work order.
3. `pre_market_report.py` and `atlas_intraday.py` were copied but not patched; existing render paths can consume metadata where already wired, but richer normalized rendering may need a small later report-format patch.
4. Live endpoint returned rows successfully, but endpoint semantics can include broad rows; local ticker matching remains required.
5. The market-scout test used fixture forcing to isolate FDA bucket and avoid unrelated provider calls; this is correct for staging proof but not a full live scan.

## Stage 2 protected TFE wiring plan — not implemented

Requires separate explicit protected alpha-work approval.

Planned protected-side changes:

1. Replace any broad per-ticker FDA calendar call in protected `atlas_engine.py` / `atlas_portfolio.py` with `atlas_fda_calendar.should_check_fda()` gate.
2. Load FDA cache once per scan in non-protected orchestrator and pass/cache sidecar into protected calls only if necessary.
3. Preserve all current liquidity/risk/too-hot/admission gates.
4. Allow FDA to contribute to Catalyst pillar only if:
   - ticker-matched FDA event;
   - material event type;
   - availability date no-lookahead safe;
   - event upcoming/recent in approved window;
   - status not stale/irrelevant.
5. FDA cannot generate BUY alone and cannot override failed risk/liquidity/extension gates.
6. Build protected-file staged patch in `/tmp`, with byte-identity checks for untouched functions and copied-DB tests proving no BUY/AVOID drift except explicitly approved future scoring fixtures.

`protected_work_order_needed = YES`

## Final verdict

`P0B2_STAGE1_READY_FOR_REVIEW = YES`

`approval_required = YES`
