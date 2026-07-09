# P0 FDA/Benzinga Wiring Audit — Read-only Design/Access Finding

Generated: 2026-07-09

## Executive verdict

**Status: PARTIALLY WIRED.**

FDA catalyst data is **not merely an unused API**: Atlas production code has a direct Benzinga FDA calendar loader and FDA-check functions are called from engine/portfolio paths. However, the current wiring appears to be a **separate FDA calendar/risk overlay**, not a fully proven Fat Engine catalyst-pillar/scoring input. Live probes showed direct Benzinga FDA access works, but sample ticker metadata did **not consistently carry FDA events into `analyze_ticker()` output or `catalyst_reason`**.

## Safety / side-effect disclosure

The work order requested no production DB writes. I avoided deploys, patches, broker actions, Telegram sends, and Quiver. However, two `analyze_ticker()` probes unexpectedly triggered Atlas signal logging and Vault signal sync despite my attempted no-op monkeypatch.

Observed production DB additions:

| table | ids | tickers | reason |
|---|---:|---|---|
| `signals` | 31783-31786 | CRSP, LLY, DCTH, FBRX | diagnostic `analyze_ticker()` probes |

Vault stdout showed `vault_client: pushed signal {'signals': 1}` for three of those probes. I did **not** clean up or modify DB rows because cleanup would be another production write requiring Professor approval.

## 1. Provider entitlement/access

Key status only — no values printed:

| key name | status |
|---|---|
| `MASSIVE_API_KEY` | SET |
| `POLYGON_API_KEY` | MISSING |
| `BENZINGA_API_KEY` | SET |
| `EODHD_API_KEY` | SET |
| `EODHD_TOKEN` | MISSING |

Endpoint probes:

| provider path | result | finding |
|---|---:|---|
| `https://api.massive.com/benzinga/v2/news` | 200 | Massive/Benzinga news entitlement usable |
| `https://api.massive.com/benzinga/v1/earnings` | 200 | Massive/Benzinga earnings entitlement usable |
| `https://api.massive.com/benzinga/v1/calendar/fda` | 404 | no Massive FDA path found at this guessed endpoint |
| `https://api.massive.com/benzinga/v2.1/calendar/fda` | 404 | no Massive FDA path found at this guessed endpoint |
| `https://api.massive.com/benzinga/v1/fda` | 404 | no Massive FDA path found at this guessed endpoint |
| `https://api.benzinga.com/api/v2.1/calendar/fda` | 200 | direct Benzinga FDA calendar accessible |
| `https://eodhd.com/api/sec-filings/CRSP/form4` | 200 | EODHD Form4 fallback accessible |
| `https://eodhd.com/api/news` | 200 | EODHD ticker-news fallback accessible |

## 2. Code wiring

Affected production files/functions found:

| file | function/path | observed role |
|---|---|---|
| `atlas_engine.py` | `_load_fda_calendar_window()` | direct Benzinga FDA calendar fetch path present |
| `atlas_engine.py` | `check_fda_calendar(ticker, fundamentals=None, holding=False)` | FDA event classifier/check present |
| `atlas_engine.py` | `analyze_ticker(ticker, regime=None)` | calls FDA check and can include `fda_calendar` field |
| `atlas_portfolio.py` | `consider_buy()` | calls FDA check in buy-decision path |
| `atlas_portfolio.py` | `evaluate_pending_pullback()` | calls FDA check in pending-pullback path |
| `atlas_portfolio.py` | `evaluate_exit()` | calls FDA check in holding/exit-risk path |
| `atlas_manage.py` | `run()` | propagates `fda_calendar`, `fda_note`, `fda_blackout` into high-candidate/report dictionaries |
| `atlas_intraday.py` | `_fda_tag()` | renders FDA metadata if present in candidate dictionaries |
| `pre_market_report.py` | `get_wavef_fda_warnings()` | pre-market report-only FDA section from engine calendar loader |
| `market_scout.py` | `discover_tickers()` | uses Benzinga news and Massive earnings; no direct FDA-discovery bucket found |
| `atlas_preopen_check.py` | `_provider_probes()` | has a health probe for direct Benzinga FDA endpoint |

Protected-source note: I used non-disclosing AST/function/call-name analysis for protected files and did not paste formula bodies, thresholds, or alpha math.

## 3. Live behavior probes

### Direct API shape — Benzinga FDA calendar

Redacted shape from `https://api.benzinga.com/api/v2.1/calendar/fda`:

```json
{
  "fda": [
    {
      "commentary": "str",
      "companies": "list",
      "created": "int",
      "date": "str",
      "drug": "dict",
      "event_type": "str",
      "id": "str",
      "nic_number": "str",
      "notes": "str",
      "outcome": "str",
      "outcome_brief": "str",
      "source_link": "str",
      "source_type": "str",
      "status": "str",
      "target_date": "str",
      "time": "str",
      "updated": "int"
    }
  ]
}
```

### Engine calendar loader

`atlas_engine._load_fda_calendar_window()` returned:

- status: string
- rows: 50
- sample row keys: `commentary`, `companies`, `created`, `date`, `drug`, `event_type`, `id`, `notes`, `outcome`, `status`, `target_date`, `time`, `updated`

### Sample ticker probes

| ticker | probe | result |
|---|---|---|
| CRSP | `check_fda_calendar()` | biotech=True, events=0, tag=None |
| CRSP | `analyze_ticker()` | score=`1/4 Pillars`, signal=`AVOID`, `fda_calendar=null`, `catalyst_reason=LLM: Analysts maintain $80 price target` |
| FATE | `check_fda_calendar()` | biotech=True, status=ok, events=1, tag=`FDA date unknown` |
| LLY | `check_fda_calendar()` | status=ok, events=1, tag=`FDA date unknown` |
| LLY | `analyze_ticker()` | score=`2/4 Pillars`, signal=`WATCH`, but `fda_calendar` not carried as dict in selected output |
| DCTH | `analyze_ticker()` | score=`3/4 Pillars`, signal=`BUY (Small)`, `fda_calendar` dict present but no FDA tag |

Production DB evidence from accidental probe writes:

| signal id | ticker | score | catalyst | warnings |
|---:|---|---|---|---|
| 31783 | CRSP | 1/4 | Catalyst YES — Recent news | earnings warning only |
| 31784 | LLY | 2/4 | Catalyst YES — Recent news | earnings warning only |
| 31785 | DCTH | 3/4 | Catalyst YES — Recent news | news sentiment + earnings warning |
| 31786 | FBRX | 2/4 | Catalyst YES — Recent news | earnings warning only |

No observed signal row showed FDA-specific catalyst text in `signals.catalyst` or `signals.warnings`.

## 4. Answers to the audit questions

| question | finding |
|---|---|
| Is the FDA provider accessible? | Yes via direct Benzinga FDA endpoint. Massive/Benzinga FDA via `api.massive.com` was not found at tested paths. |
| Is FDA fetched in code? | Yes, via `atlas_engine._load_fda_calendar_window()`. |
| Is FDA called by engine/portfolio? | Yes: `analyze_ticker`, `consider_buy`, `evaluate_pending_pullback`, and `evaluate_exit` have FDA-check call paths. |
| Does FDA data affect Fat Engine score/catalyst pillar? | Not proven. Sample scores/catalyst text remained news/earnings-driven; FDA metadata was missing or non-specific in sample candidate output. |
| Is FDA used only for FDA/biotech tickers? | `check_fda_calendar()` reports biotech classification, but code call paths can run from general ticker analysis/portfolio paths; practical event matching appears ticker/event-dependent. |
| Is FDA used by market_scout discovery? | No dedicated FDA discovery bucket found. Market scout uses Benzinga news and Massive earnings, then scans those tickers through normal engine logic. |
| Is FDA used by premarket/intraday reports? | Yes as report metadata if present: pre-market FDA warning section and intraday `_fda_tag()` rendering. |

## 5. Gaps

1. **Massive/Benzinga FDA package not verified through Massive.** News and earnings work via Massive; FDA was only verified through direct Benzinga.
2. **Direct Benzinga FDA endpoint may ignore/loosely handle ticker filter.** A CRSP-filtered query returned broad FDA rows with zero CRSP matches in the first 20 rows.
3. **FDA event match is inconsistent.** `check_fda_calendar()` found events for FATE/LLY, but `analyze_ticker()` did not reliably carry FDA metadata into candidate output.
4. **No clear FDA contribution to `signals.catalyst`, `signals.warnings`, score, BUY/AVOID, or catalyst override was proven from live samples.**
5. **Market discovery lacks an FDA-specific ticker bucket.** FDA event tickers are not being proactively fed into the scan universe as FDA candidates.

## 6. Recommended staging fix — no deployment

If Professor wants FDA catalysts to be deterministic and visible:

1. **Provider normalization module**: create staged `/tmp` helper, e.g. `atlas_fda_calendar.py`, that fetches direct Benzinga FDA calendar with redacted key handling and normalizes rows into:
   - `ticker`
   - `filing/report/publication date`
   - `target_date`
   - `event_type`
   - `drug_name`
   - `status`
   - `outcome_brief`
   - `source_endpoint`
2. **No-lookahead rule**: use only provider `created`/`updated`/publication availability fields for historical benchmarking; never use `target_date` as if it were public earlier.
3. **Discovery bucket**: add a staged FDA ticker discovery bucket for FDA rows in the next N days, capped and de-duplicated, feeding `market_scout`/intraday candidates without changing scoring.
4. **Metadata-only first gate**: propagate normalized `fda_calendar` into `analyze_ticker()` output and reports; no score change.
5. **Deterministic scoring proposal only after metadata proof**: if approved later, define a narrow FDA catalyst rule as a separate deterministic catalyst evidence flag, not LLM-written catalyst text.
6. **Staging verification**: copied DB, monkeypatch `log_signal` and Vault sync correctly, assert production DB SHA unchanged, and assert no Telegram send.

## Final verdict

`wired = PARTIALLY_WIRED`

Atlas has working direct Benzinga FDA access and code-level FDA checks, but the current behavior is not cleanly wired as a deterministic, auditable Fat Engine catalyst-scoring input. It is best treated as a report/risk overlay with incomplete candidate-metadata propagation until a staging fix proves otherwise.
