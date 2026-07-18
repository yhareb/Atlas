"""Deterministic ORDER #25 two-gear packet and universal admission/sizing gate."""
from __future__ import annotations
import hashlib, json
from decimal import Decimal
from typing import Any, Mapping
SCHEMA_VERSION = "atlas_market_gear.v1"
ROUTES = frozenset({"ordinary", "pullback", "gap", "intraday", "sector", "sector-peer", "override"})

def _digest(x): return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

def build_gear_packet(*, spy_close: Any = None, spy_closes: list[Any] | None = None,
                      spy_sma50: Any = None, spy_completed_session: str | None = None,
                      perme_regime: str | None = None, perme_valid: bool = False,
                      perme_packet_digest: str | None = None, macro_event_gate: str = "CLEAR",
                      calendar_digest: str | None = None, computed_at: str | None = None) -> dict:
    if spy_sma50 is None and spy_closes is not None and len(spy_closes) >= 50:
        spy_sma50 = sum(Decimal(str(x)) for x in spy_closes[-50:]) / Decimal("50")
    spy_known = spy_close is not None and spy_sma50 is not None and bool(spy_completed_session)
    below = spy_known and Decimal(str(spy_close)) < Decimal(str(spy_sma50))
    perme = str(perme_regime or "MISSING").upper() if perme_valid else "REJECTED_OR_MISSING"
    risk_off = perme_valid and perme == "RISK_OFF"
    reasons = (["SPY_BELOW_SMA50"] if below else []) + (["PERME_RISK_OFF"] if risk_off else [])
    if reasons: gear, state = 2, "DEFENSIVE"
    elif spy_known and perme_valid: gear, state = 1, "NORMAL"
    else: gear, state = None, "DATA_INCOMPLETE"
    packet = {"schema_version": SCHEMA_VERSION, "gear": gear, "state": state, "reason_codes": reasons,
              "spy_close": None if spy_close is None else str(spy_close), "spy_sma50": None if spy_sma50 is None else str(spy_sma50),
              "spy_completed_session": spy_completed_session, "spy_source": "Massive adjusted daily aggregates",
              "perme_regime": perme, "perme_packet_digest": perme_packet_digest,
              "macro_event_gate": macro_event_gate, "calendar_digest": calendar_digest, "computed_at": computed_at,
              "new_positions_blocked": gear is None}
    packet["packet_digest"] = _digest(packet); return packet

def header_line(packet: Mapping[str, Any]) -> str:
    if packet.get("gear") == 1: return "GEAR 1 — NORMAL"
    if packet.get("gear") == 2: return "GEAR 2 — DEFENSIVE · " + " | ".join(packet.get("reason_codes") or ["DEFENSIVE"])
    return "GEAR DATA INCOMPLETE — NEW POSITIONS BLOCKED"

def gate_candidate(candidate: Mapping[str, Any], packet: Mapping[str, Any], *, route: str, base_risk_budget: Any) -> dict:
    route = route.lower()
    if route not in ROUTES: raise ValueError("unknown entry route")
    gear = packet.get("gear")
    score = candidate.get("pillars_met")
    if score is None:
        text = str(candidate.get("score") or "").split("/")[0]
        try: score = int(text)
        except ValueError: score = 0
    reasons=[]
    allowed = gear is not None
    if gear is None: reasons.append("GEAR_DATA_INCOMPLETE")
    if gear == 2 and int(score) != 4: allowed=False; reasons.append("GEAR2_REQUIRES_4_OF_4")
    if gear == 2 and str(packet.get("macro_event_gate") or "").upper() != "CLEAR": allowed=False; reasons.append("GEAR2_MACRO_EVENT_GATE")
    multiplier = Decimal("0.5") if gear == 2 else Decimal("1")
    return {"allowed": allowed, "route": route, "gear": gear, "risk_budget": str(Decimal(str(base_risk_budget))*multiplier),
            "base_risk_budget": str(base_risk_budget), "multiplier": str(multiplier), "reason_codes": reasons,
            "gear_packet_digest": packet.get("packet_digest")}

__all__=["build_gear_packet","header_line","gate_candidate","ROUTES","SCHEMA_VERSION"]
