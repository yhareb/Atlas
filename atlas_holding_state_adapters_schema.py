
"""Phase 3 producer-adapter schemas for Atlas Holding-State Authority.

/tmp staging only; no production imports; adapters normalize inputs only and never
calculate final action.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

ADAPTER_SCHEMA_VERSION = "atlas_holding_state_adapters.v1"
ADAPTERS = (
    "db_open_positions", "provider_quotes", "portfolio_event_journal", "daily_reunderwrite_packet",
    "profit_protection_packet", "prior_canonical_ledger", "nyse_calendar", "corporate_action_normalizer",
)
VALIDITY = ("VALID", "INVALID", "STALE", "MISSING", "REJECTED")

@dataclass(frozen=True)
class AdapterRecord:
    adapter_schema_version: str
    adapter_name: str
    source_type: str
    source_path: str | None
    source_timestamp: str | None
    freshness: str
    digest: str
    validity: str
    rejection_reason: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_adapter_record(d: dict[str, Any]) -> tuple[bool, list[str]]:
    errors=[]
    if d.get('adapter_schema_version') != ADAPTER_SCHEMA_VERSION: errors.append('SCHEMA_VERSION_INVALID')
    if d.get('adapter_name') not in ADAPTERS: errors.append('ADAPTER_NAME_INVALID')
    if d.get('validity') not in VALIDITY: errors.append('VALIDITY_INVALID')
    for k in ['source_type','freshness','digest','payload']:
        if k not in d: errors.append(f'MISSING_{k.upper()}')
    if d.get('validity') != 'VALID' and not d.get('rejection_reason'):
        errors.append('REJECTION_REASON_REQUIRED')
    return not errors, errors
