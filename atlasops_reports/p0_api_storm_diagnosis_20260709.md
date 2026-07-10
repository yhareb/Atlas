# P0 API Storm Diagnosis — Read-Only Report

Generated: 2026-07-10 (session time, host now ~00:4x ET, storm occurred 15:30–16:00 ET on 2026-07-09)

Scope: read-only diagnosis only. No patch, no deploy, no DB write, no Telegram, no broker action, no force kill, no scheduler change. Nothing was modified.

## ROOT_CAUSE

**Host-level network/DNS outage**, not an application bug and not amplified by any tonight's deployment.

Evidence:
- All failing calls during the 15:30–16:00 ET window show either `NameResolutionError` (DNS failed to resolve `api.massive.com`, `eodhd.com`, `api.benzinga.com`) or `NewConnectionError: [Errno 51] Network is unreachable` (raw OS-level network-down error).
- These errors hit **every provider simultaneously** — Massive, EODHD, Benzinga, and Telegram (`api.telegram.org`) all failed with the same network-unreachable signature in the same cycle. A single provider outage would not explain a simultaneous failure across four independent, unrelated hostnames.
- Live re-check during this diagnosis confirmed the host is *currently* also unable to resolve DNS (`nslookup api.massive.com` → "connection timed out; no servers could be reached"; `ping 8.8.8.8` → 100% packet loss). This is independent confirmation that host-level network/DNS instability is an ongoing environmental condition on this Mac, not a one-off transient blip that only affected Atlas.
- The two intraday cycles immediately before the storm (15:30 ET, 15:40 ET) show **zero** network errors and completed cleanly (`telegram report success=True` both times). The 15:50 ET cycle is the one with the storm signature (127 network-unreachable/DNS-fail lines). This is consistent with an outage that started sometime between 15:40 and 15:50 ET, not a gradually-building code problem.

## ACTIVE_PROCESSES

Checked at diagnosis time (now, well after the storm):

| process | running now? |
|---|---|
| `atlas_intraday.py` | NO |
| `atlas_manage.py` | NO |
| `market_scout.py` | NO |
| `pre_market_report.py` | NO |
| duplicate scanner/provider jobs | NO — only long-running `atlas_ingest.py` (Docling/RAG ingest daemon, unrelated to market-data providers) was found |

Relevant launchd labels all `state = not running`, `last exit code = 0`: `com.atlas.intraday`, `com.atlas.api_audit`, `com.atlas.premarket`, `com.atlas.macro.premarket`, `com.atlas.macro.postmarket`, `com.atlas.eod.positions`.

## OVERLAP_STATUS

**No overlap.** Cycles ran sequentially and cleanly:

- 15:30 ET cycle: started, completed, `telegram report success=True`, **before** 15:40 ET cycle started.
- 15:40 ET cycle: started, completed, `telegram report success=True`, **before** 15:50 ET cycle started.
- 15:50 ET cycle (the storm cycle): ran alone, no second concurrent intraday process, no duplicate scanner detected.

No evidence of two scan cycles running at once, no lock-file contention, no duplicate provider-call amplification from parallel processes.

## TOP_PROVIDER_FAILURES

From the `com.atlas.api_audit` 16:00 ET report (30-minute window ending 16:00 ET, i.e. covering the storm):

| provider | calls | ok | fail |
|---|---:|---:|---:|
| Massive | 472 | 311 | **161** |
| EODHD | 27 | 2 | **25** |
| Benzinga | 13 | 12 | 1 |
| Perme | 4 | 4 | 0 |

Immediately preceding 30-min window (15:30 ET report) and following window (16:30 ET, outside report hours) both showed **0 failures** — confirming the failure spike is isolated to the single 15:30–16:00 ET window, matching the network-outage timing exactly.

## TOP_TICKER_RETRY_LOOPS

No runaway retry loop found. In the storm cycle (15:50 ET), each of a set of ~12 tickers (`VLO`, `TRV`, `SEIC`, `SBUX`, `RPRX`, `PSMT`, `MUFG`, `JNJ`, `INCY`, `ILMN`, `CYTK`, `AAPL`) was called **7 times** by `get_massive_aggs()` — but this is normal: the pipeline calls the same ticker's price data at multiple distinct, legitimate call sites in one cycle (pillar checks, pending-pullback trigger check, indicator-info map, and live-price map used for the WAITING FOR DIP report section). All 7 calls per ticker failed for the same reason (DNS/network down), which multiplies the *failure count* but is not a code-level retry loop — no single call site looped more than its designed single attempt (`atlas_engine.get_massive_aggs()` has no retry logic at all: one `try/except`, no backoff).

## GOVERNOR_STATUS

- `atlas_provider_guard.py` (used by `market_scout.py`/report scripts) has a real retry/backoff governor: Massive gets 1 retry with 2s backoff (`MASSIVE_RETRY_BACKOFF_SECONDS = (2,)`), EODHD gets 1 retry on HTTP 429 after 60s. This is intact and was not bypassed — it correctly attempted its one retry and then failed closed (expected behavior for a real network outage, not a bug).
- `atlas_engine.get_massive_aggs()` (used inside the ticker pillar-check loop) does **not** go through the governor at all — it calls `_audit_get()` directly with a bare `try/except`, no retry. This is pre-existing behavior (not something introduced tonight) and is the reason failures multiplied cleanly per call-site rather than compounding via retries. No evidence any call cap was bypassed; the multiplication comes from the number of distinct call sites per ticker per cycle, not from retry amplification.
- No evidence of a call-cap override, rate-limit disable, or governor short-circuit in tonight's diffs.

## FDA_CALL_IMPACT

**Zero impact.** The FDA selective-wiring deploy did not contribute to the storm:

- FDA calendar cache (`/tmp/atlas_fda_calendar_cache/fda_calendar_stats.json`) shows `endpoint_calls_total: 1`, `generated_at: 2026-07-09T17:30:15Z` (13:30 ET) — the one-and-only FDA endpoint fetch for the day happened **2+ hours before** the storm window and is still within its 6-hour cache TTL, so **zero additional FDA calls were made during the storm window**.
- Zero `FDA calendar`/`atlas_fda_calendar`/`benzinga...fda`/`calendar/fda` log lines appear anywhere in the storm cycle or the two preceding cycles.
- `market_scout.py`'s new FDA discovery bucket calls `atlas_fda_calendar.discover_fda_tickers()`, which reads the cache/index only (no live fetch) once the cache is warm — consistent with the one-call-per-scan-window design verified during P0B2/P0B3 staging.

## DEPLOY_CAUSALITY

None of tonight's three deployments caused or amplified the storm:

| deploy | completed (UTC) | completed (ET) | storm window (15:30–16:00 ET) |
|---|---|---|---|
| FDA P0B2 + P0B3 selective wiring | 2026-07-09T17:27:41Z | 13:27:41 ET | **before** storm (deployed ~2h before) |
| P0P2a Profit Protection Overlay | 2026-07-09T20:44:48Z | 16:44:48 ET | **after** storm (deployed ~45 min after) |
| FDA P0B4 report-side cleanup | 2026-07-09T20:48:18Z | 16:48:18 ET | **after** storm (deployed ~48 min after) |

- FDA P0B2/P0B3 was live during the two clean cycles immediately before the storm (15:30 ET, 15:40 ET) with zero errors and normal Telegram success — proving the FDA deploy itself was not destabilizing the scan.
- Profit Protection and P0B4 were deployed entirely after the storm window ended, so they cannot be the cause by simple temporal ordering.
- All three deploys' own post-deploy verification (already on record) showed production DB SHA/counts unchanged and no forbidden static-scan hits, consistent with them being inert with respect to network call volume.

## SAFE_FIX_PLAN

Read-only recommendations only — **not implemented, no approval assumed**:

1. **Add retry/backoff to `atlas_engine.get_massive_aggs()`** by routing it through the existing `atlas_provider_guard.massive_get_json()` governor instead of a bare `_audit_get()` call. This would give the ticker pillar-check loop the same 1-retry/2s-backoff resilience `market_scout.py` already has, reducing (not eliminating) failure count during a brief transient outage — but would not have prevented tonight's storm since the outage lasted the full report window.
2. **Add a short DNS/connectivity pre-check** at the very start of the intraday scan loop (e.g. a lightweight resolve of one always-up host) so a full network outage can short-circuit the scan into a single clear "network down, skipping full scan" log line instead of ~187 individual provider failures — purely diagnostic/logging improvement, no scoring/decision impact.
3. **No change needed to FDA selective wiring** — it is already correctly isolated to one fetch per scan window and was not implicated.
4. **No change needed to Profit Protection overlay or P0B4** — both are report-render-only and were not active during the storm window.
5. Recommend Prof check the Mac's own network/DNS stability independently (this diagnosis found the host still has DNS/connectivity issues at the time of this read-only check), since that is outside Atlas code and cannot be fixed by any Atlas-side patch.

`approval_required = YES` — nothing above should be implemented without Prof's explicit go-ahead.
