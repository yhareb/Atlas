# Intraday Advisory Authority v1 — staging-only remediation

## Required return

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = YES**

Workspace:

`/tmp/p0_intraday_advisory_authority_v1/`

No deployment, restart, production DB write, strategy/scoring/classification change, Telegram send, broker action, or reconciliation work occurred.

---

# Exact code-level fix

Changed production-ready source:

`atlas_report_blocks.py`

The shared human renderer no longer exposes the raw return value from:

`atlas_report_authority.normalize_price_source()`

New local boundary behavior:

1. import the authority normalizer as `_authority_normalize_price_source`;
2. preserve `atlas_report_authority.py` unchanged for diagnostic/non-human consumers;
3. translate the returned authority class inside `atlas_report_blocks.py` through `_human_source_label()`;
4. map raw implementation labels to human labels before any shared block renders them:
   - `[DB]` / `DB` → `Recorded`
   - `[TFE]` / `TFE` → `TFE`
   - `[PROVIDER]` / `PROVIDER` → `Market data`
   - `[CACHE]` / `CACHE` → `Cached market data`
   - `[FALLBACK]` / `FALLBACK` → `Reference`
   - `[RENDER-CALC]` / `RENDER-CALC` → `Calculated`

This is a local presentation-boundary fix. `atlas_report_authority.py` was not modified.

The bracketed strings remain only as input keys in the private translation map and fallback simulation; direct renderer output contains none of them.

`TFE CLASSIFICATION` remains unchanged in advisory cards. It is the explicit authority-contract heading, not a machine badge.

---

# Final staged files and SHA256

Production-ready files:

1. `atlas_intraday.py`
   - `438427606559dbd811a6367ac0005e7831299e7384f29ea7b2961c1e1cef075d`
   - unchanged by this remediation
2. `atlas_intraday_advisory.py`
   - `ef9bb985ca686628abb9aa601f5308d8047b0e425ff39e86fb27a23cb6329d9c`
   - unchanged by this remediation
3. `atlas_report_blocks.py`
   - `c19c84ab13f823838d7c4e1993685675a05a7d13db8a65ae04df9627c7c3564e`
   - changed by this remediation

Regression artifacts:

- `tests/direct_shared_blocks_regression.py`
  - `546e9b37e2464b04f930187ef6f1f8aba338eca6b596b6fe225186fb8d871b27`
- `tests/module_origin_full.py`
  - `3ded381a4f17e763c73f3b6d934307aff0e68220e62145b7648c1767778b76b6`
- `tests/test_advisory.py`
  - `72acfd9f0a9642c058b10bac0fe8c94794ba633dbb7f1b679cb220201f8c2b3f`
- `tests/test_atlas_intraday_integration.py`
  - `a64cefa181f8c9968adb73fd5c05400940a7743ee6c71ff7e40824fe8bfd576b`
- immutable fixture
  - `e3b356001de2e86f4e6e7f2eebcd4a4fd0dae273df73ef7663c8907464368b6d`

---

# Module-origin proof

Full staged origin probe loaded:

- `atlas_intraday` → `/private/tmp/p0_intraday_advisory_authority_v1/atlas_intraday.py`
- `atlas_intraday_advisory` → `/private/tmp/p0_intraday_advisory_authority_v1/atlas_intraday_advisory.py`
- `atlas_report_blocks` → `/private/tmp/p0_intraday_advisory_authority_v1/atlas_report_blocks.py`

Result: **PASS** — staged modules loaded, not production copies.

Evidence:

`/tmp/p0_intraday_advisory_authority_v1/output/module_origin_full.json`

---

# Direct shared-block regression

The changed shared report module was imported from staging while using the real production dependency environment.

Direct calls exercised:

1. `holding_block()`
2. `pullback_block()`
3. `watch_list_block()`
4. `portfolio_footer()`

Every output was independently checked for:

- `[PROVIDER]`
- `[DB]`
- `[TFE]`
- `[RENDER-CALC]`

Result: **PASS — zero forbidden badges**.

Observed natural output included:

- `Entry Recorded`
- `Now Market data`
- `Stop Recorded/TFE`
- `Target Recorded/TFE`
- `Calculated gain/loss`
- `Current Value Calculated`

No later whole-report cleanup was used for this proof.

Evidence:

`/tmp/p0_intraday_advisory_authority_v1/output/direct_shared_blocks_regression.json`

---

# Full suite result

All staged Python files compiled successfully.

Full existing suite:

```text
Ran 11 tests
OK
```

Result: **11/11 PASS**.

Verified behavior:

- WDFC → `TECHNICALLY QUALIFIED — WAIT`
- WDFC raw TFE → `BUY Small`, `3/4`
- WDFC blockers include RSI 81, weak momentum, failed Relative Strength, and material earnings-gap reversal
- ELV RVOL 0.17 excludes TOP PICKS
- KO RVOL 0.36 excludes TOP PICKS
- clean BUY remains actionable
- AVOID never promotes
- one consistent regime statement
- no Perme packet jargon
- earnings wording matches sourced evidence
- WATCHING cap/count/omitted names are correct
- no invented support/VWAP/entry/breakout/recheck levels in incident WAIT cards
- zero Telegram sends

---

# Exact previously failing test

Previously failing test:

`test_no_machine_labels_and_momentum_does_not_claim_no_earnings`

Exact isolated rerun under the production-dependency/copy-DB environment:

```text
Ran 1 test
OK
```

Result: **PASS**.

Evidence:

`/tmp/p0_intraday_advisory_authority_v1/output/exact_previous_failure_rerun.txt`

---

# Production-path copied-DB/no-send proof

Copied DB:

`/tmp/p0_intraday_advisory_authority_v1/production_path_smoke.db`

Before smoke:

- production DB SHA: `50dc47662a6798159ed203645d5ab5a17984d6f4c0109f9bb3f80c9f3b3f2316`
- copied DB SHA: same
- integrity: `ok`
- FK violations: `0`

The exact production-path smoke used:

- staging modules first on `PYTHONPATH`;
- real production dependency directory second;
- `ATLAS_DB` and `ATLAS_STAGING_DB` pointed only to the copied DB;
- integration Telegram sender stub with send count asserted zero.

Result:

- **11/11 PASS**
- copied DB SHA unchanged
- production DB SHA unchanged
- production full table counts unchanged
- copied DB unchanged
- zero Telegram sends
- zero production DB writes

Evidence:

- `/tmp/p0_intraday_advisory_authority_v1/output/production_path_11_tests.txt`
- `/tmp/p0_intraday_advisory_authority_v1/output/production_smoke_before.json`
- `/tmp/p0_intraday_advisory_authority_v1/output/production_smoke_after.json`

---

# Production invariants

Production source remains rolled-back/predeployment state:

- `atlas_intraday.py`
  - `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_report_blocks.py`
  - `b2d3bb37644bcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`
- `atlas_intraday_advisory.py`
  - **ABSENT**

Production DB remains:

- SHA: `50dc47662a6798159ed203645d5ab5a17984d6f4c0109f9bb3f80c9f3b3f2316`
- integrity: `ok`
- FK violations: `0`
- trades: `105`
- cash_ledger: `25`
- signals: `35885`
- pending_pullbacks: `54`
- handoff: `16`
- position_lots: `68`
- portfolio_event_journal: `92`
- report_snapshots: `118`

All production source and DB values matched the remediation baseline after testing.

---

# Strategy invariants

- no strategy change
- no Fat Engine scoring/pillar change
- no BUY/AVOID classification change
- no Too Hot change
- no stop/target/sizing change
- no broker/cash/trade-status change
- no production DB write
- no Telegram test/send
- no restart
- no protected strategy-file change
- no global authority-helper change

---

## Final

**STATUS = PASS**  
**production touched = NO**  
**deployment_ready = YES**

The previous production-path failure is fixed at the shared renderer boundary, independently proven without whole-report cleanup, and the complete copied-DB/no-send suite passes 11/11. Stop condition observed: no deployment performed.
