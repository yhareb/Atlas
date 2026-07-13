#!/usr/bin/env python3
"""Atlas Conversational Determinism Closure v1 schemas.

Staging-only artifact. Defines immutable packet, provenance, freshness, and
strong-action contracts for deterministic Atlas conversation routing.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
import hashlib, json, math

SCHEMA_VERSION = "atlas_conversational_determinism_closure_v1"

class RouterError(RuntimeError):
    pass

class Authority(str, Enum):
    TFE_PACKET = "TFE_PACKET"
    APPROVED_PROVIDER = "APPROVED_PROVIDER"
    APPROVED_PROVIDER_VIA_TFE = "APPROVED_PROVIDER_VIA_TFE"
    CANONICAL_LEDGER = "CANONICAL_LEDGER"
    HOLDINGS_PACKET = "HOLDINGS_REUNDERWRITE_PACKET"
    PERME_PACKET = "PERME_PACKET"
    QUIVER_PACKET = "QUIVER_PACKET"
    FDA_PACKET = "FDA_PACKET"
    RENDERER_CALC = "DETERMINISTIC_RENDERER_CALC"

class RejectedAuthority(str, Enum):
    USER_SUPPLIED = "USER_SUPPLIED"
    LLM_GENERATED = "LLM_GENERATED"
    UNLABELED = "UNLABELED"
    UNKNOWN = "UNKNOWN"

ACCEPTED_PRICE_AUTHORITIES = {
    Authority.APPROVED_PROVIDER.value,
    Authority.TFE_PACKET.value,
    Authority.CANONICAL_LEDGER.value,
    Authority.HOLDINGS_PACKET.value,
}
REJECTED_PRICE_AUTHORITIES = {x.value for x in RejectedAuthority}

ACTION_PRIORITY = {
    "SELL NOW": 0,
    "EXIT REVIEW": 1,
    "TRIM REVIEW": 2,
    "HOLD TIGHT": 3,
    "HOLD": 4,
    "DATA INCOMPLETE": 5,
}
BUY_FAMILY = {"BUY", "BUY SMALL", "BUY SMALL", "BUY_SMALL"}

@dataclass(frozen=True)
class SourceField:
    value: Any
    authority: str
    source: str
    timestamp: str | None = None
    freshness: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class PriceInput:
    value: float
    authority: str
    source: str
    timestamp: str | None = None

    def validate(self) -> "PriceInput":
        if self.authority in REJECTED_PRICE_AUTHORITIES or self.authority not in ACCEPTED_PRICE_AUTHORITIES:
            raise RouterError(f"PRICE_AUTHORITY_REJECTED:{self.authority}")
        if not isinstance(self.value, (int, float)) or not math.isfinite(float(self.value)) or float(self.value) <= 0:
            raise RouterError("PRICE_VALUE_INVALID")
        if not self.source:
            raise RouterError("PRICE_SOURCE_MISSING")
        return self


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest_obj(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def freeze_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(json.loads(canonical_json(dict(data))))


def unwrap_field(packet: Mapping[str, Any], key: str, default_authority: str, default_source: str) -> SourceField | None:
    raw = packet.get(key)
    if isinstance(raw, Mapping) and "value" in raw:
        return SourceField(
            value=raw.get("value"),
            authority=str(raw.get("authority") or default_authority),
            source=str(raw.get("source") or default_source),
            timestamp=raw.get("timestamp"),
            freshness=raw.get("freshness"),
        )
    if raw is None:
        return None
    return SourceField(raw, default_authority, default_source, packet.get("generated_at") or packet.get("timestamp"), packet.get("freshness_state"))


def field(value: Any, authority: str, source: str, timestamp: str | None = None, freshness: str | None = None) -> dict[str, Any]:
    return SourceField(value, authority, source, timestamp, freshness).to_dict()


def packet_digest(packet: Mapping[str, Any]) -> str:
    d = dict(packet)
    d.pop("packet_digest", None)
    return digest_obj(d)


def attach_digest(packet: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(packet)
    out["packet_digest"] = packet_digest(out)
    return out


def verify_digest(packet: Mapping[str, Any]) -> bool:
    expected = packet.get("packet_digest")
    if not expected:
        return False
    return str(expected) == packet_digest(packet)


def validate_freshness(packet: Mapping[str, Any] | None, *, now: datetime | None = None, ttl_seconds: int = 300, timestamp_keys=("generated_at", "timestamp", "created_at")) -> tuple[bool, str, float | None]:
    if not packet:
        return False, "PACKET_MISSING", None
    if packet.get("freshness_state") in {"STALE", "PACKET_STALE", "DATA_UNAVAILABLE"}:
        return False, str(packet.get("freshness_state")), None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    ts = None
    for key in timestamp_keys:
        ts = parse_dt(packet.get(key))
        if ts:
            break
    if not ts:
        return False, "PROVIDER_TIMESTAMP_MISSING", None
    age = max(0.0, (now - ts).total_seconds())
    if age > ttl_seconds:
        return False, "PACKET_STALE", age
    return True, "FRESH", age


def validate_holdings_packet(packet: Mapping[str, Any] | None, *, now: datetime | None = None, ttl_seconds: int = 36*3600, expected_session: str | None = None) -> tuple[bool, str]:
    if not packet:
        return False, "PACKET_MISSING"
    if packet.get("packet_version") != "holdings_reunderwrite.v1":
        return False, "SCHEMA_INVALID"
    if not isinstance(packet.get("positions"), list):
        return False, "SCHEMA_INVALID"
    if expected_session and packet.get("run_date") != expected_session:
        return False, "SESSION_MISMATCH"
    if packet.get("packet_digest") and not verify_digest(packet):
        return False, "DIGEST_INVALID"
    if not packet.get("packet_digest") and not packet.get("input_digest"):
        return False, "DIGEST_INVALID"
    ok, reason, _age = validate_freshness(packet, now=now, ttl_seconds=ttl_seconds, timestamp_keys=("created_at", "generated_at"))
    return (ok, reason if not ok else "FRESH")


def preserve_strong_action(raw_action: str | None, proposed: str | None) -> str:
    raw = str(raw_action or "DATA INCOMPLETE").upper()
    final = str(proposed or raw).upper()
    if raw in ACTION_PRIORITY and final in ACTION_PRIORITY:
        return raw if ACTION_PRIORITY[raw] < ACTION_PRIORITY[final] else final
    return raw if raw in ACTION_PRIORITY else final


def normalize_raw_tfe(value: Any) -> str:
    text = str(value or "UNKNOWN").strip().upper().replace("_", " ")
    if "AVOID" in text:
        return "AVOID"
    if "BUY" in text and "SMALL" in text:
        return "BUY Small"
    if "BUY" in text:
        return "BUY"
    if "WATCH" in text:
        return "WATCH"
    return str(value or "UNKNOWN")
