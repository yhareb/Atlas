# Intraday Advisory Authority v1 — staging evidence

## Required return

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = YES**

Staging path:

`/tmp/p0_intraday_advisory_authority_v1/`

Readiness means the exact three-file renderer package is staged and tested. Deployment still requires a separate Professor approval, fresh production backups, immediate pre-copy process/tick-window gate, exact SHA verification, targeted pyc clearing, compile, copied-DB/no-send smoke test, and rollback boundary. No deployment or restart occurred.

---

# Root cause and non-protected call chain

Current scheduled path:

1. `atlas_intraday.py::run_intraday()`
2. `_run_intraday_locked()`
3. scan returns `summary`
4. `_build_report(summary)` assembles the operator report
5. `_current_cycle_buy_signals()` reads persisted BUY-family rows
6. `_canonical_top_pick_signals()` selects report TOP PICKS
7. `_actions_lines()` renders TOP PICKS
8. `watch_list_block()` renders WATCHING
9. report snapshot is stored, then the existing send path runs

No protected strategy source was inspected or modified.

## TOP PICKS defect

Before staging:

- `_current_cycle_buy_signals()` returned only a narrow subset and omitted persisted Relative Strength, volume, and catalyst facts.
- `_canonical_top_pick_signals()` excluded open/waiting/buy-now/Too Hot and one RSI warning shape, but did **not** enforce RVOL `>=1.5` or a unified report-authority policy.
- `_rvol_line()` displayed RVOL pass/fail but had no placement authority.
- `AtlasSignal` rendering made raw BUY-family classification look like an independent practical recommendation.

Latest production snapshot 116 proved the defect:

- TOP PICKS: ELV, KO, WDFC
- ELV RVOL `0.2 / 1.5 ❌`
- KO RVOL `0.39 / 1.5 ❌`
- WDFC RSI `81`, momentum weak

## WDFC authority defect

Persisted/current sourced facts available to the renderer:

- raw TFE `BUY Small`, `3/4`
- RVOL approximately `5.5`
- RSI `81`
- weak momentum
- Relative Strength persisted as `NO (...)`
- material earnings-gap reversal supplied by the immutable incident replay

Before staging, the renderer discarded or failed to combine these facts and promoted WDFC by raw BUY-family score. Staging now keeps the raw classification unchanged and separately derives `WAIT — DO NOT CHASE`.

## Report hygiene defects

- `_header_lines()` independently rendered technical `RISK-ON` and raw macro `RISK_OFF` as peer labels.
- `_perme_engine_packet_lines()` exposed packet terminology.
- `atlas_report_blocks.py` imported implementation-style authority badges for direct human rendering.
- TOP PICKS and WAITING joined two independent facts into `Momentum Weak · No Earnings`.
- `watch_list_block()` rendered all names; diagnostics separately assumed a top-15 cap, creating `WATCHING (16)` while saying one name was omitted.

---

# Staged architecture

## New pure helper

`atlas_intraday_advisory.py`

Properties:

- Python standard library only
- no DB access
- no provider/network access
- no Telegram access
- immutable `Advisory` result
- raw TFE signal, score, pillar expression, and timestamp retained verbatim
- deterministic blockers/action/placement/freshness
- no numeric level calculation

Action set:

- `BUY NOW`
- `REVIEW`
- `WAIT — DO NOT CHASE`
- `AVOID`

TOP PICKS eligibility requires:

- raw BUY-family classification
- valid/fresh timestamp
- RVOL at least `1.5`
- deterministic renderer gates pass
- not Too Hot
- no hard advisory blocker
- action is `BUY NOW` or `REVIEW`

Blocked BUY-family candidates retain raw classification and route to:

`TECHNICALLY QUALIFIED — WAIT`

AVOID never promotes.

## Shared decision collection

`atlas_intraday.py::_current_cycle_advisory_decisions()` performs one current-cycle collection used by both TOP PICKS and WAIT:

- reads raw current-cycle rows
- merges high-candidate facts while restoring raw signal/score/pillars/timestamp afterward
- merges indicator-map RSI/momentum evidence
- parses persisted Relative Strength `YES/NO` text without changing it
- constructs explicit report gates from renderer-known facts
- derives one immutable advisory decision per ticker

TOP PICKS and WAIT consume that same collection, preventing contradictory placement.

## Required operator card

Every advisory card renders:

- `TFE CLASSIFICATION`
- `ACTION NOW`
- `WHY`
- `BLOCKERS`
- `DATA FRESHNESS`

Freshness includes exact timestamp, source, age, and fresh/stale state.

---

# Mandatory replays

## WDFC

Before:

- TOP PICKS
- raw 3/4 presentation looked actionable
- RSI 81 and weak momentum displayed, but no authority separation

After:

- not in TOP PICKS
- in `TECHNICALLY QUALIFIED — WAIT`
- `TFE CLASSIFICATION: BUY Small · score 3/4 · pillars 3/4`
- `ACTION NOW: WAIT — DO NOT CHASE`
- blockers:
  - `RSI 81 with weak momentum`
  - `Relative Strength failed`
  - `Material earnings-gap reversal`
- RVOL `5.5` is preserved as a sourced fact
- no support, VWAP, entry, breakout, or recheck levels are invented
- no reward/risk number is rendered because the immutable replay does not provide one

## ELV

Before:

- TOP PICKS despite low RVOL

After:

- not in TOP PICKS
- in `TECHNICALLY QUALIFIED — WAIT`
- raw TFE classification unchanged
- blocker: `RVOL 0.17 below 1.5`

## KO

Before:

- TOP PICKS despite low RVOL

After:

- not in TOP PICKS
- in `TECHNICALLY QUALIFIED — WAIT`
- raw TFE classification unchanged
- blocker: `RVOL 0.36 below 1.5`

## Normal valid BUY

CLEAN fixture:

- raw `BUY`, `4/4`
- fresh
- RVOL `1.8`
- all supplied report gates pass
- `ACTION NOW: BUY NOW`
- remains the sole TOP PICK in the replay

## AVOID

NOPE fixture:

- raw `AVOID`, `4/4` remains unchanged
- `ACTION NOW: AVOID`
- never appears in TOP PICKS or technically-qualified WAIT

Generated evidence:

`/tmp/p0_intraday_advisory_authority_v1/output/incident_replay.txt`

---

# Report hygiene

Before examples from production snapshot 116:

- `🟢 RISK-ON ... RISK_OFF`
- `Perme Engine Packet: ANNOTATE ... STRUCTURED_MACRO_FACTS`
- `[DB]`, `[TFE]`, `[PROVIDER]`, `[RENDER-CALC]` implementation badges in human cards
- `Momentum Weak · No Earnings`
- `WATCHING (16)` with item 16 displayed while diagnostics called it omitted

After:

- one operator regime label only
- packet/machine section removed from human report
- implementation badges translated to natural labels such as `Recorded`, `TFE`, `Market data`, `Calculated`, `Reference`
- momentum and earnings wording separated
- WATCHING shows `15 shown of N` and lists exact omitted names

The required phrase `TFE CLASSIFICATION` remains because it is the explicit authority contract, not an internal badge.

---

# Regime precedence rule

Conservative deterministic precedence:

1. any sourced technical or macro risk-off state → `RISK-OFF`
2. otherwise any sourced caution state → `CAUTION`
3. otherwise explicit technical risk-on → `RISK-ON`
4. insufficient/ambiguous state → `CAUTION`

Only one operator regime token is rendered. Conflicting source facts remain in natural explanatory text such as `defensive macro sentiment`; a second `RISK_OFF` token is not shown.

---

# Earnings source rule

Deterministic wording:

1. catalyst evidence containing earnings, guidance, or earnings-related analyst action → `Earnings-related catalyst present`, with timestamp when supplied
2. stale evidence → `Earnings information stale`, with timestamp or explicit missing timestamp
3. explicit sourced no-earnings flag → `No earnings catalyst reported by source`
4. otherwise → `Earnings information missing`

Weak momentum never implies “No Earnings.” Missing and stale evidence are not guessed.

---

# WATCHING cap

`watch_list_block(..., cap=15)` now:

- deduplicates and sorts first
- displays at most the configured cap
- reports exact shown/total count
- enumerates exact omitted labels

Fixture result:

- `WATCHING (15 shown of 18)`
- 15 numbered names
- omitted: `T15, T16, T17`

The intraday caller passes `summary['watching_cap']` when configured and defaults to 15.

---

# Files and final SHA256

Production-ready staged files:

- `atlas_intraday.py`
  - `438427606559dbd811a6367ac0005e7831299e7384f29ea7b2961c1e1cef075d`
- `atlas_intraday_advisory.py`
  - final SHA in artifact manifest
- `atlas_report_blocks.py`
  - `cb9bd50ea46a9d9d4fc99785af0e2fa516e261d0bfe22b2ce40b35f2edcddb65`

Fixtures/tests/evidence:

- `fixtures/advisory_fixtures_v1.json`
- `tests/test_advisory.py`
- `tests/test_atlas_intraday_integration.py`
- `tests/render_evidence.py`
- `output/incident_replay.txt`
- `output/atlas_intraday.diff`
- `output/atlas_report_blocks.diff`

A final manifest records all current SHAs after the final verification run.

No `/tmp` staging path exists inside the three production-ready modules.

---

# Verification

## Compile

All staged Python files compiled successfully.

## Tests

```text
Ran 11 tests
OK
```

Coverage includes:

- exact WDFC replay
- persisted Relative Strength `NO` parsing
- ELV/KO RVOL failures
- clean BUY promotion
- AVOID non-promotion
- production schema fallback from score to exact pillar expression
- stale/missing freshness failure
- regime precedence
- earnings consistency
- human-label hygiene
- watching cap/count/omitted names
- full staged `atlas_intraday._build_report()` integration render
- no Telegram call from the integration harness

One environment-only urllib3/LibreSSL warning appeared during staged import; it did not affect test results.

## No invented levels

The WDFC/ELV/KO incident integration fixtures contain no entry, support, VWAP, breakout, or recheck levels. Assertions prohibit these invented labels in the WAIT section.

## No DB/Telegram side effects

- pure helper has zero SQL write literals and zero Telegram calls
- report blocks have zero DB calls and zero Telegram calls
- staged intraday retains the production script’s pre-existing imports/write/send paths byte-for-byte outside the renderer delta; no new write/send path was added
- integration test stubs `atlas_db` to `/dev/null`, stubs the send function, and verifies send count `0`

---

# Strategy invariants

- raw TFE classifications unchanged
- raw scores/pillar expressions unchanged
- AVOID unchanged
- no Fat Engine scoring/pillar edit
- no Too Hot threshold edit
- no stop or target edit
- no sizing, broker, trade-status, or cash edit
- no protected strategy-file change
- no production DB write
- no Telegram test
- LLM has no calculation or placement authority

Production protected file SHAs remained:

- `atlas_engine.py`: `a3908a609b37533e6daa106ade23f3a886c1ad628cb6c847ea4c5bc6448a071a`
- `atlas_portfolio.py`: `8fed8d2985bb6ff4ac661dfa75f447f5d30b7325f335dede60232329a90b1444`

The staged intraday file retains the same pre-existing protected imports as production; the patch adds none.

---

# Production invariants

Production source SHAs remained:

- `atlas_intraday.py`: `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_report_blocks.py`: `b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`

Production DB integrity remained `ok`. Stable authority counts remained:

- trades `105`
- cash_ledger `25`
- pending_pullbacks `54`
- handoff `16`
- position_lots `68`
- portfolio_event_journal `92`

`signals` and the DB file SHA changed during the long staging window because normal scheduled Atlas cycles continued. The staging integration did not open the production DB; timestamps and report snapshots attribute the growth to scheduled production activity.

---

# Likely production deployment scope

Exactly three files:

1. `/Users/yasser/scripts/atlas_intraday.py`
2. `/Users/yasser/scripts/atlas_intraday_advisory.py` — new
3. `/Users/yasser/scripts/atlas_report_blocks.py`

No `atlas_perme_engine_packet.py`, `atlas_report_authority.py`, protected strategy file, DB schema/data, config, SOUL, skill, route, or schedule change is required.

Restart requirement: **NO daemon restart expected**. The scheduled Python process starts fresh each cycle. Deployment still must occur only in a verified idle/tick-safe window.

---

# Rollback plan

For a later authorized deployment:

1. create timestamped archive backups of existing `atlas_intraday.py` and `atlas_report_blocks.py`
2. verify `atlas_intraday_advisory.py` does not unexpectedly pre-exist; if it exists, back it up and stop on unknown drift
3. copy the exact three staged files atomically after the final idle check
4. clear only the three corresponding local/macOS Python caches
5. compile and SHA verify

Rollback:

1. idle/tick-window gate
2. restore the two archived production files
3. remove the newly introduced helper only if its predeploy state was absent; otherwise restore its backup
4. clear only corresponding bytecode caches
5. compile, verify original SHAs, and run the same no-send smoke harness

---

## Final

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = YES**

Stop condition observed: staging evidence only; no deploy or restart performed.
