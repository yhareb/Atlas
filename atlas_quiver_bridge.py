#!/usr/bin/env python3
"""Quiver bridge helpers for Atlas/Fat Engine presentation paths.

Mirrors Perme engine packet authority: annotation-only. No DB writes, no broker,
no score/entry/stop/target/sizing mutation.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from atlas_quiver_engine_packet import validate_packet

DEFAULT_PACKET = "/Users/yasser/atlas_inbox/quiver_engine_packet_v1.json"
VALID_VIEWS = {"SUPPORTIVE", "CAUTION", "MIXED", "NO_USABLE_DATA", "DATA_UNAVAILABLE"}


def load_packet(path: str | Path = DEFAULT_PACKET) -> tuple[dict[str, Any] | None, str]:
    p = Path(path)
    if not p.exists():
        return None, "missing"
    try:
        payload = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return None, f"json:{type(exc).__name__}"
    ok, reason = validate_packet(payload)
    if not ok:
        return None, reason
    if payload.get("freshness_state") != "FRESH" or (payload.get("source_health") or {}).get("status") != "PASS":
        return payload, "stale_or_unhealthy"
    return payload, "ok"


def context_for_ticker(ticker: str, packet: dict[str, Any] | None) -> dict[str, Any]:
    t = str(ticker or "").upper().strip()
    if not packet:
        return {"ticker": t, "quiver_view": "DATA_UNAVAILABLE", "reason_codes": ["packet_missing_or_invalid"], "source_health": "DATA_UNAVAILABLE"}
    packet_health = (packet.get("source_health") or {}).get("status")
    if packet.get("freshness_state") != "FRESH" or packet_health != "PASS":
        return {"ticker": t, "quiver_view": "DATA_UNAVAILABLE", "reason_codes": ["packet_stale_or_unhealthy"], "source_health": packet_health or "DATA_UNAVAILABLE"}
    ctx = ((packet.get("ticker_contexts") or {}).get(t))
    if not ctx:
        return {"ticker": t, "quiver_view": "NO_USABLE_DATA", "reason_codes": ["no_ticker_context"], "source_health": (packet.get("source_health") or {}).get("status")}
    reasons = []
    for ev in ctx.get("contributing_public_evidence") or []:
        reasons.append(f"{ev.get('dataset')}:{ev.get('public_availability_date')}")
    for ev in (ctx.get("excluded_evidence") or [])[:4]:
        reasons.append(f"excluded:{ev.get('dataset')}:{ev.get('reason')}")
    out = dict(ctx)
    out["reason_codes"] = reasons or ["no_usable_public_evidence"]
    out["source_health"] = (packet.get("source_health") or {}).get("status")
    return out


def plain_reason(ctx: dict[str, Any]) -> str:
    view = ctx.get("quiver_view") or "DATA_UNAVAILABLE"
    if view == "DATA_UNAVAILABLE":
        return "Quiver data unavailable; Atlas continues without Quiver influence."
    if view == "NO_USABLE_DATA":
        return "No usable public Quiver evidence for this ticker."
    parts = []
    for ev in ctx.get("contributing_public_evidence") or []:
        ds = str(ev.get("dataset") or "dataset").replace("_", " ")
        when = ev.get("public_availability_date") or "date unavailable"
        parts.append(f"{ds} evidence public as of {str(when)[:10]}")
    if ctx.get("conflict_penalty"):
        parts.append("conflicting public datasets present")
    return "; ".join(parts[:3]) if parts else "No usable public Quiver evidence for this ticker."


def _is_buy_family(value: Any) -> bool:
    text = str(value or "").upper()
    return "BUY" in text and "AVOID" not in text


def apply_to_decision(raw_decision: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Bounded REVIEW overlay. Raw TFE fields are preserved; no trading values mutate."""
    raw = dict(raw_decision or {})
    raw_signal = raw.get("signal") or raw.get("classification") or raw.get("action") or "UNKNOWN"
    view = ctx.get("quiver_view") or "DATA_UNAVAILABLE"
    final = raw_signal
    why = "TFE remains the authority; Quiver is not material or unavailable."
    review_flag = False
    if _is_buy_family(raw_signal) and view == "CAUTION":
        final = "WAIT / REVIEW"
        review_flag = True
        why = "TFE remains valid, but Quiver adds a bounded caution review flag."
    elif _is_buy_family(raw_signal) and view == "MIXED":
        final = "REVIEW"
        review_flag = True
        why = "TFE remains valid, but Quiver has conflicting public evidence."
    elif _is_buy_family(raw_signal) and view == "SUPPORTIVE":
        final = raw_signal
        why = "Quiver confirms only; no score or sizing increase."
    elif "AVOID" in str(raw_signal).upper():
        final = raw_signal
        why = "Raw AVOID cannot be promoted by Quiver."
    return {
        "ticker": str(raw.get("ticker") or ctx.get("ticker") or "").upper(),
        "tfe_classification": raw_signal,
        "raw_tfe": raw,
        "quiver_context": view,
        "quiver_evidence": plain_reason(ctx),
        "final_action": final,
        "why": why,
        "review_flag": review_flag,
        "authority": "REVIEW_OVERLAY_ONLY",
        "mutations": {"entry": "UNCHANGED", "stop": "UNCHANGED", "target": "UNCHANGED", "size": "UNCHANGED", "tfe_score": "UNCHANGED", "pillars": "UNCHANGED", "status": "UNCHANGED", "cash": "UNCHANGED"},
    }


def decision_presentation(raw_decision: dict[str, Any], ctx: dict[str, Any]) -> str:
    applied = apply_to_decision(raw_decision, ctx)
    return "\n".join([
        f"TFE CLASSIFICATION: {applied['tfe_classification']}",
        f"QUIVER CONTEXT: {applied['quiver_context']}",
        f"QUIVER EVIDENCE: {applied['quiver_evidence']}",
        f"FINAL ADVISORY ACTION: {applied['final_action']}",
        f"WHY: {applied['why']}",
    ])


def conversational_ticker_answer(ticker: str, raw_decision: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    ctx = context_for_ticker(ticker, packet)
    applied = apply_to_decision(raw_decision, ctx)
    missing = []
    for dataset, state in (ctx.get("endpoint_completeness") or {}).items():
        if state not in {"ENTITLED", "EMPTY_RESPONSE"}:
            missing.append({"dataset": dataset, "state": state})
    return {
        "ticker": str(ticker).upper(),
        "tfe_classification": applied["tfe_classification"],
        "quiver_posture": applied["quiver_context"],
        "available_evidence": ctx.get("contributing_public_evidence") or [],
        "evidence_freshness": ctx.get("age_days") or [],
        "missing_datasets": missing,
        "final_bounded_interpretation": applied["final_action"],
        "packet_status": ctx.get("source_health"),
    }


def join_contexts(decisions: list[dict[str, Any]], packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [apply_to_decision(d, context_for_ticker(str(d.get("ticker") or ""), packet)) for d in decisions]


# Search-engine closure v1: delegate bounded authority to the single decision-envelope module.
try:
    from atlas_quiver_decision_envelope import (
        apply_quiver_review_overlay,
        render_decision_block,
        context_from_packet,
        persist_decision_envelope,
        is_actionable_buy,
    )
except Exception:
    apply_quiver_review_overlay = None
    render_decision_block = None
    context_from_packet = None
    persist_decision_envelope = None
    is_actionable_buy = None
