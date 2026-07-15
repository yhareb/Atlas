"""Explicit typed section integration with ordinary arguments (no context-local state)."""
from __future__ import annotations
import json, os, pathlib
from typing import Any, Callable, Mapping
EVENT_LOG_ENV = 'ATLAS_CANONICAL_EVENT_LOG'
BYPASS_SENTINEL_ENV = 'ATLAS_BYPASS_SENTINEL_LOG'

def bypass_local_authority(reference: str, legacy_callable: Callable | None=None, *args, **kwargs):
    """Runtime sentinel for an explicit REPLACE_AUTHORITY construction site.

    Legacy invokes the producer/local implementation. Shadow records the bypass
    candidate while preserving legacy behavior. Canonical never invokes it.
    """
    selected = mode()
    target = os.environ.get(BYPASS_SENTINEL_ENV)
    event = {'event': 'BYPASS_LOCAL_AUTHORITY', 'reference': reference, 'mode': selected, 'legacy_invoked': selected in ('legacy', 'shadow') and legacy_callable is not None}
    if target:
        with pathlib.Path(target).open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n')
    if selected == 'canonical':
        return {'bypassed': True, 'reference': reference}
    return legacy_callable(*args, **kwargs) if legacy_callable is not None else None

def _append_event(*, entrypoint, unit, selected_mode, legacy_called, projection=None, packet=None):
    """Append one deliberately non-secret dispatch record when evidence logging is enabled."""
    target = os.environ.get(EVENT_LOG_ENV)
    if os.environ.get('ATLAS_CANONICAL_EVENT_SUPPRESS') == '1':
        return
    if not target:
        return
    event = {'entrypoint': entrypoint or '<unspecified>', 'unit': unit, 'selected_mode': selected_mode, 'legacy_called': bool(legacy_called), 'projection_packet_id': None, 'projection_packet_digest': None, 'projection_present': projection is not None}
    if packet is not None:
        event['projection_packet_id'] = packet.get('packet_id')
        event['projection_packet_digest'] = packet.get('packet_digest') or packet.get('digest')
    with pathlib.Path(target).open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n')
from atlas_holding_state_schema import immutable_packet, immutable_receipt, thaw
from atlas_holding_state_adapters import render_section, adapter
from atlas_holding_state_feature_gate import mode, MANIFEST_ENV
from atlas_holding_state_packet_builder import verify_runtime_manifest, load_build_validate_rebuild as coordinator_load
UNITS = ('PRE_MARKET_HOLDINGS', 'INTRADAY_HOLDINGS', 'EOD_POSTMARKET_HOLDINGS', 'CONVERSATION_HOLDINGS', 'BROKER_PENDING_VISIBILITY', 'DAILY_PP_HOLDING_SECTIONS')
UNIT_ADAPTER = {'PRE_MARKET_HOLDINGS': 'PRE_MARKET_TYPED', 'INTRADAY_HOLDINGS': 'INTRADAY_TYPED', 'EOD_POSTMARKET_HOLDINGS': 'EOD_TYPED', 'CONVERSATION_HOLDINGS': 'CONVERSATION_TYPED', 'BROKER_PENDING_VISIBILITY': 'BROKER_TYPED', 'DAILY_PP_HOLDING_SECTIONS': 'DAILY_PP_TYPED'}
ENTRY_ADAPTER = {'pre_market_report.generate_pre_market_report': 'PRE_MARKET_TYPED', 'atlas_report_handoff.build_atlas_handoff_report': 'PRE_MARKET_TYPED', 'morning_briefing.render_morning_briefing': 'PRE_MARKET_TYPED', 'morning_briefing.generate_morning_briefing': 'PRE_MARKET_TYPED', 'atlas_intraday._build_report': 'INTRADAY_TYPED', 'atlas_intraday._quick_status_report': 'INTRADAY_TYPED', 'atlas_eod_positions.build_report': 'EOD_TYPED', 'post_market_report.generate_post_market_report': 'EOD_TYPED', 'eod_writer.generate_eod_handoff': 'EOD_TYPED', 'atlas_conversation_router.dispatch_atlas_trading_question': 'CONVERSATION_TYPED', 'atlas_conversation_router.holdings_reunderwrite_conversation_answer': 'CONVERSATION_TYPED', 'atlas_report_authority.render_pending_broker_confirmation': 'BROKER_TYPED', 'atlas_report_authority.render_portfolio_visibility_block': 'BROKER_TYPED', 'atlas_profit_protection_v2.render_report_block_from_snapshot': 'DAILY_PP_TYPED'}

def load_build_validate_rebuild(unit: str):
    if unit not in UNITS:
        raise ValueError('UNKNOWN_ACTIVATION_UNIT')
    manifest = verify_runtime_manifest(os.environ[MANIFEST_ENV])
    return coordinator_load(manifest, unit)

def _v3_improved_project(unit, packet, receipt):
    if unit not in UNITS:
        raise ValueError('UNKNOWN_ACTIVATION_UNIT')
    try:
        packet = immutable_packet(packet)
        receipt = immutable_receipt(receipt, packet)
    except ValueError as exc:
        reason = str(exc)
        original = thaw(packet)
        return {
            'unit': unit, 'authority_state': 'BLOCKED',
            'label': 'CANONICAL HOLDING AUTHORITY UNAVAILABLE — ' + reason,
            'reason_codes': [reason], 'historical_packet': {
                'packet_id': original.get('packet_id'),
                'provenance': deepcopy(original.get('provenance') or {}),
            }, 'local_fallback': False, 'rebuild_required': True,
        }
    return render_section(unit, packet, receipt)

def integrate_section(value, unit, packet, receipt, adapter_name=None):
    projection = project(unit, packet, receipt)
    return adapter(adapter_name or UNIT_ADAPTER[unit])(value, projection)

def select_leaf(unit: str, legacy_thunk: Callable, *, reference: str, projector: Callable | None=None):
    """Select a concrete leaf lazily; canonical never evaluates local authority."""
    selected = mode()
    if selected == 'legacy':
        return legacy_thunk()
    (packet, receipt) = load_build_validate_rebuild(unit)
    projection = project(unit, packet, receipt)
    if selected == 'shadow':
        value = legacy_thunk()
        _append_event(entrypoint=reference, unit=unit, selected_mode=selected, legacy_called=True, projection=projection, packet=packet)
        return value
    value = projector(projection) if projector else list(projection.lines)
    _append_event(entrypoint=reference, unit=unit, selected_mode=selected, legacy_called=False, projection=projection, packet=packet)
    return value

def dispatch_at_entry(unit: str, legacy_callable: Callable, args=(), kwargs=None, *, entrypoint: str | None=None, adapter_name: str | None=None):
    """Run canonical work at the boundary and replace only the typed holding section.

    Legacy assembly executes exactly once in every mode. Shadow returns its value
    byte/object-identically. Canonical uses an explicit per-entrypoint adapter.
    """
    kwargs = {} if kwargs is None else kwargs
    selected = mode()
    if selected == 'legacy':
        _append_event(entrypoint=entrypoint, unit=unit, selected_mode=selected, legacy_called=True)
        return {'handled': False, 'mode': 'legacy'}
    (packet, receipt) = load_build_validate_rebuild(unit)
    projection = project(unit, packet, receipt)
    if selected == 'shadow':
        old = os.environ.get('ATLAS_HOLDING_STATE_AUTHORITY')
        os.environ['ATLAS_HOLDING_STATE_AUTHORITY'] = 'legacy'
        old_suppress = os.environ.get('ATLAS_CANONICAL_EVENT_SUPPRESS')
        os.environ['ATLAS_CANONICAL_EVENT_SUPPRESS'] = '1'
        try:
            original = legacy_callable(*args, **kwargs)
        finally:
            if old is None:
                os.environ.pop('ATLAS_HOLDING_STATE_AUTHORITY', None)
            else:
                os.environ['ATLAS_HOLDING_STATE_AUTHORITY'] = old
            if old_suppress is None:
                os.environ.pop('ATLAS_CANONICAL_EVENT_SUPPRESS', None)
            else:
                os.environ['ATLAS_CANONICAL_EVENT_SUPPRESS'] = old_suppress
        _append_event(entrypoint=entrypoint, unit=unit, selected_mode=selected, legacy_called=True, projection=projection, packet=packet)
        return {'handled': True, 'mode': 'shadow', 'value': original, 'shadow_projection': projection}
    chosen = adapter_name or (ENTRY_ADAPTER.get(entrypoint) if entrypoint else None) or UNIT_ADAPTER[unit]
    original = legacy_callable(*args, **kwargs)
    value = adapter(chosen)(original, projection)
    _append_event(entrypoint=entrypoint, unit=unit, selected_mode=selected, legacy_called=True, projection=projection, packet=packet)
    return {'handled': True, 'mode': 'canonical', 'value': value, 'projection': projection, 'adapter': chosen}

def direct_entrypoint(module_name, function_name, unit, argv=None):
    selected = mode()
    if selected == 'legacy':
        return None
    module = __import__(module_name)
    fn = getattr(module, function_name)
    result = dispatch_at_entry(unit, fn, (), {}, entrypoint=f'{module_name}.{function_name}')
    value = result['value']
    if isinstance(value, str):
        print(value)
    elif value is not None:
        print(json.dumps(value, sort_keys=True, default=str))
    return 0

def load_validate_project_premarket(p, r):
    return project(UNITS[0], p, r)

def load_validate_project_intraday(p, r):
    return project(UNITS[1], p, r)

def load_validate_project_eod_postmarket(p, r):
    return project(UNITS[2], p, r)

def load_validate_project_conversation(p, r):
    return project(UNITS[3], p, r)

def load_validate_project_broker_visibility(p, r):
    return project(UNITS[4], p, r)

def load_validate_project_daily_pp_sections(p, r):
    return project(UNITS[5], p, r)
from copy import deepcopy
from threading import local
from functools import wraps
from atlas_holding_state_packet_builder import digest
from atlas_holding_state_schema import PACKET_SCHEMA_VERSION, RECEIPT_SCHEMA_VERSION
_DISPATCH_CONTEXT = local()

def _validate(packet, receipt):
    reasons = []
    if not packet:
        return (False, ['CANONICAL_BUILD_MISSING_OR_FAILED'])
    if packet.get('schema_version') != PACKET_SCHEMA_VERSION:
        reasons.append('PACKET_SCHEMA_INVALID')
    if digest({k: v for (k, v) in packet.items() if k != 'packet_digest'}) != packet.get('packet_digest'):
        reasons.append('PACKET_DIGEST_INVALID')
    if not receipt:
        return (False, sorted(set(reasons + ['RECEIPT_MISSING'])))
    if receipt.get('schema_version') != RECEIPT_SCHEMA_VERSION:
        reasons.append('RECEIPT_SCHEMA_INVALID')
    if digest({k: v for (k, v) in receipt.items() if k != 'receipt_digest'}) != receipt.get('receipt_digest'):
        reasons.append('RECEIPT_DIGEST_INVALID')
    if receipt.get('packet_id') != packet.get('packet_id') or receipt.get('packet_digest') != packet.get('packet_digest'):
        reasons.append('RECEIPT_PACKET_REFERENCE_MISMATCH')
    reasons += receipt.get('reason_codes') or []
    return (receipt.get('usability') == 'USABLE' and (not reasons), sorted(set(reasons)))

def _unavailable(reason):
    return {'value': None, 'label': 'UNAVAILABLE — ' + reason}

def bind_mode(*, mode, legacy_external, packet=None, receipt=None, unit):
    mode = mode.lower()
    if mode == 'legacy':
        return {'external': legacy_external, 'internal': None, 'effects': False}
    internal = project(unit, packet, receipt)
    if mode == 'shadow':
        return {'external': legacy_external, 'internal': internal, 'effects': False}
    if mode == 'canonical':
        raise RuntimeError('CANONICAL_MODE_DEPLOYMENT_LOCKED')
    raise ValueError('INVALID_HOLDING_STATE_AUTHORITY_MODE')

def set_dispatch_context(context):
    previous = getattr(_DISPATCH_CONTEXT, 'value', None)
    _DISPATCH_CONTEXT.value = context
    return previous

def reset_dispatch_context(token):
    _DISPATCH_CONTEXT.value = token

def _mode(ctx):
    from atlas_holding_state_feature_gate import resolve_mode
    return resolve_mode(env=ctx.get('env'), canonical_unlock=bool(ctx.get('canonical_unlock')))['mode']

def _record(ctx, unit, entry, mode, value):
    event = {'unit': unit, 'entrypoint': entry, 'mode': mode, 'packet_id': (value or {}).get('packet_id') if isinstance(value, dict) else None}
    ctx.setdefault('dispatch_events', []).append(event)
    ctx['shadow_projection' if mode == 'shadow' else 'canonical_projection'] = value

def dispatch_holding_call(*, unit, legacy_call, args, kwargs):
    """Compatibility dispatcher for non-entry local functions.

 Entrypoints, not these local shims, are the canonical trust boundary.  This
 remains for legacy callers and defense in depth; canonical entry paths never
 reach it.
 """
    ctx = getattr(_DISPATCH_CONTEXT, 'value', None) or {}
    mode = _mode(ctx)
    if mode == 'canonical':
        value = project(unit, ctx.get('packet'), ctx.get('receipt'))
        _record(ctx, unit, legacy_call.__qualname__, mode, value)
        return value
    external = legacy_call(*args, **kwargs)
    if mode == 'shadow':
        value = project(unit, ctx.get('packet'), ctx.get('receipt'))
        _record(ctx, unit, legacy_call.__qualname__, mode, value)
    return external

def wire_holding_call_site(fn, unit):
    """Backward-compatible local shim; entrypoint wiring is authoritative."""
    if unit not in UNITS:
        raise ValueError('UNKNOWN_ACTIVATION_UNIT')

    @wraps(fn)
    def wired(*args, **kwargs):
        return dispatch_holding_call(unit=unit, legacy_call=fn, args=args, kwargs=kwargs)
    wired.__atlas_canonical_unit__ = unit
    wired.__atlas_legacy_function__ = fn
    return wired

def canonical_render(value, kind='dict'):
    """Adapt a projection to a generator's established return category."""
    if kind == 'dict':
        return value
    if kind == 'text':
        import json
        return json.dumps(value, sort_keys=True, separators=(',', ':'))
    if kind == 'lines':
        return [canonical_render(value, 'text')]
    if kind == 'list':
        return [value]
    if kind == 'status':
        return 0
    raise ValueError('UNKNOWN_CANONICAL_RETURN_KIND')

def wire_entrypoint(fn, unit, return_kind='dict', adapter=None):
    """Branch at function entry, before any legacy/local holding authority.

 Shadow computes a canonical projection first and independently, then invokes
 legacy exactly once and returns that legacy value unchanged. Canonical never
 invokes ``fn``. Signature metadata is retained by ``wraps`` and arbitrary
 positional/keyword contracts pass through untouched in legacy/shadow.
 """
    if unit not in UNITS:
        raise ValueError('UNKNOWN_ACTIVATION_UNIT')

    @wraps(fn)
    def entry(*args, **kwargs):
        ctx = getattr(_DISPATCH_CONTEXT, 'value', None) or {}
        mode = _mode(ctx)
        if mode == 'legacy':
            return fn(*args, **kwargs)
        value = project(unit, ctx.get('packet'), ctx.get('receipt'))
        _record(ctx, unit, fn.__qualname__, mode, value)
        if mode == 'shadow':
            return fn(*args, **kwargs)
        return adapter(value, args, kwargs) if adapter else canonical_render(value, return_kind)
    entry.__atlas_entrypoint__ = True
    entry.__atlas_canonical_unit__ = unit
    entry.__atlas_legacy_function__ = fn
    entry.__atlas_return_kind__ = return_kind
    return entry

def _v1_baseline_project(unit: str, packet: dict[str, Any] | None, receipt: dict[str, Any] | None) -> dict[str, Any]:
    if unit not in UNITS:
        raise ValueError('UNKNOWN_ACTIVATION_UNIT')
    (usable, reasons) = _validate(packet, receipt)
    state = (receipt or {}).get('usability') or 'BLOCKED'
    reason = ', '.join(reasons) or 'UNUSABLE'
    if state == 'BLOCKED' or not packet:
        return {'unit': unit, 'authority_state': 'BLOCKED', 'label': 'CANONICAL HOLDING AUTHORITY UNAVAILABLE — ' + reason, 'reason_codes': reasons, 'historical_packet': {'packet_id': (packet or {}).get('packet_id'), 'provenance': deepcopy((packet or {}).get('provenance') or {})}, 'local_fallback': False, 'rebuild_required': True}
    if not usable:
        role_use = (receipt or {}).get('price_role_usability') or {}
        roles = {}
        for (name, value) in (packet.get('price_roles') or {}).items():
            roles[name] = deepcopy(value) if role_use.get(name, False) else _unavailable(reason)
        retained = deepcopy((packet.get('axes') or {}).get('advisory_action')) if receipt.get('retention_valid') else _unavailable('RETENTION_EXPIRED_REBUILD_REQUIRED')
        return {'unit': unit, 'authority_state': 'DATA_INCOMPLETE', 'label': 'DATA INCOMPLETE', 'trade_identity': deepcopy(packet.get('trade_identity')), 'canonical_levels_as_built': deepcopy(packet.get('canonical_levels')), 'provenance': deepcopy(packet.get('provenance')), 'price_roles': roles, 'retained_advisory_action': retained, 'reason_codes': reasons, 'local_fallback': False, 'rebuild_required': True}
    return {'unit': unit, 'authority_state': 'USABLE', 'packet_id': packet['packet_id'], 'axes': deepcopy(packet.get('axes') or {}), 'price_roles': deepcopy(packet.get('price_roles') or {}), 'canonical_levels': deepcopy(packet.get('canonical_levels') or {}), 'provenance': deepcopy(packet.get('provenance') or {}), 'local_fallback': False, 'rebuild_required': False}

def project(*args, **kwargs):
    """Backward-compatible overload: V2/V3 interface preferred, V1 accepted."""
    import inspect
    try:
        inspect.signature(_v3_improved_project).bind(*args, **kwargs)
    except TypeError:
        return _v1_baseline_project(*args, **kwargs)
    return _v3_improved_project(*args, **kwargs)
__all__ = sorted((n for n in globals() if not n.startswith('_')))
