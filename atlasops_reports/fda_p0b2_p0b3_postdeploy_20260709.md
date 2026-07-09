# FDA P0B2 + P0B3 Selective Wiring — Post-Deploy Verification

Generated: `2026-07-09T21:27:41`

`DEPLOY_STATUS = PASS`

- `phase`: `P0B2+P0B3_DEPLOYED`
- `predeploy_gate`: `PASS`
- `py_compile_exit`: `0`
- `sha_verify_pass`: `True`
- `static_scan_pass`: `True`
- `smoke_status`: `PASS`
- `smoke_endpoint_calls`: `1`
- `smoke_endpoint_call_max_1`: `True`
- `smoke_old_broad_loader_not_called`: `True`
- `smoke_score_signal_action_invariant`: `True`
- `smoke_no_signal_writes`: `True`
- `prod_db_sha_unchanged`: `True`
- `prod_counts_unchanged`: `True`
- `rollback_ready`: `True`

## Files deployed

- `/Users/yasser/scripts/atlas_fda_calendar.py` — `1621c6fd0a99a78e1bb295c8dc41b4ce74d24bd21a96c114e1fe4c6c89cffb50`
- `/Users/yasser/scripts/market_scout.py` — `2dfaf7f9969a05020a0a1d63ae8410a866a7ea47b1f580182bf1323259b500f0`
- `/Users/yasser/scripts/atlas_manage.py` — `d7df29af75fa3ae073556cde2c531406e07910a61206f92b85c31d590d7f7ca7`
- `/Users/yasser/scripts/atlas_engine.py` — `a3908a609b37533e6daa106ade23f3a886c1ad628cb6c847ea4c5bc6448a071a`

## Backup archive

`/Users/yasser/scripts/archive/20260709T172741Z_fda_p0b2_p0b3_predeploy`

- `/Users/yasser/scripts/atlas_fda_calendar.py` -> `ABSENT_BEFORE_DEPLOY`
- `/Users/yasser/scripts/market_scout.py` -> `/Users/yasser/scripts/archive/20260709T172741Z_fda_p0b2_p0b3_predeploy/market_scout.py.bak`
- `/Users/yasser/scripts/atlas_manage.py` -> `/Users/yasser/scripts/archive/20260709T172741Z_fda_p0b2_p0b3_predeploy/atlas_manage.py.bak`
- `/Users/yasser/scripts/atlas_engine.py` -> `/Users/yasser/scripts/archive/20260709T172741Z_fda_p0b2_p0b3_predeploy/atlas_engine.py.bak`

## Smoke summary

- `FATE`: `{'status': 'ok', 'fda_check_decision': 'ALLOW', 'fda_event_count': 1, 'fda_relevance_reason': 'FDA_CHECK_ALLOWED_CALENDAR_MATCH', 'fda_source_endpoint': 'benzinga_direct_fda_calendar_v2_1'}`
- `CRSP`: `{'status': 'eligible_no_event', 'fda_check_decision': 'ALLOW', 'fda_event_count': 0, 'fda_relevance_reason': 'FDA_CHECK_ALLOWED_HEALTHCARE_CLASSIFICATION', 'fda_source_endpoint': None}`
- `BAC`: `{'status': 'skipped', 'fda_check_decision': 'BLOCK', 'fda_event_count': 0, 'fda_relevance_reason': 'FDA_CHECK_BLOCKED_NON_FDA_SECTOR', 'fda_source_endpoint': None}`
- `NVDA`: `{'status': 'skipped', 'fda_check_decision': 'BLOCK', 'fda_event_count': 0, 'fda_relevance_reason': 'FDA_CHECK_BLOCKED_NON_FDA_SECTOR', 'fda_source_endpoint': None}`
- `MSFT`: `{'status': 'skipped', 'fda_check_decision': 'BLOCK', 'fda_event_count': 0, 'fda_relevance_reason': 'FDA_CHECK_BLOCKED_NON_FDA_SECTOR', 'fda_source_endpoint': None}`
- `SPY`: `{'status': 'skipped', 'fda_check_decision': 'BLOCK', 'fda_event_count': 0, 'fda_relevance_reason': 'FDA_CHECK_BLOCKED_ETF_OR_PROXY', 'fda_source_endpoint': None}`
- `JPM`: `{'status': 'ok', 'fda_check_decision': 'ALLOW', 'fda_event_count': 1, 'fda_relevance_reason': 'FDA_CHECK_ALLOWED_CALENDAR_MATCH', 'fda_source_endpoint': 'benzinga_direct_fda_calendar_v2_1'}`

## Remaining P0B4 report-side cleanup gap

Report-side cleanup remains: pre_market_report.py still uses older protected FDA loader path; a future P0B4 should switch report-only FDA warning rendering to atlas_fda_calendar without scoring changes.

## JSON evidence

`/tmp/fda_p0b2_p0b3_deploy/output/post_deploy_verification.json`

