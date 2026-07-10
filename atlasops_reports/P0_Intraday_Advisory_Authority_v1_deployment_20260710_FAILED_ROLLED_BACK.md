# Intraday Advisory Authority v1 — production deployment attempt

## Final status

**STATUS = FAIL**  
**production touched = YES — temporarily deployed, then fully rolled back**  
**intraday_advisory_authority_complete = NO**

The approved three-file unit passed preflight, idle/tick gating, backup, atomic copy, compile, deployed-SHA verification, and immediate DB invariance. The required production-path copied-DB/no-Telegram smoke then failed **1 of 11 tests**. Per the work order, the entire unit was restored in a later verified idle window. Production is now back at its exact predeployment source SHAs; the new helper is absent.

No position-ledger reconciliation or Position Management work was started.

---

# Predeploy gate

Final gate immediately before copy:

- `atlas_intraday.py`: no active process
- `atlas_manage.py`: no active process
- `market_scout.py`: no active process
- intraday/manage/scout locks: none
- relevant Atlas launchd jobs: loaded but not running
- time to next 10-minute tick: `597 seconds`
- gate result: **PASS**

No process was killed and no launchd job was unloaded or restarted.

---

# Staging/manifest verification

Manifest:

`/tmp/p0_intraday_advisory_authority_v1/output/artifact_manifest.json`

Manifest SHA256:

`59e5f206dbd9922944c7bb7379538cd0e7cc81fae7b6e3044350a6d3e9417a06`

All three staged files matched both disk and manifest:

1. `atlas_intraday.py`
   - approved/manifest/disk SHA: `438427606559dbd811a6367ac0005e7831299e7384f29ea7b2961c1e1cef075d`
2. `atlas_report_blocks.py`
   - approved/manifest/disk SHA: `cb9bd50ea46a9d9d4fc99785af0e2fa516e261d0bfe22b2ce40b35f2edcddb65`
3. `atlas_intraday_advisory.py`
   - manifest/disk SHA: `ef9bb985ca686628abb9aa601f5308d8047b0e425ff39e86fb27a23cb6329d9c`

Production preimage:

- `atlas_intraday.py`: `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_report_blocks.py`: `b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`
- `atlas_intraday_advisory.py`: **ABSENT**

Staging-versus-current-production diffs were captured before deployment. No unexpected helper drift existed.

---

# Backups

1. `/Users/yasser/scripts/archive/20260710T192003Z_intraday_advisory_authority_v1_atlas_intraday.py.bak`
   - SHA: `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
2. `/Users/yasser/scripts/archive/20260710T192003Z_intraday_advisory_authority_v1_atlas_report_blocks.py.bak`
   - SHA: `b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`

The helper was absent before deployment, so no helper backup was required.

---

# Temporary deployment result

The unit was copied with sibling temporary files and ordered atomic replacements. Targeted local and macOS bytecode caches were cleared for only:

- `atlas_intraday`
- `atlas_intraday_advisory`
- `atlas_report_blocks`

Production compile result immediately after copy:

**PASS**

Temporary deployed SHAs matched staging exactly:

- `atlas_intraday.py`: `438427606559dbd811a6367ac0005e7831299e7384f29ea7b2961c1e1cef075d`
- `atlas_intraday_advisory.py`: `ef9bb985ca686628abb9aa601f5308d8047b0e425ff39e86fb27a23cb6329d9c`
- `atlas_report_blocks.py`: `cb9bd50ea46a9d9d4fc99785af0e2fa516e261d0bfe22b2ce40b35f2edcddb65`

No daemon or gateway restart occurred.

---

# DB proof at deployment boundary

Immediately before and after deployment:

- DB SHA: `582c7a868fabfd6868735755b5ee036f0e3b2e0421b0ecb1626ebcf0476e4839`
- `PRAGMA integrity_check`: `ok`
- FK violations: `0`
- every table count: unchanged

Key counts at the deployment boundary:

- trades: `105`
- cash_ledger: `25`
- signals: `35815`
- pending_pullbacks: `54`
- handoff: `16`
- position_lots: `68`
- portfolio_event_journal: `92`
- report_snapshots: `117`

---

# Required copied-DB/no-Telegram smoke

Smoke setup:

- production DB copied byte-for-byte to:
  `/tmp/p0_intraday_advisory_authority_v1/production_smoke/atlas_smoke.db`
- production DB SHA before smoke:
  `582c7a868fabfd6868735755b5ee036f0e3b2e0421b0ecb1626ebcf0476e4839`
- copied DB SHA before/after:
  `582c7a868fabfd6868735755b5ee036f0e3b2e0421b0ecb1626ebcf0476e4839`
- Telegram sender stubbed; no send occurred
- integration assertion required actual module path:
  `/Users/yasser/scripts/atlas_intraday.py`

Result:

**10/11 PASS; 1 FAIL**

Passing behavior included:

- WDFC raw `BUY Small`, `3/4` preserved
- WDFC routed to `TECHNICALLY QUALIFIED — WAIT`
- ELV/KO low-RVOL exclusion from TOP PICKS
- clean BUY actionability
- AVOID non-promotion
- regime consistency
- earnings consistency
- watching-cap behavior
- no invented incident levels
- zero Telegram sends
- zero production DB writes

Exact failure:

`test_no_machine_labels_and_momentum_does_not_claim_no_earnings`

Rendered direct WAITING block contained:

`👀 Now [PROVIDER] $1.00 (Calculated +0%)`

Expected: no `[PROVIDER]` badge.

Root cause:

`atlas_report_blocks.py` assigns natural local source constants, but calls production `atlas_report_authority.normalize_price_source()`. That function returns the production implementation badge `[PROVIDER]` for the current-price source. The full intraday renderer’s final naturalization pass can hide this, but the shared report block itself still violates the authority/hygiene contract when invoked directly. The staging-only test did not expose this production import interaction; the production-path smoke did.

Because the work order explicitly required **11/11**, this was a hard failure, not a warning.

---

# Production DB after smoke

Immediately after the failed smoke:

- production DB SHA remained:
  `582c7a868fabfd6868735755b5ee036f0e3b2e0421b0ecb1626ebcf0476e4839`
- copied DB SHA remained identical
- integrity: `ok`
- all counts remained unchanged

Therefore the failed smoke itself caused zero production DB writes.

---

# Live-cycle status

Before rollback could enter a safe write window, the next normal scheduled intraday cycle started. The rollback worker did not kill it and waited for it to finish.

Observed scheduler change:

- launchd runs: `1606 → 1607`
- last exit code: `0`

Normal scheduled activity then increased:

- signals: `35815 → 35885`
- report_snapshots: `117 → 118`

Stable authority/ledger counts remained unchanged:

- trades: `105`
- cash_ledger: `25`
- pending_pullbacks: `54`
- handoff: `16`
- position_lots: `68`
- portfolio_event_journal: `92`

Because the mandatory smoke had already failed, this cycle was **not accepted as deployment completion evidence**. WDFC/ELV/KO live placement and hygiene are therefore reported as **NOT ACCEPTED / incomplete**, regardless of the cycle’s exit code.

No strategy, score, stop, target, cash, broker, or trade-status mutation was attributed to deployment or smoke.

---

# Automatic rollback

The first rollback attempt correctly refused to write because a normal intraday process and lock were active. No process was killed.

A bounded rollback worker waited for a verified idle window, rechecked it twice, then restored the complete unit:

- restored `atlas_intraday.py` from backup
- restored `atlas_report_blocks.py` from backup
- removed newly created `atlas_intraday_advisory.py`
- cleared only targeted local/macOS caches
- compiled restored production files
- verified restored SHAs

Rollback result:

**PASS**

Current production state:

- `atlas_intraday.py`:
  `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_report_blocks.py`:
  `b2d3bb37644bcbcbf846568f6777de27bd72c68af102076a2fdf9434aabb094a`
- `atlas_intraday_advisory.py`: **ABSENT**
- compile: **PASS**
- intraday launchd: loaded, not running, last exit code `0`
- integrity: `ok`
- FK violations: `0`

Rollback evidence:

`/tmp/p0_intraday_advisory_authority_v1/output/rollback_result.json`

The system is rollback-safe and currently restored.

---

# Placement/hygiene return fields

- WDFC production deployment placement: **NOT ACCEPTED — rolled back**
- ELV production deployment placement: **NOT ACCEPTED — rolled back**
- KO production deployment placement: **NOT ACCEPTED — rolled back**
- report hygiene: **FAIL** due direct `[PROVIDER]` badge leakage
- rollback readiness: **YES; rollback completed and verified**
- `intraday_advisory_authority_complete = NO`

A new staging remediation and separate deployment approval are required. This work order stopped after rollback; no reconciliation or Position Management work began.
