# FDA P0B1 Selective Fat Engine Wiring — Design + Staging Plan

Generated: 2026-07-09

## Status

`P0B1_STATUS = DESIGN_AND_STAGING_PLAN_ONLY`

`approval_required = YES`

No production patch, no production DB write, no Telegram, no Vault, no broker action, no Fat Engine scoring change, no Quiver/FDA live change.

## Grounding snapshot

Key status only — no values:

| env name | status |
|---|---|
| `BENZINGA_API_KEY` | SET |
| `MASSIVE_API_KEY` | SET |
| `POLYGON_API_KEY` | MISSING |
| `EODHD_API_KEY` | SET |
| `EODHD_TOKEN` | MISSING |

Known provider fact from prior audit: direct Benzinga FDA endpoint is accessible:

```text
https://api.benzinga.com/api/v2.1/calendar/fda
```

Massive/Benzinga FDA path was not found in prior audit. Do not build Stage 1 on Massive FDA.

## Current affected files/functions map

Non-disclosing current map:

| file | functions / role |
|---|---|
| `atlas_engine.py` protected | existing FDA internals: `_fda_symbols`, `_fda_text`, `_classify_fda_event`, `_fda_sector_info`, `_is_biotech_sector`, `_load_fda_calendar_window`, `check_fda_calendar`, `analyze_ticker` |
| `atlas_portfolio.py` protected | existing FDA call paths in `evaluate_pending_pullback`, `evaluate_exit`, `consider_buy` |
| `atlas_manage.py` | orchestrates `analyze_ticker`, calls `evaluate_pending_pullback` / `consider_buy`, propagates `fda_calendar`, `fda_note`, `fda_blackout` into candidate dictionaries |
| `market_scout.py` | `discover_tickers()` currently has Benzinga news and Massive earnings buckets, no dedicated FDA bucket |
| `pre_market_report.py` | `get_wavef_fda_warnings()` calls protected loader; report-only FDA warning section already exists |
| `atlas_intraday.py` | `_fda_tag()` renders FDA metadata if candidate dict contains it |
| `atlas_premarket_gaps.py` | `benzinga_catalyst()` uses Benzinga news only, not FDA calendar |
| new proposed | `atlas_fda_calendar.py` deterministic provider/cache/gating helper |

Protected-source boundary: I did not read/provide protected formulas, thresholds, or body logic. Function/call names only.

## Proposed architecture

### New unprotected provider module

Create staged module:

```text
/tmp/p0b1_fda_selective_wiring/src/atlas_fda_calendar.py
```

Production target only after later approval:

```text
/Users/yasser/scripts/atlas_fda_calendar.py
```

Responsibilities:

1. Fetch direct Benzinga FDA calendar once per scan/window.
2. Normalize rows into a deterministic schema.
3. Cache normalized rows with TTL.
4. Build ticker index for selective gating.
5. Expose cheap per-ticker lookup from cache.
6. Expose discovery bucket tickers for `market_scout`.
7. Record API call count / row count / ticker count for verification.

### Normalized row schema

```json
{
  "ticker": "FATE",
  "company": "Fate Therapeutics, Inc.",
  "drug": "FT839",
  "event_type": "FDA Clearance",
  "target_date": "2026-07-09",
  "availability_date": "2026-07-09T...Z",
  "created": 178..., 
  "updated": 178...,
  "status": "Investigational New Drug (IND)",
  "outcome": "...",
  "outcome_brief": "...",
  "source_endpoint": "benzinga_direct_fda_calendar_v2_1",
  "source_id": "benzinga_fda_id"
}
```

Rules:

- `target_date` = event date only.
- `availability_date` = first known provider availability date derived from `created`, `updated`, or equivalent provider publication field.
- `source_endpoint` must be a stable label, not a credentialed URL.
- No raw token/API key ever stored in cache/report.

## Selective ticker gating

### `should_check_fda(ticker, metadata, news, cache) -> gate_result`

Closed enum:

| decision | meaning |
|---|---|
| `FDA_CHECK_ALLOWED_CALENDAR_MATCH` | ticker appears in normalized FDA calendar index |
| `FDA_CHECK_ALLOWED_HEALTHCARE_CLASSIFICATION` | sector/industry matches FDA-relevant terms |
| `FDA_CHECK_ALLOWED_RECENT_KEYWORD_NEWS` | recent ticker news includes FDA/clinical/drug keywords |
| `FDA_CHECK_ALLOWED_METADATA_TAG` | cached metadata explicitly marks FDA-relevant |
| `FDA_CHECK_ALLOWED_WATCHLIST` | explicit FDA watchlist contains ticker |
| `FDA_CHECK_BLOCKED_NON_FDA_SECTOR` | ticker is bank/semi/software/consumer/industrial/etc. and not calendar-matched |
| `FDA_CHECK_BLOCKED_ETF_OR_PROXY` | ETF/index/broad proxy and not calendar-matched |
| `FDA_CHECK_BLOCKED_MISSING_DATA` | insufficient metadata/news/cache; fail closed |

### Allowed classifiers

FDA-relevant if any metadata field contains terms in these families:

- biotechnology / biotech
- pharmaceuticals / pharma
- drug manufacturers
- medical devices
- diagnostics / diagnostic tools
- life sciences tools
- clinical-stage / clinical trials
- healthcare therapeutics
- genomics / gene therapy / cell therapy / oncology drug development

### Explicit blocklist families unless calendar-matched

- banks / financials / brokers / insurance
- semiconductors / chips / hardware
- software / SaaS / internet platforms
- consumer discretionary/staples
- industrials / transports / energy / materials
- ETFs / ETNs / indexes / broad market proxies
- sector ETFs like `XLF`, `XLK`, `SMH`, `SOXX`, `SPY`, `QQQ`

Calendar match always wins because a direct provider event for a ticker is authoritative FDA relevance.

## Cache / TTL design

### Cache files

Staged cache root:

```text
/tmp/p0b1_fda_selective_wiring/cache/
```

Production later:

```text
/Users/yasser/scripts/cache/fda_calendar/
```

Files:

| file | purpose |
|---|---|
| `fda_calendar_normalized.json` | normalized row list + metadata |
| `fda_calendar_ticker_index.json` | ticker -> events list |
| `fda_calendar_stats.json` | endpoint calls, row count, ticker count, cache hit/miss, generated_at |
| `fda_relevance_metadata.json` | optional cached ticker relevance tags |

### TTL

| use | TTL |
|---|---:|
| intraday scan/runtime | 6 hours |
| premarket report | 12 hours |
| offline staging tests | fixture/frozen cache, no live TTL dependency |

### API control invariant

- Per scan window: **one FDA endpoint fetch max**.
- Per-ticker checks must read normalized cache/index only.
- Staging verification must assert provider call count does not exceed `1` for a multi-ticker test set.

## Discovery bucket design

Add to `market_scout.discover_tickers()` after existing news/earnings buckets and before generic fallback:

```text
fda_order = atlas_fda_calendar.discover_fda_tickers(days=30|60|90, limit=N)
```

Design rules:

- Windows supported: `30`, `60`, `90` calendar days.
- Default Stage 1: `60` days, cap `10` tickers per scan.
- Deduped tickers, preserve event-date ordering first, then materiality priority.
- Exclude ETFs/proxies unless directly present in FDA calendar row.
- Add bucket into `LAST_DISCOVERY_BUCKETS["fda"]` for audit/reporting.
- Feed candidates into normal scan path as FDA-relevant tickers.
- Stage 1: **no score change**; only adds candidates + metadata visibility.

## Stage 1 integration — metadata/report only

### Design objective

Make FDA data visible and selective without touching BUY/AVOID scoring.

### Files/functions likely touched in Stage 1

| file | function | change |
|---|---|---|
| new `atlas_fda_calendar.py` | `fetch_fda_calendar_window()` | direct Benzinga FDA fetch + redacted key handling |
| new `atlas_fda_calendar.py` | `normalize_fda_rows()` | provider row -> normalized schema |
| new `atlas_fda_calendar.py` | `load_or_refresh_fda_cache()` | TTL cache + stats |
| new `atlas_fda_calendar.py` | `build_ticker_index()` | ticker -> events |
| new `atlas_fda_calendar.py` | `should_check_fda()` | selective gating decision |
| new `atlas_fda_calendar.py` | `get_fda_metadata_for_ticker()` | cache-only per-ticker metadata |
| new `atlas_fda_calendar.py` | `discover_fda_tickers()` | FDA discovery bucket |
| `market_scout.py` | `discover_tickers()` | add `fda_order` bucket, cap, dedupe, expose in `_LAST_DISCOVERY_BUCKETS` |
| `atlas_manage.py` | `run()` / pre-loop setup | load FDA cache once per scan, pass/merge metadata into candidate dicts after analysis |
| `atlas_intraday.py` | `_fda_tag()` / report rows | existing render can consume richer normalized metadata; minimal or no change expected |
| `pre_market_report.py` | FDA warning source | switch to new helper for report-only warning lines, avoiding protected loader dependency |

### Protected-file approach in Stage 1

Two options:

1. **Preferred Stage 1 non-protected path:** do not modify `atlas_engine.py`/`atlas_portfolio.py`; apply FDA metadata as a sidecar in `atlas_manage.py` and reports only. This proves provider/cache/gating/discovery value without touching scoring.
2. **If Prof wants strict “TFE candidate output” inside `analyze_ticker`:** a later explicitly-approved protected-file staging round is required. That would insert the new selective helper in `atlas_engine.analyze_ticker()` and replace existing broad FDA calls with `should_check_fda()` gating, still with no score change.

Recommendation: do **non-protected Stage 1 first**, then decide whether protected TFE internals need cleanup once metadata path is proven.

## Stage 2 scoring proposal — do not implement yet

FDA can count as a Catalyst pillar only when **all** are true:

1. Event is ticker-matched in normalized FDA calendar.
2. Event is upcoming/recent within an approved window.
3. Event type is material.
4. Availability date passes no-lookahead rule.
5. Status is not stale, irrelevant, canceled, or stale historical noise.
6. Ticker passes non-FDA gates: liquidity, risk, too-hot/extension, price sanity, basic eligibility.

FDA must **not**:

- override failed liquidity/risk/too-hot gates;
- generate BUY alone;
- convert non-FDA sector tickers into FDA candidates unless calendar-matched;
- use `target_date` as evidence that the event was known before provider availability;
- use LLM-written prose as a scoring source.

Stage 2 output should be an explicit deterministic evidence field, e.g.:

```json
{
  "fda_catalyst_evidence": {
    "qualifies_for_catalyst_pillar": true,
    "reason_code": "FDA_MATERIAL_UPCOMING_TICKER_MATCH",
    "availability_date": "...",
    "event_type": "PDUFA / FDA clearance / Phase result / IND clearance",
    "source_id": "..."
  }
}
```

`protected_work_order_needed_for_stage2 = YES`

## No-lookahead rule

Historical/replay usage must use:

- provider `created` timestamp;
- provider `updated` timestamp when `created` absent;
- provider publication/source timestamp if provided;
- never `target_date` as availability date.

For a historical candidate date `T`, event may be used only if:

```text
availability_date <= T
```

`target_date` may define event distance, but not knowledge availability.

## Stage 1 staging patch plan

Staging root:

```text
/tmp/p0b1_fda_selective_wiring/
  src/
  cache/
  db/
  fixtures/
  output/
```

Files copied to staging:

```text
src/atlas_fda_calendar.py          # new
src/market_scout.py                # staged copy
src/atlas_manage.py                # staged copy
src/pre_market_report.py           # staged copy if FDA report source is switched
src/atlas_intraday.py              # staged copy only if rendering needs normalized fields
```

Production DB copy:

```text
/tmp/p0b1_fda_selective_wiring/db/atlas_validation.db
```

Staging invariants:

- Set `ATLAS_DB` to copied DB only.
- Never call production `analyze_ticker()` against production DB.
- Stub `atlas_db.log_signal`, audit hooks, Telegram sender names, broker functions, and any sync side effects before imports where required.
- Since Vault has been purged, static scan must still prove no Vault refs are introduced.
- Provider key reported only as `BENZINGA_API_KEY SET|MISSING`.

## Required staging verification

| test | pass condition |
|---|---|
| `py_compile` | all staged files compile |
| static scan | no Telegram send calls, no Vault, no broker writes, no Quiver imports, no new protected imports in new helper |
| provider endpoint | direct Benzinga FDA endpoint returns 200 or fixture fallback explicitly marked if network unavailable |
| normalized sample | one redacted normalized row shape printed, no raw token/url params |
| discovery bucket | sample FDA tickers returned, capped, deduped, event-window sorted |
| gating FDA ticker | FDA-relevant ticker returns `FDA_CHECK_ALLOWED_*` and metadata from cache |
| gating non-FDA ticker | bank/semi/software/ETF returns blocked and does not trigger endpoint fetch |
| endpoint call count | multi-ticker test with mixed sectors uses max 1 FDA endpoint fetch |
| copied DB counts | `signals`, `trades`, `pending_pullbacks`, `handoff`, `cash_ledger`, `portfolio_event_journal`, `report_snapshots` unchanged |
| no signal writes | `signals` count unchanged in copied DB and production DB SHA unchanged |
| Stage 1 score invariant | candidate score/signal/action/entry/stop/target unchanged vs baseline fixture |
| candidate metadata | FDA-relevant sample candidate includes `fda_calendar_normalized` / `fda_relevance_reason` metadata |
| report render | FDA metadata appears in report-only text; no BUY/AVOID impact |

## Runtime/API count proof design

Use a fake provider session and one live/fixture provider test:

1. Fake response with 3 FDA rows: biotech ticker, bank ticker absent, ETF absent.
2. Call `discover_fda_tickers()` once: assert `api_calls=1`.
3. Call `get_fda_metadata_for_ticker()` for 20 tickers: assert `api_calls` remains `1`.
4. Assert `JPM`, `NVDA`, `SPY` return blocked/no metadata unless inserted directly in FDA fixture.
5. Insert `FATE`/`QNRX` fixture rows: assert allowed + metadata populated.

## Risks

| risk | mitigation |
|---|---|
| FDA endpoint filter may return broad rows despite ticker param | always normalize all rows and match tickers locally from `companies/securities` |
| existing protected FDA calls may still run broad checks | Stage 1 sidecar avoids protected changes; Stage 2 must explicitly gate protected calls |
| accidental DB writes via `analyze_ticker()` | never run against production; copied DB + stubs + SHA/count verification |
| runtime slowdown | fetch once per scan, cache TTL, per-ticker cache-only checks |
| false FDA relevance for healthcare conglomerates | require sector/industry plus event/news/watchlist confidence; score impact deferred to Stage 2 |
| no-lookahead leakage | store separate `availability_date`; tests assert `availability_date <= candidate_date` |
| LLM contamination | LLM may format report text only; cannot create FDA evidence or prices |

## Approval boundary

Stage 1 implementation requires approval to create staging artifacts under `/tmp` only.

Production deployment requires a separate approval after staging verification.

`approval_required = YES`
