# Intraday Advisory Authority v1 — canonical routing remediation

## Final

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = YES**

Workspace: `/tmp/p0_intraday_advisory_authority_v1/`

No deployment, restart, production DB write, Telegram send, strategy/scoring/classification change, broker action, reconciliation deployment, or Position Management work occurred.

---

# Exact live root cause

Snapshot 120 was generated at `2026-07-10 19:46:02`. The live log reconstructed the current-cycle signal boundary as:

`_before_scan_signal_id = 35972`

Both missing BUY-family rows were inside that cycle:

- KO — signal ID `35988`, `19:44:24`, raw `🟡 BUY (Small)`, `3/4 Pillars`, RVOL `0.42`
- ELV — signal ID `36018`, `19:44:52`, raw `🟡 BUY (Small)`, `3/4 Pillars`, RVOL `0.24`

WDFC was also current-cycle but no longer BUY-family:

- WDFC — signal ID `36006`, `19:44:41`, raw `⚪ WATCH`, `2/4 Pillars`, RVOL `5.96`

The SQL boundary and score/time filters included ELV and KO. Neither was open nor WAITING/pending. There was one row per ticker, so deduplication was not the cause.

The exact failure was classification-only string handling in `atlas_intraday_advisory.py`:

- `_upper('🟡 BUY (Small)')` produced `🟡 BUY (SMALL)`
- code tested `signal.startswith(BUY_FAMILY)`
- the leading emoji made this false
- ELV/KO fell through to generic `REVIEW`, `top_pick=False`
- TOP PICKS requires `top_pick=True`
- qualified WAIT requires status `TECHNICALLY QUALIFIED — WAIT`
- therefore both rows silently disappeared

High-candidate merge preserved the raw signal and did not cause the loss. Snapshot/report timing was consistent.

---

# Staged code changes

## `atlas_intraday_advisory.py`

Added classification-only normalization:

- strips leading emoji/punctuation
- normalizes punctuation/spacing
- preserves the raw signal verbatim in the operator contract
- classifies normalized families as BUY, WATCH, AVOID, or OTHER

Added immutable `AdvisoryRouting` and `build_advisory_routing()`.

Every current-cycle BUY-family ticker is routed exactly once to:

1. BUY NOW
2. TOP PICKS
3. TECHNICALLY QUALIFIED — WAIT
4. explicitly excluded with a deterministic reason

Explicit reasons include:

- open position
- pending entry/WAITING
- stale data
- duplicate current-cycle BUY rows
- Too Hot
- malformed/incomplete score or report gates
- top-pick display cap

WATCH and AVOID are separate non-BUY destinations.

## `atlas_intraday.py`

- builds one enriched current-cycle decision collection
- builds one canonical routing result from that collection
- TOP PICKS and qualified WAIT consume the same routing object
- existing BUY NOW rendering remains intact
- current-cycle WATCH is added only to WATCHING
- routing diagnostics are attached to the report summary
- report diagnostics render the exact accounting equation and explicit exclusion reasons
- a failed equation raises instead of silently rendering

The diagnostic invariant is:

`current_buy_family = buy_now + top_picks + qualified_wait + explicitly_excluded`

All destination sets are mutually exclusive.

`atlas_report_blocks.py` retains the prior shared human-label boundary fix.

---

# Final production-ready SHAs

- `atlas_intraday.py`
  - `8094a472b8f60faf7d2e791bfa4cb65056cb3b430f20de227e030adece428fee`
- `atlas_intraday_advisory.py`
  - `25715b07f17df58b509304cb88ff1cea3712f5aa5fdeb941515e6917cc7125d7`
- `atlas_report_blocks.py`
  - `c19c84ab13f823838d7c4e1993685675a05a7d13db8a65ae04df9627c7c3564e`

Fixture/test SHAs:

- snapshot-120 fixture: `141c7414c961cb137401a336a00fd1b0a31faf2130a670be12794d5857148f53`
- canonical routing tests: `fdf40a436211b5498fe12f9062cc3103112a066c0353a68c8bdb2c90503bfdf5`
- integration test: `98e4a55bafa6a31cd2f85d7910eac607f1e5059703379f92618e0eec30344803`
- replay generator: `068b982392abc039bcbaffa018954fb796caa80904be1edf0e05290fb37ceb93`

---

# Snapshot-120 live-equivalent replay

Immutable fixture:

`/tmp/p0_intraday_advisory_authority_v1/fixtures/snapshot_120_live_equivalent.json`

Replay output:

`/tmp/p0_intraday_advisory_authority_v1/output/snapshot_120_replay.json`

Destinations:

- ELV → `TECHNICALLY QUALIFIED — WAIT`
- KO → `TECHNICALLY QUALIFIED — WAIT`
- WDFC → WATCH path
- WDFC not in qualified WAIT
- no TOP PICK or BUY NOW in this three-row incident fixture
- no exclusions required

Raw signals remain byte-for-byte fixture values:

- ELV `🟡 BUY (Small)`
- KO `🟡 BUY (Small)`
- WDFC `⚪ WATCH`

No invented levels were added.

---

# Reconciliation equation and exclusion evidence

Snapshot-120 replay:

- current BUY-family: `{ELV, KO}`
- BUY NOW: `{}`
- TOP PICKS: `{}`
- qualified WAIT: `{ELV, KO}`
- explicitly excluded: `{}`
- WATCH: `{WDFC}`
- equation: **true**

Additional tests prove:

- clean BUY → BUY NOW
- AVOID → avoid-only, never promoted
- open BUY → explicit `open position`
- pending BUY → explicit `pending entry/WAITING`
- stale BUY → explicit `stale data`
- Too Hot BUY → explicit `Too Hot`
- duplicate BUY → explicit duplicate reason
- malformed score → explicit malformed/incomplete reason
- no ticker appears in multiple BUY-family destinations
- union of destinations exactly equals current BUY-family set

---

# Test results

All staged Python files compiled successfully.

Full suite:

```text
Ran 16 tests
OK
```

Coverage includes all corrected mandatory placement tests plus existing hygiene, earnings, regime, WATCHING-cap, raw-label, no-invented-level, and no-send tests.

Direct shared-block badge regression: **PASS**.

Staged module-origin proof: **PASS**.

Production-dependency copied-DB/no-Telegram suite:

```text
Ran 16 tests
OK
```

- production DB unchanged during smoke
- copied DB unchanged
- integrity `ok`
- FK violations `0`
- zero Telegram sends

Evidence:

- `output/canonical_routing_tests_final.txt`
- `output/canonical_production_path_tests.txt`
- `output/direct_shared_blocks_regression_final.json`
- `output/module_origin_final.json`
- `output/canonical_smoke_before.json`
- `output/canonical_smoke_after.json`

---

# Production invariants

Production remains at rolled-back baseline:

- `atlas_intraday.py`
  - `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_report_blocks.py`
  - `b2d3bb37644bcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`
- `atlas_intraday_advisory.py`
  - absent

Production DB after final verification:

- SHA `c64b0ebecd916acf893df34a75f03bdc6d381ef190ba4d703ed21174940a8654`
- integrity `ok`
- FK violations `0`
- trades `105`
- cash_ledger `25`
- pending_pullbacks `54`
- handoff `16`
- position_lots `68`
- portfolio_event_journal `92`
- report_snapshots `121`
- signals `36094`

All source and DB values matched the final remediation baseline after testing.

No strategy, scoring, BUY/AVOID, Too Hot, stop, target, sizing, cash, broker, trade-status, protected-file, scheduler, route, or Telegram behavior changed.

---

## Return

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = YES**

The live disappearance cause is fixed, current-cycle BUY-family accounting is exhaustive and mutually exclusive, snapshot 120 replays correctly, and no deployment was performed.
