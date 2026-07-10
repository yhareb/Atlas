# P0 Atlas Session Guard + Conversational Advisory — Staging Report

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = NO**

Both requested packages were built and exercised exclusively under `/tmp`. No gateway was restarted; no production SOUL, skill, config, code, schedule, Telegram route, or trading logic was changed.

`deployment_ready = NO` is deliberate: Package B passed focused staging, but Package A is an external guard prototype and has not yet been wired through a copied Hermes gateway/session lifecycle. A production deployment plan must first define the supported integration point that consumes `ROTATE`, creates the new session, and injects the compact handoff without mutating the live conversation mid-turn.

## Package A — Atlas session/context guard

Staging root:

`/tmp/p0_atlas_session_guard_v1/`

### Hermes configuration evidence

Hermes Agent:

- Version: `0.16.0 (2026.6.5)`, upstream `a904ff17`
- Production Atlas compression: enabled, threshold `0.5`, target ratio `0.2`, protect last `20`, protect first `3`
- Production `abort_on_summary_failure=false`
- Production `codex_gpt55_autoraise=true`
- Production `session_reset.mode=none`

Supported native reset policy found in Hermes source/setup:

- `idle`
- `daily`
- `both`
- `none`

Hermes setup explicitly documents idle/daily reset and `/new`/`/reset`. No supported token-count, message-count, or active-session size cap was found in v0.16 configuration. `session_store_max_age_days` is pruning by inactivity age and is not an active-context cap.

Therefore the package uses:

1. A supported idle-reset backstop in a staged config copy.
2. A separate read-only external preflight guard for active-session size.

No unsupported Hermes setting was invented.

### Staged config delta

`config.staged.yaml` is a production config copy with only:

- `compression.codex_gpt55_autoraise: true → false`
- `session_reset.mode: none → idle`
- `session_reset.idle_minutes: 1440`
- `session_reset.notify: true`

Primary model/provider/base URL and the currently absent fallback list were preserved exactly. SOUL, skills, toolsets, deterministic authority, and platform configuration were not changed in this package.

The 24-hour idle reset is only a supported hygiene backstop. It does not solve an actively growing chat; the external cap does.

### Guard design

`session_guard.py` opens a session DB copy read-only and returns:

- `CONTINUE`, exit `0`
- `ROTATE`, exit `20`

Default preflight caps:

- active messages: `120`
- estimated/stored tokens: `120,000`
- message characters: `400,000`
- compact handoff: at most `8,000` characters

It uses stored per-message token counts where available and a conservative character estimate otherwise. On rotation it emits `atlas-session-handoff/v1`, retaining the latest relevant ticker envelope and a bounded recent envelope. It never calls compression, `/new`, or `/reset`; never mutates `state.db`; never restarts the gateway; and never runs the wrapped command after a `ROTATE` decision.

A later deployment design should place this preflight before the model request, then hand `ROTATE` to a supported session-reset integration. It must not alter prior messages mid-conversation because Hermes prompt caching and role alternation require a byte-stable session history.

### Oversized copied-session proof

Fixture decision:

```text
decision=ROTATE
reasons=message_cap,token_cap,character_cap
messages=172
estimated_tokens=147270
characters=586060
handoff_json_chars=7140
latest_ticker_retained=true
compression_invoked=false
guard_exit=20
```

This proves the guard rejects the oversized fixture before invoking a model/compression path and preserves a compact WDFC handoff.

### Package A tests

```text
test_normal_followup_continues_without_compression ... ok
test_oversized_rotates_and_context_is_bounded ... ok
test_recent_wdfc_envelope_retained ... ok
test_wrapper_blocks_command_on_rotate_and_runs_on_continue ... ok

Ran 4 tests in 0.078s
OK
```

Acceptance interpretation:

- No compression during tested normal follow-up: **PASS at guard unit/wrapper level**
- Bounded oversized-session handoff: **PASS**
- Latest ticker context retained: **PASS**
- Controlled production session rotation E2E: **NOT YET PROVEN**; requires a separate copied-gateway integration stage
- Gateway restart/production change: **NONE**

### Package A files and SHAs

```text
21c132296a984959bb07a7e7da8db6df79338583e992608d861a565fa000d7f8  session_guard.py
89de7bd8421ed95bf7f9db1206eb9033c46914717e863f5f67756df60f3269e6  config.staged.yaml
e48190f39e37246959e690974536872b21b4261c992bbeeee174e8780eb9af30  tests/test_session_guard.py
f7d56c5e80f387d89c9e2d8357e885214c971ea57fe5ee57ecd247b1bdd23e48  out/oversized-copy-decision.json
07f9735cf06b0729df10ee9f26570489040ac0488db711e61dcb4da67653af67  README.md
c968709431a7b99c8566abe5b5d8fc47acfcc2767995ae75e102f29eae51438e  fixtures/state.production-copy.db
```

## Package B — Atlas conversational advisory router

Staging root:

`/tmp/p0_atlas_conversational_advisory_v1/`

### Staged design

`atlas_conversation_router.py` is additive and imports neither protected trading module. It provides:

- immutable structured-envelope input;
- SQLite `mode=ro&immutable=1` query access;
- bounded lookup of newest signal and at most 20 recent report manifests;
- deterministic metrics;
- two routing modes;
- bounded, injected targeted-news enrichment;
- explicit TFE/operator authority contract;
- no Telegram path and no SQL write path.

### Query classification

`FRESH_TFE_REQUIRED` when any is true:

- no recent structured result;
- stale result;
- exact/current/fresh number request;
- movement at least `1%`;
- movement at least `0.25 ATR`;
- deterministic boundary crossed;
- material catalyst/news change;
- regime change;
- report/signal conflict.

`CONVERSATIONAL_CONFIRMATION` when a fresh deterministic result exists and Professor asks whether to act, chase, wait, or trust it.

Every forced-refresh reason is returned in `invalidation_reasons` and rendered under `DATA FRESHNESS`. A fresh single-ticker execution is marked `fresh_run_occurred=true`.

### Freshness defaults

- Regular-hours TFE result: `300s`
- Gap/breakout act-now advice: `180s`
- Gap-name threshold for stricter TTL: `8%`
- Price invalidation: `1%`
- ATR invalidation: `0.25 ATR`

The thresholds are contained in immutable `RouterPolicy` fields and can be configured without changing TFE.

### Deterministic calculations

Python alone calculates:

- freshness age;
- applicable TTL;
- price movement since analysis;
- ATR movement fraction;
- gap percentage where source data permits;
- upside/downside components;
- reward/risk.

The LLM-facing renderer receives calculated values. It does not calculate, rewrite, or invent signal, score, entry, stop, target, RSI, RVOL, or catalyst facts.

### Authority contract

Rendered sections:

1. `TFE CLASSIFICATION`
2. `ACTION NOW`
3. `WHY`
4. `RECHECK`
5. `DATA FRESHNESS`

Rules proven:

- Raw TFE signal stays unchanged.
- BUY can receive `WAIT — DO NOT CHASE` as a separate advisory action.
- AVOID returns `AVOID` and cannot be promoted to BUY.
- A normal sourced BUY without caution conditions may return `BUY NOW`.
- No trade, DB, stop, target, signal, sizing, Too Hot, broker, or Telegram mutation exists.

### WDFC replay output

```text
ATLAS ADVISORY — WDFC
ROUTE: CONVERSATIONAL_CONFIRMATION
TFE CLASSIFICATION:
BUY Small, 3/4 Pillars | timestamp 2026-07-10T14:12:19Z | source immutable envelope
ACTION NOW:
WAIT — DO NOT CHASE
WHY:
gap 22.0%; RSI 81; weak momentum; failed relative strength; reward/risk 0.9573
RECHECK:
stabilization, pullback improving reward/risk, or fresh TFE run after material change
DATA FRESHNESS:
41s old / TTL 180s | fresh_run_occurred=false | invalidated_by=none
ENTRY / STOP: $289.77 / $273.86
REWARD/RISK: 0.9573 | GAP: 22.00%
TARGETED NEWS: not requested
LATENCY: 0.0003s (router harness latency; not a live provider benchmark)
```

This resolves the prior contradiction without changing TFE.

### Targeted current-news mode

- Receives one validated ticker only.
- Fetcher is injected; no full-market scan is possible through this API.
- Timeout is configurable and hard-capped at `10s`.
- Results are capped at five items.
- Missing fetcher, empty result, exception, and timeout all degrade transparently to an advisory without targeted news.
- News cannot supply or alter deterministic numeric fields.

A production plan should wire only an already-approved existing single-ticker provider helper, not the full engine/universe path.

### Package B tests

```text
test_atr_quarter_move_invalidates_even_below_one_percent ... ok
test_cached_p95_under_five_seconds ... ok
test_exact_wdfc_fixture_calculations_and_contract ... ok
test_fresh_stub_single_ticker_latency_under_30_seconds ... ok
test_fresh_without_injected_runner_fails_closed ... ok
test_gap_ttl_conflict_and_other_invalidation_reasons ... ok
test_immutable_envelope_defensive_copy ... ok
test_no_telegram_or_protected_imports ... ok
test_normal_buy_may_be_buy_now_and_avoid_never_promoted ... ok
test_report_snapshot_bounded_fallback ... ok
test_route_matrix_fresh_current_stale_missing_and_price_move ... ok
test_sqlite_read_only_signals_and_no_writes ... ok
test_targeted_news_single_ticker_capped_and_fallbacks ... ok
test_targeted_news_timeout_is_bounded_fallback ... ok

Ran 14 tests in 0.047s
OK
```

Latency:

- Cached follow-up harness p95: `0.000013s` — PASS under 5s.
- Injected healthy TFE stub: `0.000120s` — harness-only, not live-provider proof.
- Separate real single-ticker WDFC probes against an isolated copied DB: `8.30s`, `9.43s`, `9.07s` — all PASS under 30s.

The real probe used live provider helpers but pointed Atlas DB/audit writes at a copied DB and suppressed the SQLite audit callback. Production DB SHA changed during the market-hours interval because the normal scheduler was active; production counts/timestamps showed ordinary scheduler growth. No production script/config was modified by the probe.

### Package B files and SHAs

```text
72e0e7f6b71376bc69c1e64489aa304ed36d76b834837c37ec61c887ed7756e8  atlas_conversation_router.py
a9872d223b75b45d873718bbd26bc5fb94482459afb4f2ffa18995e3b4ed42ae  tests/test_router.py
7c5196b108b8d71d767da8c1d02ab2045e3b8663310fa6f30c07f2677f01c9f5  fixtures/wdfc_incident_20260710.json
98095938a5ef37665391e14a38dc14e40e565bf597e6504511a4d6b38dcd9242  SOUL.md
0fc4c66fa5d0700eb3723778e3bb6b9e0232940f7acfc51020d6a5393b339021  atlas_trading/SKILL.md
b20b4da86b1317622533efa33b7081c50425e0c2fc77d00326256de2512fdcde  wdfc_replay_output.txt
0468451db77256e2409f1aa041244dae85ab1bb6d958038b8185449d2c6855ae  README.md
```

Copied benchmark DB is test scaffolding, not a deployment artifact:

`2c1658b3c587f08e1749c0db71418e6234f5f1b5511f86aee01b9a11a31ed00d  fixtures/fresh_tfe_benchmark.db`

## No-change / strategy invariants

Production SHAs at final verification:

```text
45355bae967b648994d93a55cffff7d1fc5b99e6f23382c3cbc30d95dd63be7d  Atlas config.yaml
52a8442bc560fa0626ae761741a3d56670aeea23d693f697fad8f2a13ab74324  Atlas SOUL.md
9fbb9e34d5c13ba7f0d714c4d5e939d998972fbad30bc8db5ac322be2d44d240  Atlas atlas_trading/SKILL.md
a3908a609b37533e6daa106ade23f3a886c1ad628cb6c847ea4c5bc6448a071a  atlas_engine.py
8fed8d2985bb6ff4ac661dfa75f447f5d30b7325f335dede60232329a90b1444  atlas_portfolio.py
```

Production DB final integrity: `ok`. Its SHA/counts changed during staging because normal scheduled intraday cycles continued; AtlasOps did not disable the scheduler, and all staging/test DB access was directed to copies or read-only handles.

No production cache was cleared. No SOUL/skill/config/code/DB was written. No Telegram send/test occurred. No gateway restart occurred.

## Likely production scope for a later plan

Package A:

- Atlas `config.yaml`: approved delta for `codex_gpt55_autoraise=false` and supported reset policy.
- A gateway-edge preflight integration or external supervisor that runs before model invocation, consumes `ROTATE`, creates a fresh supported session, and inserts the compact handoff once.
- No Hermes core modification should be assumed until the copied-gateway E2E design proves an existing hook/edge integration is sufficient.

Package B:

- New `/Users/yasser/scripts/atlas_conversation_router.py`.
- Atlas SOUL and `atlas_trading/SKILL.md` routing/authority wording.
- Optional read-only latest-result helper/envelope store; it must not write trading tables.
- An approved injected single-ticker TFE runner and approved bounded single-ticker news helper.

No `atlas_engine.py` or `atlas_portfolio.py` change is needed for the operator-facing design.

## Rollback design

Nothing is deployed, so current rollback is deletion of the two `/tmp` package roots.

For a later production rollout:

1. Back up Atlas config, SOUL, skill, and every new/wired operator-layer file.
2. Deploy Package B additive module first with no-send copied-DB tests.
3. Stage Package A copied-gateway E2E separately; do not combine it with Package B until rotation/handoff is proven.
4. Roll back configuration/files from exact backups and remove only added modules/hooks.
5. A gateway restart, if eventually required, needs separate explicit approval and a planned external restart/verification window.
6. No DB rollback should be needed because neither package may write production DB.

## Final verdict

- Package A guard logic: **PASS staging proof; integration incomplete**
- Package B router: **PASS focused staging proof**
- Production touched: **NO**
- Deployment ready: **NO** — copied-gateway controlled-rotation E2E remains the blocking gate
