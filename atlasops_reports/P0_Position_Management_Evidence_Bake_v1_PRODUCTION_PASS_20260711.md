# Position Management Evidence Bake v1 — Production Deployment Evidence

## Verdict

- **STATUS = PASS**
- **production touched = YES** — only the five approved new evidence scripts, one new LaunchAgent plist, dedicated evidence data root, and dedicated logs were installed/created.
- `evidence_bake_production_complete = YES`
- `policy_authority = NO`

## Predeploy gates

All nine approved staging SHA256 values matched exactly, including README, manifest, plist, five scripts, and test suite.

Predeploy anchors:

- Canonical Atlas DB SHA256: `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`
- Atlas DB integrity: `ok`
- Atlas DB FK violations: `0`
- Unrelated Atlas source anchor: `f4e10b4f14a13e23b05fef4f7e50dd031a612eb60b4866141dc43381a6452147`
- Atlas profile `.env` SHA256: `031b3fa65f01d16f3f8fbdd2ca7f1ee2711f25e192068ba39ba757752e3505bd`
- Unrelated LaunchAgents anchor: `396d267bde234872fb4e3a176cbf5f77c3c8126c830ff97d8187c7c1a0d99b9b`
- Evidence-bake loaded count: `0`
- All six production file targets: `ABSENT`
- Dedicated data root and logs: `ABSENT`
- Evidence-bake lock: `ABSENT`
- Active Atlas writer processes: none
- Existing EOD, intraday, macro-postmarket, and backup LaunchAgents all had PID `-` (not running)

No process was killed or existing job altered.

## Backups / preimages

All approved targets were new and absent, so there was no file preimage to back up. A timestamped absent-preimage and anchor manifest was created:

`/Users/yasser/scripts/archive/position_evidence_bake_20260710T231423Z_predeploy/preimage_manifest.txt`

It records all targets as absent plus the immediate DB and profile-env anchors. Rollback therefore removes the newly installed manifest-listed unit; no restoration copy is required.

## Deployed paths, SHA256 and permissions

- `/Users/yasser/scripts/atlas_position_evidence_acquire.py` — `2be80e09d003ae951768ad36e2ef71db323b35d592af52d889cbb882d64a77f1` — `0750`
- `/Users/yasser/scripts/atlas_position_evidence_bake.py` — `abd000eb298fe97c25263b2c417292500d6879adc790606f1547702439cd4b1f` — `0750`
- `/Users/yasser/scripts/atlas_position_evidence_health.py` — `a3764540e147a7b61e0e02e956556dc6da4857c8cd5a0859565bdf086864f465` — `0750`
- `/Users/yasser/scripts/atlas_position_evidence_launchd.py` — `b1d74df46ebb7790544b03f6ed2bd81b769ed107c5d0aac203581b4217f70547` — `0750`
- `/Users/yasser/scripts/atlas_position_evidence_orchestrator.py` — `7a94742eca0c0e8a78f0feefae51964890d8cc6e3adc16337d19d6d99677f4ae` — `0750`
- `/Users/yasser/Library/LaunchAgents/com.atlas.position_evidence_bake.plist` — `4a46669ca4ad8cd2d067db87e4b6bd4602f5405e5d3495645a65f72c0753e2fa` — `0644`

Dedicated data root and all subdirectories are owned by `yasser:staff` with mode `0700`. Shadow SQLite is `0600`.

Only per-file bytecode caches for the five newly deployed modules were cleared in both local `__pycache__` and macOS system cache locations. All five deployed scripts passed `py_compile`.

## Preload production smoke

The deployed launch helper was executed manually under `env -i` before scheduler activation.

- Orchestrator: `COMPLETE`
- Massive authenticated acquisition: `ACQUIRED / PASS`
- Provider errors: `0`
- Canonical DB access: read-only URI plus `query_only`
- Canonical DB unchanged during acquisition: `true`
- Immutable snapshot created mode `0440`
- Evidence bake: `BAKED / PASS`
- Six bucket counts: anomalous/disputed `2`, broker-confirmed completed `8`, current open `5`, filled pullbacks `22`, shadow policy observations `4`, signal-only non-fills `12`
- Shadow evidence rows: `53`
- Catalyst A observations: `53`
- Catalyst B observations: `53`
- Shadow integrity: `ok`
- Shadow FK violations: `0`
- Shadow SQLite mode: `0600`
- Smoke stderr bytes: `0`

## Idempotency and health

The exact immutable snapshot was baked twice more:

- Rerun 1: `IDEMPOTENT`
- Rerun 2: `IDEMPOTENT`
- Shadow DB SHA before/after both reruns: `f40d8075d405bc89f73e21745c82dca8cb1597a14b26ce3e887d6b899a611987`
- Byte-identical across both reruns: `true`
- Health verifier: `ok=true`
- Health quick/integrity: `ok / ok`
- Health FK violations: `0`
- Health source-write proof: unchanged `true`

## Child environment inventory

Observed variable names only:

- `ATLAS_POSITION_EVIDENCE_ORCHESTRATOR`
- `HOME`
- `PATH`
- `MASSIVE_API_KEY`
- `LC_CTYPE` (platform-added)
- `__CF_USER_TEXT_ENCODING` (platform-added)

Forbidden names reaching child: `0`. Unexpected names: `0`. No Telegram, OpenAI, Benzinga, EODHD, broker, or unrelated variable reached the child.

## Secret and side-effect checks

- Secret-value hits in dedicated data/log files: `0`
- Secret-value hits in process argv: `0`
- Secret leak scan: `PASS`
- Telegram send references in deployed unit: `0`
- Broker action references: `0`
- Strategy/protected-module references: `0`
- Telegram sends: `0`
- Broker actions: `0`
- TFE/strategy mutation: `0`

No Telegram credential/config value was read or referenced.

## Schedule activation

Only `com.atlas.position_evidence_bake` was bootstrapped.

- Loaded count: `1`
- Plist path: `/Users/yasser/Library/LaunchAgents/com.atlas.position_evidence_bake.plist`
- Program: `/usr/bin/python3 /Users/yasser/scripts/atlas_position_evidence_launchd.py`
- Effective schedule: host-local Tue–Sat at `00:45`
- `RunAtLoad=false`
- Internal gates: NYSE session, at/after 16:40 ET, final-data requirement, busy-process/label gate, nonblocking self-lock, acquisition/bake timeouts
- Post-load state: `not running`
- Runs: `0`
- Last exit: `never exited`
- Immediate duplicate execution: none
- Crash loop: none
- Process count: `0`

Log files were not created immediately because `RunAtLoad=false` and the job had not run. Therefore no launchd log content or credential could exist at activation time.

## Postdeploy invariants

Postdeploy values equal predeploy values:

- Canonical Atlas DB SHA256: `858e303f43ab5b10efe10313c491c2591db01fbbf44096567a7b37e37a3460f9`
- Integrity: `ok`
- FK violations: `0`
- Unrelated Atlas source anchor: `f4e10b4f14a13e23b05fef4f7e50dd031a612eb60b4866141dc43381a6452147`
- Atlas profile `.env` SHA256: `031b3fa65f01d16f3f8fbdd2ca7f1ee2711f25e192068ba39ba757752e3505bd`
- Unrelated LaunchAgents anchor: `396d267bde234872fb4e3a176cbf5f77c3c8126c830ff97d8187c7c1a0d99b9b`
- Trades count: `105`
- Cash-ledger count: `25`
- Open trades: `5`
- Open status/stop/target/quantity/entry/broker digest: `c8a792d1ab9cc948ebebab9f562fd7a4618ffb0fe4a0392d7338d4bf8bc9087c`
- Cash digest: `8ce6a0b63108d29466e8a30154534b57f15fac7c1edfc17978eb52b960bce1e4`
- Schedule loaded count: `1`

## Policy boundary and rollback

The deployed system collects append-only shadow evidence only. It has no policy selection, threshold promotion, reporting influence, BUY/AVOID influence, exit authority, recommendation send path, broker path, or canonical stop/target/status/cash mutation path.

Rollback is ready: boot out only `com.atlas.position_evidence_bake`; remove only the six manifest-listed files and dedicated evidence-bake data/log paths; verify loaded count `0`; then recheck the DB/source/env/unrelated-LaunchAgent anchors above. Since every target was absent predeploy, no production file restore is required.

**evidence_bake_production_complete = YES**  
**policy_authority = NO**
