"""Actual-environment, all-six-units Atlas feature gate."""
from __future__ import annotations
import json,os
FEATURE_FLAG_NAME="ATLAS_HOLDING_STATE_AUTHORITY"
MANIFEST_ENV="ATLAS_HOLDING_STATE_RUNTIME_MANIFEST"
PACKAGED_DEFAULT="legacy"
UNITS=("PRE_MARKET_HOLDINGS","INTRADAY_HOLDINGS","EOD_POSTMARKET_HOLDINGS","CONVERSATION_HOLDINGS","BROKER_PENDING_VISIBILITY","DAILY_PP_HOLDING_SECTIONS")

def mode(environ=None):
    env=os.environ if environ is None else environ
    value=str(env.get(FEATURE_FLAG_NAME,PACKAGED_DEFAULT)).strip().lower()
    if value not in ("legacy","shadow","canonical"):raise RuntimeError("INVALID_AUTHORITY_MODE")
    if value!="legacy":
        manifest=env.get(MANIFEST_ENV)
        if not manifest:raise RuntimeError("RUNTIME_MANIFEST_REQUIRED")
        from atlas_holding_state_packet_builder import verify_runtime_manifest
        record=verify_runtime_manifest(manifest)
        if record["mode"]!=value or sorted(record["units"])!=sorted(UNITS):raise RuntimeError("ALL_SIX_UNITS_REQUIRED")
        if value=="canonical" and not record.get("canonical_unlocked"):raise RuntimeError("CANONICAL_MODE_LOCKED")
    return value

def sidecar_initialized(environ=None):
    env=os.environ if environ is None else environ
    return str(env.get("ATLAS_CANONICAL_SIDECAR_INITIALIZED","")).lower() in ("1","true","yes")

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
VALID_MODES = ('legacy', 'shadow', 'canonical')
CONSUMERS = ('pre_market', 'intraday', 'eod', 'conversation', 'broker_pending', 'holding_sections')
CANONICAL_DEPLOYMENT_LOCKED = True

class FeatureGateError(RuntimeError):
    pass

def resolve_mode(*, env=None, consumer_modes=None, canonical_unlock=False):
    env = os.environ if env is None else env
    mode = str(env.get(FEATURE_FLAG_NAME, PACKAGED_DEFAULT)).strip().lower()
    if mode not in VALID_MODES:
        raise FeatureGateError('INVALID_HOLDING_STATE_AUTHORITY_MODE')
    if consumer_modes is not None:
        vals = {str(v).lower() for v in consumer_modes.values()}
        if set(consumer_modes) != set(CONSUMERS) or len(vals) != 1 or mode not in vals:
            raise FeatureGateError('PARTIAL_PER_CONSUMER_ACTIVATION_FORBIDDEN')
    if mode == 'canonical' and (CANONICAL_DEPLOYMENT_LOCKED or not canonical_unlock):
        raise FeatureGateError('CANONICAL_MODE_DEPLOYMENT_LOCKED')
    return {'mode': mode, 'external_behavior': 'LEGACY_UNCHANGED' if mode in {'legacy', 'shadow'} else 'CANONICAL', 'shadow_external_visibility': False if mode == 'shadow' else None, 'all_consumers_atomic': True, 'canonical_locked': CANONICAL_DEPLOYMENT_LOCKED}

def assert_shadow_no_external_change(legacy_output, shadow_external_output):
    if legacy_output != shadow_external_output:
        raise FeatureGateError('SHADOW_EXTERNALLY_VISIBLE_CHANGE')
    return True
__all__ = ['FEATURE_FLAG_NAME', 'PACKAGED_DEFAULT', 'VALID_MODES', 'CONSUMERS', 'FeatureGateError', 'resolve_mode', 'assert_shadow_no_external_change']

# Complete additive V1+V2/V3 public surface.
__all__ = sorted(n for n in globals() if not n.startswith("_"))
