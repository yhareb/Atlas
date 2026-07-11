# Position Management Evidence Bake v1 — Production Release Package

## Final status

- **STATUS = BLOCKED**
- **production touched = NO**
- Release staging path: `/tmp/p0_position_management_evidence_bake_release_v1/`
- `evidence_bake_release_ready = NO`
- Mechanical validation: **PASS**
- Deployment blocker: the dedicated launchd-safe Keychain item is absent.

Required credential prerequisite:

- Keychain service: `com.atlas.position-evidence.massive`
- Account: `yasser`
- Current state: `MISSING` (`security` exit 44)

There is deliberately no fallback to the mixed Atlas environment file, Telegram-related configuration, Yahoo, or an embedded secret. The schedule must not be installed/loaded until the dedicated credential is provisioned and verified from launchd context.

## Exact production target paths

- `/Users/yasser/scripts/atlas_position_evidence_acquire.py`
- `/Users/yasser/scripts/atlas_position_evidence_bake.py`
- `/Users/yasser/scripts/atlas_position_evidence_launchd.py`
- `/Users/yasser/scripts/atlas_position_evidence_orchestrator.py`
- `/Users/yasser/scripts/atlas_position_evidence_health.py`
- `/Users/yasser/Library/LaunchAgents/com.atlas.position_evidence_bake.plist`
- Dedicated data root: `/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/`
- Logs: `/Users/yasser/Library/Logs/Atlas/position_evidence_bake.{out,err}.log`

Nothing at these targets was created or changed during staging.

## Files and SHA256

- Acquisition runner: `2be80e09d003ae951768ad36e2ef71db323b35d592af52d889cbb882d64a77f1`
- Evidence-bake runner: `abd000eb298fe97c25263b2c417292500d6879adc790606f1547702439cd4b1f`
- Health verifier: `a3764540e147a7b61e0e02e956556dc6da4857c8cd5a0859565bdf086864f465`
- Launch helper: `7b7baabe54173b8cda17937ca83ee5844c8561ec288a6c2df581a456b19e2215`
- Orchestrator: `7a94742eca0c0e8a78f0feefae51964890d8cc6e3adc16337d19d6d99677f4ae`
- launchd plist: `4a46669ca4ad8cd2d067db87e4b6bd4602f5405e5d3495645a65f72c0753e2fa`
- Test source: `c91b8cd445f954e7ba2501b66131b6bf6c881ad305fd60abc1aaa3267f64780e`
- Current artifact manifest file: `f436107847d964ca4bca6731a5b86b3dfb3d0387940a10651aa552b12663cbbb`

## Acquisition and evidence design

The acquisition runner:

- Opens `atlas.db` with SQLite `mode=ro` and `query_only=ON`.
- Records production DB SHA before and after acquisition and requires equality.
- Uses authenticated Massive adjusted daily aggregates with bounded 8-second calls.
- Requires final-session bars for every current OPEN position.
- Writes one immutable, content-addressed, atomic snapshot.
- Stores no credentials.

Six buckets remain structurally separate:

1. Broker-confirmed completed trades.
2. Anomalous/disputed trades.
3. FILLED pullbacks.
4. Signal-only non-fills.
5. Current OPEN positions.
6. Shadow policy observations.

The signal-only query is bounded to the current session, BUY-family, score ≥2/4, latest ticker/day, maximum 250, and explicitly labels every row `is_fill=false` and `evidence_class=signal_only`.

The append-only shadow SQLite records full market/provenance/completeness/conflict data, candidate arrays, formulas, parameters, rejection reasons, calculation version, and digests. UPDATE/DELETE triggers protect evidence and observations; high-water cannot regress; stale streams preserve prior verified state; repeated snapshots are idempotent and restart-safe.

## Catalyst A/B behavior

Each evidence event receives both unselected shadow variants:

- **A:** verified price/ATR/structure stop candidates remain observable; target advice is `INCOMPLETE_BLOCKED`.
- **B:** both stop and target candidates are blocked.

Both carry candidate arrays and `selection=null`; recommendation/new authoritative level remain null; action authority is false. No policy is chosen or promoted.

## Schedule and timing rationale

Staged label: `com.atlas.position_evidence_bake`

- Current host timezone: `+04`.
- Current New York timezone: EDT (`−04`).
- Existing EOD positions: host Tue–Sat `00:05` = prior Mon–Fri `16:05 ET`.
- Existing macro post-market: host `00:15` = prior day `16:15 ET`.
- Audit jobs fire at `:00` and `:30`.
- Proposed evidence bake: host Tue–Sat `00:45` = prior Mon–Fri `16:45 ET` under the current EDT mapping.

This leaves 30 minutes after macro post-market, 40 minutes after EOD positions, and avoids the `:30` audit and host `06:00` backup. An internal NYSE-session and `>=16:40 ET` gate prevents premature/non-session execution.

**DST caveat:** launchd uses static host-local wall time. Seasonal host/ET mapping must be reviewed before DST changes; the ET gate prevents premature execution but cannot reschedule a trigger that becomes too late/early.

## Overlap, locking, timeout, and health gates

- Nonblocking exclusive lock prevents self-overlap.
- Busy launch labels: intraday, EOD positions, macro post-market, and backup.
- Busy process gates include `atlas_manage.py` and `market_scout`.
- Acquisition timeout: 180 seconds; bake timeout: 60 seconds; provider timeout: 8 seconds.
- NYSE holiday/weekend gate exits cleanly; observed Independence Day behavior is tested.
- Health verifier is stdout-only and checks recency, quick/integrity checks, FK violations, six nonempty buckets, A/B parity, and source-DB before/after SHA equality.

## Shadow storage, retention, and backups

- Owner/group: `yasser:staff`.
- Data directories: mode `0700`.
- Executable scripts: `0750`; plist: `0644`; shadow DB: `0600`; backups: `0400`.
- Immutable snapshot retention: 400 days.
- Shadow backup retention: 90 days.
- After each successful bake, the orchestrator uses SQLite’s online backup API and validates the backup before retention cleanup.
- Backup location is dedicated and separate from canonical Atlas data; no secrets are stored.

## Staging tests and safety evidence

- `py_compile`: PASS.
- `plutil -lint`: PASS.
- Tests: **9/9 PASS**.
- Covered: copied-profile launchd-equivalent execution, Massive acquisition, immutable snapshots, six buckets, candidate fields, catalyst A/B, idempotency/restart, high-water/stale state, append-only enforcement, lock/timeout/busy gates, NYSE holiday, retention/backup, health/integrity/FK, fake Keychain isolation, and no schedule load.
- Final probe bucket counts: broker-confirmed `8`, anomalous `2`, FILLED pullbacks `22`, signal-only `12`, OPEN `5`, shadow-policy source rows `4`.
- Provider errors: zero.
- Telegram sends: zero.
- Broker actions: zero.
- TFE/strategy mutations: zero.
- Production DB writes: zero.
- Production DB SHA remains `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`; integrity `ok`; FK violations `0`.
- Staged launch label loaded count: `0`.
- Production target Git status: clean.

## Rollback plan

If a later installation is separately approved:

1. Unload only `com.atlas.position_evidence_bake`.
2. Remove only the manifest-listed plist and five additive scripts.
3. Archive/remove only the dedicated evidence-bake data/log directories.
4. Optionally remove only the dedicated Keychain service item.
5. Verify canonical Atlas DB/source/config/schedule SHAs remain unchanged.

Because the package is additive and never feeds live reports, agents, TFE, or trading state, rollback requires no Atlas DB migration or trading-state repair.

## Blocker closure required before deployment approval

Provision the dedicated Keychain item by a separately authorized secret operation, then verify:

- Keychain lookup succeeds for the launch user without exposing the value.
- Env-clean launch helper reaches Massive and passes no Telegram or unrelated environment values.
- Full copied-DB launchd-equivalent suite still passes.
- Artifact SHAs and production invariants are re-established.

Until then:

`evidence_bake_release_ready = NO`
