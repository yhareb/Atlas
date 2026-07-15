"""Consumer section projection value object."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
@dataclass(frozen=True)
class SectionProjection:
    unit:str
    lines:tuple[str,...]
    structured:Any
    authority_state:str
    packet_id:str|None
    replacement_tokens:tuple[str,...]=()

    # Mapping-style compatibility preserves the V2/V3 typed leaf while allowing
    # V1 callers to read its structured projection.
    def __getitem__(self, key):
        if key == 'unit': return self.unit
        if key == 'authority_state': return self.authority_state
        if key == 'packet_id': return self.packet_id
        if key in ('reason_codes', 'rebuild_required', 'usability'):
            receipt = self.structured.get('receipt', {})
            if key == 'usability': return receipt.get(key, self.authority_state)
            return receipt.get(key, () if key == 'reason_codes' else False)
        if key == 'retained_advisory_action':
            receipt = self.structured.get('receipt', {})
            if not receipt.get('retention_valid', False):
                return {'value': None, 'label': 'UNAVAILABLE — RETENTION_EXPIRED_REBUILD_REQUIRED'}
            return self.structured.get('packet', {}).get('axes', {}).get('advisory_action')
        packet = self.structured.get('packet', {})
        if key in packet: return packet[key]
        if key == 'local_fallback': return False
        return self.structured[key]

    def get(self, key, default=None):
        try: return self[key]
        except (KeyError, TypeError): return default

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from dataclasses import asdict
ADAPTER_SCHEMA_VERSION = 'atlas_holding_state_adapters.v1'
ADAPTERS = ('db_open_positions', 'provider_quotes', 'portfolio_event_journal', 'daily_reunderwrite_packet', 'profit_protection_packet', 'prior_canonical_ledger', 'nyse_calendar', 'corporate_action_normalizer')
VALIDITY = ('VALID', 'INVALID', 'STALE', 'MISSING', 'REJECTED')

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
    errors = []
    if d.get('adapter_schema_version') != ADAPTER_SCHEMA_VERSION:
        errors.append('SCHEMA_VERSION_INVALID')
    if d.get('adapter_name') not in ADAPTERS:
        errors.append('ADAPTER_NAME_INVALID')
    if d.get('validity') not in VALIDITY:
        errors.append('VALIDITY_INVALID')
    for k in ['source_type', 'freshness', 'digest', 'payload']:
        if k not in d:
            errors.append(f'MISSING_{k.upper()}')
    if d.get('validity') != 'VALID' and (not d.get('rejection_reason')):
        errors.append('REJECTION_REASON_REQUIRED')
    return (not errors, errors)
