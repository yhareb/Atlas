# Intraday Advisory Authority v1 — canonical-routing production deployment

## Current status

**STATUS = PASS (deployment and smoke); LIVE VERIFICATION PENDING**  
**production touched = YES**  
**intraday_advisory_authority_complete = NO — pending first post-deploy market-hours report**

The approved three-file unit is deployed and remains active. Atomic deployment, compile, exact SHA checks, direct badge regression, snapshot-120 replay, module-origin proof, complete 16/16 production-path copied-DB/no-Telegram suite, and deployment/smoke DB invariance all passed.

Deployment occurred after the regular session had ended. Subsequent scheduled ticks self-skipped outside market hours, so no real post-deploy report exists yet. A one-shot read-only verifier is scheduled for Monday, 2026-07-13 at 13:50 UTC (09:50 ET), after the first expected real cycle. It will not deploy, patch, restart, run a manual scan, modify DB, or send Telegram tests.

---

# Deployed files

1. `/Users/yasser/scripts/atlas_intraday.py`
   - `8094a472b8f60faf7d2e791bfa4cb65056cb3b430f20de227e030adece428fee`
2. `/Users/yasser/scripts/atlas_intraday_advisory.py`
   - `25715b07f17df58b509304cb88ff1cea3712f5aa5fdeb941515e6917cc7125d7`
3. `/Users/yasser/scripts/atlas_report_blocks.py`
   - `c19c84ab13f823838d7c4e1993685675a05a7d13db8a65ae04df9627c7c3564e`

Compile: **PASS**.

No restart occurred.

---

# Gate and backups

Final gate:

- no intraday/manage/scout process
- no relevant lock
- relevant launchd jobs loaded but not running
- 495 seconds before next tick
- no process killed

Backups:

1. `/Users/yasser/scripts/archive/20260710T201145Z_intraday_advisory_authority_v1_canonical_atlas_intraday.py.bak`
   - `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
2. `/Users/yasser/scripts/archive/20260710T201145Z_intraday_advisory_authority_v1_canonical_atlas_report_blocks.py.bak`
   - `b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`

The helper was absent before deployment; rollback removes it.

Rollback readiness: **YES**.

---

# Deployment-boundary DB proof

Before and immediately after deployment:

- SHA: `c64b0ebecd916acf893df34a75f03bdc6d381ef190ba4d703ed21174940a8654`
- integrity: `ok`
- FK violations: `0`
- signal high-water: `36112`
- every table count unchanged

Stable counts:

- trades `105`
- cash_ledger `25`
- pending_pullbacks `54`
- handoff `16`
- position_lots `68`
- portfolio_event_journal `92`
- report_snapshots `121`
- signals `36094`

---

# Production-path verification

Copied DB:

`/tmp/p0_intraday_advisory_authority_v1/canonical_deployed_smoke/atlas_smoke.db`

Results:

- complete suite: **16/16 PASS**
- snapshot-120 replay: **PASS**
- direct shared-block badge regression: **PASS**
- deployed module origins: **PASS**
- canonical routing equation: **PASS**
- mutually exclusive destinations: **PASS**
- explicit exclusion reasons: **PASS**
- no silent BUY-family drops: **PASS**
- zero Telegram sends: **PASS**
- copied DB unchanged: **PASS**
- production DB unchanged during smoke: **PASS**

Deployed module origins:

- `/Users/yasser/scripts/atlas_intraday.py`
- `/Users/yasser/scripts/atlas_intraday_advisory.py`
- `/Users/yasser/scripts/atlas_report_blocks.py`

Snapshot-120 replay:

- ELV → qualified WAIT
- KO → qualified WAIT
- WDFC WATCH → WATCHING
- equation holds

Evidence:

- `output/canonical_deployed_16_tests.txt`
- `output/canonical_deployed_badges.json`
- `output/canonical_deployed_origins.json`
- `output/canonical_deployed_smoke_before.json`
- `output/canonical_deployed_smoke_after.json`
- `output/snapshot_120_replay.json`

---

# Live verification state

At 16:00 ET and later, the scheduled job logged outside-market-hours skips. No post-deploy report snapshot was generated.

Observed:

- launchd loaded, not running
- runs `1614`
- last exit code `0`
- report high-water remains `121`

Therefore current live destinations for WDFC, ELV, and KO are **N/A until the next real cycle**. No fixed historical classification is assumed.

One-shot verifier:

- job ID `101811b36ada`
- scheduled Monday 2026-07-13 13:50 UTC / 09:50 ET
- delivery to this conversation
- read-only only

It will verify:

- dynamic current classification placement
- rendered routing equation
- mutual exclusivity and explicit exclusions
- WDFC/ELV/KO current destinations and raw signal/score/RVOL
- badge/packet hygiene
- one regime label
- earnings wording
- WATCHING cap
- no invented levels
- stable trade/account/cash/ledger invariants
- integrity and FK status

---

# Current production integrity

After outside-hours skipped ticks:

- deployed source SHAs remain exact
- integrity `ok`
- FK violations `0`
- trades `105`
- cash_ledger `25`
- pending_pullbacks `54`
- handoff `16`
- position_lots `68`
- portfolio_event_journal `92`

Signals increased from scheduled activity; skipped ticks produced no live report acceptance evidence.

No reconciliation, Position Management, or idle-session rollover was deployed.

---

## Return

**STATUS = PASS (deployment/smoke), LIVE PENDING**  
**production touched = YES**  
**intraday_advisory_authority_complete = NO — pending scheduled read-only live verification**
 Transient DB SHA/count growth outside the deployment/smoke window is normal scheduled activity and not attributed to file deployment.