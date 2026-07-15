"""Immutable Atlas canonical packet and receipt primitives (V3)."""
from __future__ import annotations
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, Mapping
import hashlib,json
PACKET_SCHEMA_VERSION="atlas_holding_state_packet.v3"
RECEIPT_SCHEMA_VERSION="atlas_packet_load_receipt.v3"

def stable_json(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def digest(value:Any)->str:return hashlib.sha256(stable_json(value).encode()).hexdigest()
def freeze(value:Any)->Any:
    if isinstance(value,dict):return MappingProxyType({k:freeze(v) for k,v in value.items()})
    if isinstance(value,list):return tuple(freeze(v) for v in value)
    return value
def thaw(value:Any)->Any:
    if isinstance(value,Mapping):return {k:thaw(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [thaw(v) for v in value]
    return value

def verify_packet(packet:Mapping[str,Any])->None:
    p=thaw(packet)
    if p.get("schema_version")!=PACKET_SCHEMA_VERSION:raise ValueError("PACKET_SCHEMA_INVALID")
    claimed=p.pop("packet_digest",None)
    if not claimed or digest(p)!=claimed:raise ValueError("PACKET_DIGEST_INVALID")
def verify_receipt(receipt:Mapping[str,Any],packet:Mapping[str,Any])->None:
    r=thaw(receipt)
    if r.get("schema_version")!=RECEIPT_SCHEMA_VERSION:raise ValueError("RECEIPT_SCHEMA_INVALID")
    if r.get("packet_id")!=packet.get("packet_id") or r.get("packet_digest")!=packet.get("packet_digest"):raise ValueError("RECEIPT_PACKET_REFERENCE_INVALID")
    claimed=r.pop("receipt_digest",None)
    if not claimed or digest(r)!=claimed:raise ValueError("RECEIPT_DIGEST_INVALID")

def immutable_packet(value:Mapping[str,Any])->Mapping[str,Any]:verify_packet(value);return freeze(thaw(value))
def immutable_receipt(value:Mapping[str,Any],packet:Mapping[str,Any])->Mapping[str,Any]:verify_receipt(value,packet);return freeze(thaw(value))

def make_packet(payload:Mapping[str,Any])->dict:
    p=dict(payload);p["schema_version"]=PACKET_SCHEMA_VERSION
    policies=sorted(p.get("policy_versions") or [])
    if not p.get("packet_id"):
        p["packet_id"]=digest({"packet_schema_version":PACKET_SCHEMA_VERSION,"trade_id":p.get("trade_id"),"lot_id_or_empty":p.get("lot_id") or "","completed_session":p.get("completed_session"),"canonical_input_digest":p.get("canonical_input_digest"),"sorted_policy_versions":policies})
    p.pop("packet_digest",None);p["packet_digest"]=digest(p);return p

def make_receipt(payload:Mapping[str,Any],packet:Mapping[str,Any])->dict:
    r=dict(payload);r.update(schema_version=RECEIPT_SCHEMA_VERSION,packet_id=packet["packet_id"],packet_digest=packet["packet_digest"])
    if not r.get("receipt_id"):
        r["receipt_id"]=digest({"receipt_schema_version":RECEIPT_SCHEMA_VERSION,"packet_id":r["packet_id"],"packet_digest":r["packet_digest"],"loaded_at":r.get("loaded_at"),"current_calendar_digest":r.get("current_calendar_digest"),"current_trade_lot_binding_digest":r.get("current_trade_lot_binding_digest"),"current_broker_lifecycle_digest":r.get("current_broker_lifecycle_digest"),"validation_policy_version":r.get("validation_policy_version")})
    r.pop("receipt_digest",None);r["receipt_digest"]=digest(r);return r
__all__=["PACKET_SCHEMA_VERSION","RECEIPT_SCHEMA_VERSION","stable_json","digest","freeze","thaw","verify_packet","verify_receipt","immutable_packet","immutable_receipt","make_packet","make_receipt"]

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from dataclasses import asdict
SCHEMA_VERSION = 'atlas_holding_state_packet.v3'
QUOTE_SELECTION_VERSION = 'quote_selection.v1'
LEDGER_SCHEMA_VERSION = 'holding_state_action_ledger.v1'
ADVISORY_ACTIONS = ('HOLD', 'HOLD TIGHT', 'TRIM REVIEW', 'EXIT REVIEW', 'SELL NOW', 'DATA INCOMPLETE')
STRONG_ACTIONS = ('HOLD TIGHT', 'TRIM REVIEW', 'EXIT REVIEW', 'SELL NOW')
ACTION_RANK = {'SELL NOW': 0, 'EXIT REVIEW': 1, 'TRIM REVIEW': 2, 'HOLD TIGHT': 3, 'HOLD': 4, 'DATA INCOMPLETE': 5}
OBSERVED_STATES = ('PRICE_UNAVAILABLE', 'ABOVE_STOP', 'NEAR_STOP', 'STOP_BREACHED_PRE_MARKET', 'STOP_BREACHED_REGULAR', 'STOP_BREACHED_AFTER_MARKET', 'INVALID_OR_STALE_EVENT', 'THESIS_INTACT', 'THESIS_WEAKENED', 'THESIS_BROKEN', 'PROFIT_GIVEBACK_ACTIVE', 'TARGET_ZONE_REACHED', 'CATALYST_RISK_ACTIVE', 'LIFECYCLE_CONTRADICTION')
BROKER_STATES = ('NO_BROKER_EVENT', 'BROKER_SELL_SUBMITTED', 'BROKER_SELL_FILLED', 'CASH_CREDIT_POSTED', 'BROKER_CANCELLED', 'MANUAL_CORRECTION', 'RECONCILIATION_EXCEPTION')
REASON_CODES = ('REGULAR_STOP_BREACH', 'PREMARKET_STOP_BREACH', 'AFTERHOURS_STOP_BREACH', 'PROFIT_GIVEBACK', 'TARGET_ZONE_REACHED', 'PROFIT_PROTECTION_TRIM_REVIEW', 'THESIS_DETERIORATION', 'THESIS_BROKEN', 'CATALYST_RISK', 'SECTOR_BREAKDOWN', 'REGIME_RISK', 'BROKER_SUBMITTED_PENDING_FILL', 'LIFECYCLE_CONTRADICTION', 'DATA_STALE_OR_MISSING', 'GENERIC_HOLD_DOES_NOT_CLEAR', 'RETENTION_EXPIRED_WITHOUT_CLEARING_EVIDENCE', 'EXPLICIT_STOP_CLEAR', 'EXPLICIT_PROFIT_CLEAR', 'EXPLICIT_THESIS_CLEAR')
LEDGER_EVENT_TYPES = ('ACTION_CREATED', 'ACTION_RETAINED_STALE_INPUT', 'ACTION_STRENGTHENED', 'ACTION_CLEARED', 'SOURCE_SUPERSEDED', 'LIFECYCLE_CONTRADICTION', 'IDEMPOTENT_NO_OP')
CANONICAL_INPUT_FIELDS = ('schema_version', 'normalized_trade_lot_identity', 'canonical_levels', 'accepted_and_rejected_provider_candidates', 'stop_target_broker_events', 'selected_daily_component_id_and_digest', 'selected_pp_component_id_and_digest', 'quiver_raw_evidence_digest', 'perme_context_digest', 'prior_canonical_state_digest', 'governed_calendar_digest', 'policy_versions')

@dataclass(frozen=True)
class PriceRole:
    price: float | None
    source: str
    timestamp: str | None
    validity: str
    reason: str | None = None

@dataclass(frozen=True)
class QuoteSelection:
    selection_policy_version: str
    report_session: str
    selected_display_price: PriceRole
    selected_valuation_price: PriceRole
    selected_stop_evaluation_price: PriceRole
    rejected_quotes: tuple[dict[str, Any], ...] = ()
    timestamp_ordering_proof: str = ''

@dataclass(frozen=True)
class AxisState:
    state: str
    reason_codes: tuple[str, ...] = ()
    source_digest: str | None = None
    source_timestamp: str | None = None

@dataclass(frozen=True)
class AdvisoryAction:
    action: str
    reason_codes: tuple[str, ...] = ()
    source: str = 'CANONICAL_PRECEDENCE_ENGINE'
    source_digest: str | None = None

@dataclass(frozen=True)
class BrokerLifecycle:
    state: str = 'NO_BROKER_EVENT'
    event_ids: tuple[str, ...] = ()
    authority: str = 'BROKER_LEDGER_AXIS'
    automatic_trade_authority: str = 'NO'

@dataclass(frozen=True)
class RetentionState:
    last_valid_stronger_action: str | None = None
    retained_since: str | None = None
    retention_expires_at: str | None = None
    retention_policy: str | None = None
    original_reason_codes: tuple[str, ...] = ()
    required_clearing_evidence: tuple[str, ...] = ()
    cleared_by: dict[str, Any] | None = None
    expiry_behavior: str | None = None

@dataclass(frozen=True)
class HoldingStatePacket:
    schema_version: str
    packet_id: str
    packet_digest: str
    completed_session: str
    canonical_input_digest: str
    trade_identity: Mapping[str, Any]
    canonical_levels: Mapping[str, Any]
    provider_candidates: tuple[Mapping[str, Any], ...]
    stop_target_broker_events: tuple[Mapping[str, Any], ...]
    selected_components: Mapping[str, Any]
    provenance: Mapping[str, Any]
    axes: Mapping[str, Any]
    price_roles: Mapping[str, Any]
    retention: Mapping[str, Any]
    alert_projection: Mapping[str, Any]
    policy_versions: tuple[str, ...]
    built_at: str
    freshness_expires_at: str

@dataclass(frozen=True)
class PacketLoadValidationReceipt:
    schema_version: str
    receipt_id: str
    receipt_digest: str
    packet_id: str
    packet_digest: str
    loaded_at: str
    current_calendar_digest: str | None
    current_trade_lot_binding_digest: str | None
    current_broker_lifecycle_digest: str | None
    component_freshness: Mapping[str, str]
    price_role_usability: Mapping[str, bool]
    retention_valid: bool
    eligibility: str
    usability: str
    reason_codes: tuple[str, ...]
    rebuild_required: bool
    validation_policy_version: str

def to_dict(obj: Any) -> Any:
    if hasattr(obj, '__dataclass_fields__'):
        return asdict(obj)
    return obj

def validate_packet_shape(packet: dict[str, Any]) -> tuple[bool, list[str]]:
    errors = []
    intermediate = 'generated_at' in packet and 'packet_id' not in packet
    if not intermediate and packet.get('schema_version') != PACKET_SCHEMA_VERSION:
        errors.append('SCHEMA_VERSION_INVALID')
    required = ('generated_at', 'ticker', 'trade_identity', 'quote_selection', 'axes', 'retention', 'components', 'final_precedence', 'ledger', 'authority', 'digests') if intermediate else ('packet_id', 'packet_digest', 'completed_session', 'canonical_input_digest', 'trade_identity', 'canonical_levels', 'provider_candidates', 'stop_target_broker_events', 'selected_components', 'provenance', 'axes', 'price_roles', 'retention', 'alert_projection', 'policy_versions', 'built_at', 'freshness_expires_at')
    errors += ['MISSING_' + k.upper() for k in required if k not in packet]
    axes = packet.get('axes') or {}
    for k in ('observed_market_risk_state', 'advisory_action', 'broker_ledger_lifecycle'):
        if k not in axes:
            errors.append('MISSING_AXIS_' + k.upper())
    if (axes.get('advisory_action') or {}).get('action') not in ADVISORY_ACTIONS:
        errors.append('ADVISORY_ACTION_INVALID')
    if (axes.get('broker_ledger_lifecycle') or {}).get('state') not in BROKER_STATES:
        errors.append('BROKER_STATE_INVALID')
    return (not errors, errors)

def validate_receipt_shape(r: dict[str, Any]) -> tuple[bool, list[str]]:
    e = []
    if r.get('schema_version') != RECEIPT_SCHEMA_VERSION:
        e.append('RECEIPT_SCHEMA_INVALID')
    for k in ('receipt_id', 'receipt_digest', 'packet_id', 'packet_digest', 'loaded_at', 'usability', 'reason_codes', 'rebuild_required'):
        if k not in r:
            e.append('MISSING_RECEIPT_' + k.upper())
    if r.get('usability') not in ('USABLE', 'DATA_INCOMPLETE', 'BLOCKED'):
        e.append('RECEIPT_USABILITY_INVALID')
    return (not e, e)

# Complete additive V1+V2/V3 public surface.
__all__ = sorted(n for n in globals() if not n.startswith("_"))
