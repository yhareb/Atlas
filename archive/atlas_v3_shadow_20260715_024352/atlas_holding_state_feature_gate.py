"""Atomic holding-state authority rollout gate.

Packaged default is legacy. Canonical is deployment-locked. The mode is global:
partial per-consumer activation is invalid. Shadow projections must remain
observation-only and externally invisible.
"""
from __future__ import annotations
import os

FEATURE_FLAG_NAME='ATLAS_HOLDING_STATE_AUTHORITY'
PACKAGED_DEFAULT='legacy'
VALID_MODES=('legacy','shadow','canonical')
CONSUMERS=('pre_market','intraday','eod','conversation','broker_pending','holding_sections')
CANONICAL_DEPLOYMENT_LOCKED=True

class FeatureGateError(RuntimeError):pass

def resolve_mode(*,env=None,consumer_modes=None,canonical_unlock=False):
    env=os.environ if env is None else env
    mode=str(env.get(FEATURE_FLAG_NAME,PACKAGED_DEFAULT)).strip().lower()
    if mode not in VALID_MODES:raise FeatureGateError('INVALID_HOLDING_STATE_AUTHORITY_MODE')
    if consumer_modes is not None:
        vals={str(v).lower() for v in consumer_modes.values()}
        if set(consumer_modes)!=set(CONSUMERS) or len(vals)!=1 or mode not in vals:
            raise FeatureGateError('PARTIAL_PER_CONSUMER_ACTIVATION_FORBIDDEN')
    if mode=='canonical' and (CANONICAL_DEPLOYMENT_LOCKED or not canonical_unlock):
        raise FeatureGateError('CANONICAL_MODE_DEPLOYMENT_LOCKED')
    return {'mode':mode,'external_behavior':'LEGACY_UNCHANGED' if mode in {'legacy','shadow'} else 'CANONICAL','shadow_external_visibility':False if mode=='shadow' else None,'all_consumers_atomic':True,'canonical_locked':CANONICAL_DEPLOYMENT_LOCKED}

def assert_shadow_no_external_change(legacy_output,shadow_external_output):
    if legacy_output!=shadow_external_output:raise FeatureGateError('SHADOW_EXTERNALLY_VISIBLE_CHANGE')
    return True
__all__=['FEATURE_FLAG_NAME','PACKAGED_DEFAULT','VALID_MODES','CONSUMERS','FeatureGateError','resolve_mode','assert_shadow_no_external_change']
