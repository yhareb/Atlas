#!/usr/bin/env python3
"""Perme Engine Packet v1 parser/renderer.
Annotation-only: no DB, no network, no Telegram, no trade instructions.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "perme_engine_packet_v1"
REQUIRED_FIELDS = {
    "schema", "generated_at_et", "ttl_minutes", "severity", "confidence", "scope",
    "sector", "tickers", "event_type", "direction", "evidence_count", "reason_code",
    "allowed_actions", "forbidden_actions",
}
ALLOWED_ACTIONS = {"ANNOTATE", "REVIEW_NOW"}
FORBIDDEN_ACTIONS = {"BUY", "SELL", "CHANGE_STOP", "CHANGE_TARGET"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
DIRECTIONS = {"RISK_OFF", "RISK_ON", "NEUTRAL", "MIXED", "UNKNOWN"}

@dataclass(frozen=True)
class PacketResult:
    ok: bool
    packet: dict | None = None
    error: str = ""


def _parse_et(value: str) -> datetime:
    text = str(value or "").strip()
    dt = datetime.fromisoformat(text)
    et = ZoneInfo("America/New_York")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=et)
    return dt.astimezone(et)


def validate_packet(payload: dict, now_et: datetime | None = None) -> PacketResult:
    if not isinstance(payload, dict):
        return PacketResult(False, error="not_object")
    extra = set(payload) - REQUIRED_FIELDS
    missing = REQUIRED_FIELDS - set(payload)
    if extra or missing:
        return PacketResult(False, error="schema_fields")
    if payload.get("schema") != SCHEMA:
        return PacketResult(False, error="schema_name")
    try:
        generated = _parse_et(payload.get("generated_at_et"))
        ttl = int(payload.get("ttl_minutes"))
    except Exception:
        return PacketResult(False, error="time_parse")
    if ttl <= 0:
        return PacketResult(False, error="ttl_invalid")
    now = now_et or datetime.now(ZoneInfo("America/New_York"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("America/New_York"))
    now = now.astimezone(ZoneInfo("America/New_York"))
    if generated + timedelta(minutes=ttl) < now:
        return PacketResult(False, error="stale")
    severity = str(payload.get("severity") or "").upper()
    if severity not in SEVERITIES:
        return PacketResult(False, error="severity")
    try:
        confidence = float(payload.get("confidence"))
    except Exception:
        return PacketResult(False, error="confidence")
    if confidence < 0 or confidence > 1:
        return PacketResult(False, error="confidence")
    tickers = payload.get("tickers")
    allowed = payload.get("allowed_actions")
    forbidden = payload.get("forbidden_actions")
    if not isinstance(tickers, list) or any(not isinstance(t, str) for t in tickers):
        return PacketResult(False, error="tickers")
    if not isinstance(allowed, list) or not allowed:
        return PacketResult(False, error="prose_only")
    allowed_set = {str(a or "").upper() for a in allowed}
    if not allowed_set <= ALLOWED_ACTIONS:
        return PacketResult(False, error="forbidden_action")
    if allowed_set & FORBIDDEN_ACTIONS:
        return PacketResult(False, error="forbidden_action")
    if not isinstance(forbidden, list):
        return PacketResult(False, error="forbidden_actions_field")
    forbidden_set = {str(a or "").upper() for a in forbidden}
    if not FORBIDDEN_ACTIONS <= forbidden_set:
        return PacketResult(False, error="forbidden_actions_field")
    if str(payload.get("direction") or "").upper() not in DIRECTIONS:
        return PacketResult(False, error="direction")
    try:
        evidence_count = int(payload.get("evidence_count"))
    except Exception:
        return PacketResult(False, error="evidence_count")
    if evidence_count < 1:
        return PacketResult(False, error="prose_only")
    cleaned = dict(payload)
    cleaned["severity"] = severity
    cleaned["direction"] = str(payload.get("direction") or "").upper()
    cleaned["tickers"] = [str(t).upper() for t in tickers if str(t).strip()]
    cleaned["allowed_actions"] = sorted(allowed_set)
    cleaned["forbidden_actions"] = sorted(forbidden_set)
    return PacketResult(True, packet=cleaned)


def load_valid_packets(path: str | Path, now_et: datetime | None = None) -> tuple[list[dict], list[str]]:
    packets, errors = [], []
    p = Path(path)
    if not p.exists():
        return [], ["missing"]
    for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            errors.append(f"{idx}:json")
            continue
        result = validate_packet(payload, now_et=now_et)
        if result.ok:
            packets.append(result.packet or {})
        else:
            errors.append(f"{idx}:{result.error}")
    return packets, errors


def _summary_holding_tickers(summary: dict) -> set[str]:
    out = set()
    for row in (summary or {}).get("exit_results", []) or []:
        ticker = str((row or {}).get("ticker") or "").upper()
        if ticker:
            out.add(ticker)
    for row in (summary or {}).get("open_positions", []) or []:
        ticker = str((row or {}).get("ticker") or "").upper()
        if ticker:
            out.add(ticker)
    return out


def _summary_holding_sectors(summary: dict) -> set[str]:
    out = set()
    for row in (summary or {}).get("exit_results", []) or []:
        sector = str((row or {}).get("sector") or "").upper()
        if sector:
            out.add(sector)
    return out


def render_report_annotations(packets: list[dict], summary: dict | None = None) -> list[str]:
    """Report/annotation-only rendering. Never alters signal, score, entry, stop,
    target, exit, sizing, or risk — this only changes the *label text* shown in the
    report for HIGH-severity packets that overlap current open holdings.

    Exposure confidence:
      - Direct ticker match (packet ticker == open holding ticker) => "Confirmed exposure".
      - Sector/theme-only match (packet sector == open holding sector, no ticker overlap)
        => "Possible exposure" (sector mapping is heuristic/uncertain, so we do not claim
        confirmation from a sector match alone).
    """
    summary = summary if isinstance(summary, dict) else {}
    holdings = _summary_holding_tickers(summary)
    sectors = _summary_holding_sectors(summary)
    lines = []
    for pkt in packets or []:
        tickers = {str(t).upper() for t in pkt.get("tickers") or []}
        sector = str(pkt.get("sector") or "").upper()
        severity = str(pkt.get("severity") or "").upper()
        ticker_match = tickers & holdings
        sector_match = bool(sector) and sector in sectors and not ticker_match
        action = "ANNOTATE"
        exposure = ""
        if severity == "HIGH" and ticker_match:
            action = "REVIEW NOW"
            exposure = "Confirmed exposure"
        elif severity == "HIGH" and sector_match:
            action = "REVIEW NOW"
            exposure = "Possible exposure"
        scope = str(pkt.get("scope") or "MARKET").upper()
        reason = str(pkt.get("reason_code") or pkt.get("event_type") or "PERME_PACKET")
        target = ",".join(sorted(ticker_match or tickers)) or sector or scope
        if exposure:
            lines.append(f"⚠️ Perme Engine Packet: {action} ({exposure}) · {severity} · {target} · {reason}")
        else:
            lines.append(f"⚠️ Perme Engine Packet: {action} · {severity} · {target} · {reason}")
    return lines
