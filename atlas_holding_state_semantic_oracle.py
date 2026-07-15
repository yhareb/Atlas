"""Exact cross-consumer semantic comparison."""
from __future__ import annotations
AXES=('observed_market_risk_state','advisory_action','broker_ledger_lifecycle')
def signature(projection):
 p=projection.structured['packet'];r=projection.structured['receipt']
 return {'ticker':p.get('ticker'),'packet_id':p.get('packet_id'),'packet_digest':p.get('packet_digest'),'axes':{k:(p.get('axes') or {}).get(k) for k in AXES},'canonical_levels':p.get('canonical_levels'),'price_roles':p.get('price_roles'),'usability':r.get('usability'),'reason_codes':r.get('reason_codes'),'retention':p.get('retention')}
def compare(projections):
 values=[signature(x) for x in projections];return {'status':'PASS' if values and all(x==values[0] for x in values) else 'FAIL','signatures':values}

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from typing import Any
ORACLE = {'PENG_contradiction': {'observed_state': 'STOP_BREACHED_REGULAR', 'advisory_action': 'SELL NOW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'LASR_stronger_action_preservation': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'EXIT REVIEW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'BAC_near_stop_trim_review': {'observed_state': 'NEAR_STOP', 'advisory_action': 'TRIM REVIEW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'fresh_regular_stop_breach': {'observed_state': 'STOP_BREACHED_REGULAR', 'advisory_action': 'SELL NOW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'pre_market_stop_breach': {'observed_state': 'STOP_BREACHED_PRE_MARKET', 'advisory_action': 'EXIT REVIEW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'stale_superseded_stop_event': {'observed_state': 'PRICE_UNAVAILABLE', 'advisory_action': 'HOLD', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'broker_submitted_not_filled': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'HOLD', 'broker_lifecycle': 'BROKER_SELL_SUBMITTED'}, 'broker_filled_db_open': {'observed_state': 'LIFECYCLE_CONTRADICTION', 'advisory_action': 'DATA INCOMPLETE', 'broker_lifecycle': 'BROKER_SELL_FILLED'}, 'missing_daily_packet': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'DATA INCOMPLETE', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'stale_profit_protection_packet': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'TRIM REVIEW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'conflicting_quotes': {'observed_state': 'INVALID_OR_STALE_EVENT', 'advisory_action': 'HOLD', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'broker_filled_db_closed': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'HOLD', 'broker_lifecycle': 'BROKER_SELL_FILLED'}, 'missing_daily_fresh_pp_hold': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'DATA INCOMPLETE', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'missing_daily_retained_exit_review': {'observed_state': 'ABOVE_STOP', 'advisory_action': 'EXIT REVIEW', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'persisted_stop_null_event_id': {'observed_state': 'INVALID_OR_STALE_EVENT', 'advisory_action': 'HOLD', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'persisted_stop_wrong_trade': {'observed_state': 'INVALID_OR_STALE_EVENT', 'advisory_action': 'HOLD', 'broker_lifecycle': 'NO_BROKER_EVENT'}, 'persisted_stop_valid': {'observed_state': 'STOP_BREACHED_REGULAR', 'advisory_action': 'SELL NOW', 'broker_lifecycle': 'NO_BROKER_EVENT'}}

def projection(packet: dict[str, Any]) -> dict[str, Any]:
    axes = packet.get('axes') or {}
    return {'observed_state': (axes.get('observed_market_risk_state') or {}).get('state'), 'advisory_action': (axes.get('advisory_action') or {}).get('action'), 'broker_lifecycle': (axes.get('broker_ledger_lifecycle') or {}).get('state')}

def validate_against_oracle(name: str, packet: dict[str, Any]) -> dict[str, Any]:
    expected = ORACLE[name]
    actual = projection(packet)
    diffs = {k: {'expected': expected[k], 'actual': actual.get(k)} for k in expected if actual.get(k) != expected[k]}
    checks = {}
    qs = packet.get('quote_selection') or {}
    stop = qs.get('selected_stop_evaluation_price') or {}
    comps = packet.get('components') or {}
    stop_life = comps.get('stop_lifecycle') or {}
    retention = packet.get('retention') or {}
    valuation = qs.get('selected_valuation_price') or {}
    if stop.get('source') == 'PERSISTED_STOP_EVENT':
        required = ['event_id', 'trade_id', 'ticker', 'event_timestamp', 'event_price', 'event_stop', 'validity_state', 'supersession_proof', 'source_digest']
        missing = [k for k in required if not stop.get(k)]
        life_missing = [k for k in required if not stop_life.get(k)]
        checks['persisted_event_identity_complete'] = {'pass': not missing and (not life_missing), 'missing_stop_price_fields': missing, 'missing_lifecycle_fields': life_missing}
        checks['persisted_event_trade_binding'] = {'pass': str(stop.get('trade_id')) == str((packet.get('trade_identity') or {}).get('trade_id')) and str(stop.get('ticker')).upper() == str(packet.get('ticker')).upper(), 'stop_trade_id': stop.get('trade_id'), 'packet_trade_id': (packet.get('trade_identity') or {}).get('trade_id')}
        checks['event_only_valuation_excluded'] = {'pass': valuation.get('price') is None, 'valuation': valuation}
    if retention.get('last_valid_stronger_action'):
        required = ['retention_policy', 'retained_since', 'retention_expires_at', 'original_reason_codes', 'required_clearing_evidence', 'expiry_behavior']
        missing = [k for k in required if not retention.get(k)]
        checks['retention_metadata_complete'] = {'pass': not missing and retention.get('retention_policy') != 'EXTERNAL_POLICY' and bool(retention.get('required_clearing_evidence')), 'missing': missing, 'retention': retention}
    if name == 'broker_filled_db_open':
        checks['valuation_reconciliation_blocked'] = {'pass': valuation.get('price') is None and valuation.get('source') == 'RECONCILIATION_BLOCKED', 'valuation': valuation}
    for k, v in checks.items():
        if not v.get('pass'):
            diffs[k] = v
    return {'scenario': name, 'pass': not diffs, 'expected': expected, 'actual': actual, 'checks': checks, 'diffs': diffs}
