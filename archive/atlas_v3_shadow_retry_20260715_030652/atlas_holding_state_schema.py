
"""Atlas Holding-State Authority staged schema.

Phase 2A/2B only. Pure staging artifact. No production imports, no Telegram,
no broker actions, no atlas.db writes.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

SCHEMA_VERSION = "atlas_holding_state_authority.v2"
QUOTE_SELECTION_VERSION = "quote_selection.v1"
LEDGER_SCHEMA_VERSION = "holding_state_action_ledger.v1"

ADVISORY_ACTIONS = ("HOLD", "HOLD TIGHT", "TRIM REVIEW", "EXIT REVIEW", "SELL NOW", "DATA INCOMPLETE")
STRONG_ACTIONS = ("HOLD TIGHT", "TRIM REVIEW", "EXIT REVIEW", "SELL NOW")
ACTION_RANK = {"SELL NOW": 0, "EXIT REVIEW": 1, "TRIM REVIEW": 2, "HOLD TIGHT": 3, "HOLD": 4, "DATA INCOMPLETE": 5}

OBSERVED_STATES = (
    "PRICE_UNAVAILABLE", "ABOVE_STOP", "NEAR_STOP", "STOP_BREACHED_PRE_MARKET",
    "STOP_BREACHED_REGULAR", "STOP_BREACHED_AFTER_MARKET", "INVALID_OR_STALE_EVENT",
    "THESIS_INTACT", "THESIS_WEAKENED", "THESIS_BROKEN", "PROFIT_GIVEBACK_ACTIVE",
    "TARGET_ZONE_REACHED", "CATALYST_RISK_ACTIVE", "LIFECYCLE_CONTRADICTION",
)

BROKER_STATES = (
    "NO_BROKER_EVENT", "BROKER_SELL_SUBMITTED", "BROKER_SELL_FILLED", "CASH_CREDIT_POSTED",
    "BROKER_CANCELLED", "MANUAL_CORRECTION", "RECONCILIATION_EXCEPTION",
)

REASON_CODES = (
    "REGULAR_STOP_BREACH", "PREMARKET_STOP_BREACH", "AFTERHOURS_STOP_BREACH",
    "PROFIT_GIVEBACK", "TARGET_ZONE_REACHED", "PROFIT_PROTECTION_TRIM_REVIEW",
    "THESIS_DETERIORATION", "THESIS_BROKEN", "CATALYST_RISK", "SECTOR_BREAKDOWN",
    "REGIME_RISK", "BROKER_SUBMITTED_PENDING_FILL", "LIFECYCLE_CONTRADICTION",
    "DATA_STALE_OR_MISSING", "GENERIC_HOLD_DOES_NOT_CLEAR", "RETENTION_EXPIRED_WITHOUT_CLEARING_EVIDENCE",
    "EXPLICIT_STOP_CLEAR", "EXPLICIT_PROFIT_CLEAR", "EXPLICIT_THESIS_CLEAR",
)

LEDGER_EVENT_TYPES = (
    "ACTION_CREATED", "ACTION_RETAINED_STALE_INPUT", "ACTION_STRENGTHENED", "ACTION_CLEARED",
    "SOURCE_SUPERSEDED", "LIFECYCLE_CONTRADICTION", "IDEMPOTENT_NO_OP",
)

@dataclass(frozen=True)
class PriceRole:
    price: Optional[float]
    source: str
    timestamp: Optional[str]
    validity: str
    reason: Optional[str] = None

@dataclass(frozen=True)
class QuoteSelection:
    selection_policy_version: str
    report_session: str
    selected_display_price: PriceRole
    selected_valuation_price: PriceRole
    selected_stop_evaluation_price: PriceRole
    rejected_quotes: tuple[dict[str, Any], ...] = ()
    timestamp_ordering_proof: str = ""

@dataclass(frozen=True)
class AxisState:
    state: str
    reason_codes: tuple[str, ...] = ()
    source_digest: Optional[str] = None
    source_timestamp: Optional[str] = None

@dataclass(frozen=True)
class AdvisoryAction:
    action: str
    reason_codes: tuple[str, ...] = ()
    source: str = "CANONICAL_PRECEDENCE_ENGINE"
    source_digest: Optional[str] = None

@dataclass(frozen=True)
class BrokerLifecycle:
    state: str = "NO_BROKER_EVENT"
    event_ids: tuple[str, ...] = ()
    authority: str = "BROKER_LEDGER_AXIS"
    automatic_trade_authority: str = "NO"

@dataclass(frozen=True)
class RetentionState:
    last_valid_stronger_action: Optional[str] = None
    retained_since: Optional[str] = None
    retention_expires_at: Optional[str] = None
    retention_policy: Optional[str] = None
    original_reason_codes: tuple[str, ...] = ()
    required_clearing_evidence: tuple[str, ...] = ()
    cleared_by: Optional[dict[str, Any]] = None
    expiry_behavior: Optional[str] = None

@dataclass(frozen=True)
class HoldingStatePacket:
    schema_version: str
    generated_at: str
    ticker: str
    trade_identity: dict[str, Any]
    quote_selection: dict[str, Any]
    axes: dict[str, Any]
    retention: dict[str, Any]
    components: dict[str, Any]
    final_precedence: dict[str, Any]
    ledger: dict[str, Any]
    authority: dict[str, Any]
    digests: dict[str, Any]


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj


def validate_packet_shape(packet: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if packet.get("schema_version") != SCHEMA_VERSION:
        errors.append("SCHEMA_VERSION_INVALID")
    for key in ["generated_at", "ticker", "trade_identity", "quote_selection", "axes", "retention", "components", "final_precedence", "ledger", "authority", "digests"]:
        if key not in packet:
            errors.append(f"MISSING_{key.upper()}")
    axes = packet.get("axes") or {}
    for key in ["observed_market_risk_state", "advisory_action", "broker_ledger_lifecycle"]:
        if key not in axes:
            errors.append(f"MISSING_AXIS_{key.upper()}")
    adv = (axes.get("advisory_action") or {}).get("action")
    if adv not in ADVISORY_ACTIONS:
        errors.append("ADVISORY_ACTION_INVALID")
    broker = (axes.get("broker_ledger_lifecycle") or {}).get("state")
    if broker not in BROKER_STATES:
        errors.append("BROKER_STATE_INVALID")
    if packet.get("authority", {}).get("automatic_trade_closure") != "NO":
        errors.append("AUTOMATIC_TRADE_AUTHORITY_NOT_NO")
    return not errors, errors
