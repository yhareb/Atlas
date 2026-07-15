#!/usr/bin/env python3
"""Authoritative Quiver bounded REVIEW overlay envelope for Atlas consumers.

Deterministic, non-mutating, observation-only. All consumers call
apply_quiver_review_overlay(raw_tfe_result, quiver_context) instead of
interpreting the packet independently.
"""
from __future__ import annotations
import json, os, sqlite3, hashlib
from pathlib import Path
from typing import Any

AUTHORITY = "REVIEW_OVERLAY_ONLY"
VALID_POSTURES = {"SUPPORTIVE", "CAUTION", "MIXED", "NO_USABLE_DATA", "DATA_UNAVAILABLE"}
DEFAULT_DECISION_SIDECAR = "/Users/yasser/Library/Application Support/Atlas/quiver_shadow/db/quiver_decision_envelopes.sqlite"
DEFAULT_PACKET_PATH = "/Users/yasser/atlas_inbox/quiver_engine_packet_v1.json"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS quiver_decision_envelopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    source_run_id TEXT,
    packet_digest TEXT,
    ticker TEXT NOT NULL,
    raw_tfe_classification TEXT NOT NULL,
    raw_tfe_score TEXT,
    raw_pillars_json TEXT,
    raw_entry TEXT,
    raw_stop TEXT,
    raw_target TEXT,
    raw_size TEXT,
    quiver_posture TEXT NOT NULL,
    quiver_reason_codes_json TEXT NOT NULL,
    quiver_freshness TEXT,
    quiver_review_flag INTEGER NOT NULL,
    final_advisory_action TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    envelope_digest TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_quiver_decision_envelopes_ticker_created
ON quiver_decision_envelopes(ticker, created_at);
"""

def _norm_ticker(v: Any) -> str:
    return str(v or "").strip().upper()

def _classify(raw: dict[str, Any]) -> str:
    val = raw.get("raw_tfe_classification") or raw.get("tfe_classification") or raw.get("signal") or raw.get("classification") or raw.get("action") or "UNKNOWN"
    text = str(val or "UNKNOWN").strip().upper().replace("_", " ")
    if "BUY SMALL" in text:
        return "BUY Small"
    if "BUY" in text and "AVOID" not in text:
        return "BUY"
    if "AVOID" in text:
        return "AVOID"
    if "WAIT" in text:
        return "WAIT"
    return str(val or "UNKNOWN").strip() or "UNKNOWN"

def _is_buy_family(v: Any) -> bool:
    t = str(v or "").strip().upper().replace("_", " ")
    return "BUY" in t and "AVOID" not in t

def _plain_reason(ctx: dict[str, Any]) -> str:
    posture = str(ctx.get("quiver_posture") or ctx.get("quiver_view") or "DATA_UNAVAILABLE").upper()
    if posture == "DATA_UNAVAILABLE":
        return "QUIVER DATA UNAVAILABLE"
    if posture == "NO_USABLE_DATA":
        return "No usable public Quiver evidence."
    explicit = ctx.get("plain_english") or ctx.get("quiver_evidence") or ctx.get("evidence_summary")
    if explicit:
        return str(explicit)
    evs = ctx.get("contributing_public_evidence") or ctx.get("evidence") or []
    parts = []
    for ev in evs[:3]:
        if not isinstance(ev, dict):
            continue
        ds = str(ev.get("dataset") or "public Quiver").replace("_", " ")
        when = str(ev.get("public_availability_date") or ev.get("filing_date") or ev.get("date") or "date unavailable")[:10]
        tone = ev.get("tone") or ev.get("direction") or posture.lower()
        parts.append(f"{ds} {tone} evidence public {when}")
    if parts:
        return "; ".join(parts)
    if posture == "CAUTION":
        return "Recent public Quiver evidence requires review before action."
    if posture == "MIXED":
        return "Mixed public Quiver evidence creates a bounded review flag."
    if posture == "SUPPORTIVE":
        return "Supportive public Quiver evidence; confirms only."
    return "No usable public Quiver evidence."

def _reason_codes(ctx: dict[str, Any]) -> list[str]:
    vals = ctx.get("quiver_reason_codes") or ctx.get("reason_codes") or []
    if isinstance(vals, str):
        vals = [vals]
    if not vals:
        vals = [str(ctx.get("quiver_posture") or ctx.get("quiver_view") or "DATA_UNAVAILABLE")]
    return [str(v) for v in vals]

def load_packet_read_only(path: str | os.PathLike[str] = DEFAULT_PACKET_PATH) -> tuple[dict[str, Any] | None, str]:
    p = Path(path)
    if not p.exists():
        return None, "missing"
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace")), "ok"
    except Exception as exc:
        return None, f"json:{type(exc).__name__}"

def open_sidecar_read_only(path: str | os.PathLike[str]) -> sqlite3.Connection:
    uri = "file:" + str(Path(path).resolve()) + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn

def context_from_packet(ticker: str, packet: dict[str, Any] | None) -> dict[str, Any]:
    t = _norm_ticker(ticker)
    if not packet or packet.get("freshness_state") != "FRESH" or (packet.get("source_health") or {}).get("status") != "PASS":
        return {"ticker": t, "quiver_posture": "DATA_UNAVAILABLE", "quiver_reason_codes": ["packet_missing_stale_or_unhealthy"], "quiver_freshness": (packet or {}).get("freshness_state") if packet else None, "packet_digest": (packet or {}).get("packet_digest"), "source_run_id": (packet or {}).get("source_run_id")}
    ctx = (packet.get("ticker_contexts") or {}).get(t)
    if not ctx:
        return {"ticker": t, "quiver_posture": "NO_USABLE_DATA", "quiver_reason_codes": ["no_ticker_context"], "quiver_freshness": packet.get("freshness_state"), "packet_digest": packet.get("packet_digest"), "source_run_id": packet.get("source_run_id")}
    out = dict(ctx)
    out["ticker"] = t
    out["quiver_posture"] = str(out.get("quiver_posture") or out.get("quiver_view") or "NO_USABLE_DATA").upper()
    out["quiver_reason_codes"] = _reason_codes(out)
    out["quiver_freshness"] = packet.get("freshness_state")
    out["packet_digest"] = packet.get("packet_digest")
    out["source_run_id"] = packet.get("source_run_id")
    return out

def apply_quiver_review_overlay(raw_tfe_result: dict[str, Any], quiver_context: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw_tfe_result or {})
    ctx = dict(quiver_context or {})
    ticker = _norm_ticker(raw.get("ticker") or ctx.get("ticker"))
    raw_class = _classify(raw)
    posture = str(ctx.get("quiver_posture") or ctx.get("quiver_view") or "DATA_UNAVAILABLE").upper()
    if posture not in VALID_POSTURES:
        posture = "DATA_UNAVAILABLE"
    final = raw_class
    review = False
    why = "Raw TFE remains unchanged; Quiver has no bounded effect."
    if _is_buy_family(raw_class) and posture == "CAUTION":
        final = "WAIT / REVIEW"
        review = True
        why = "Raw TFE BUY remains valid, but recent public Quiver evidence requires review before action."
    elif _is_buy_family(raw_class) and posture == "MIXED":
        final = "REVIEW"
        review = True
        why = "Raw TFE BUY remains valid, but mixed public Quiver evidence creates a bounded review flag."
    elif _is_buy_family(raw_class) and posture == "SUPPORTIVE":
        final = raw_class
        why = "Quiver confirms only; no score, sizing, entry, stop, or target increase."
    elif "AVOID" in str(raw_class).upper():
        final = raw_class
        why = "Supportive Quiver evidence cannot override raw TFE AVOID."
    elif posture in {"NO_USABLE_DATA", "DATA_UNAVAILABLE"}:
        final = raw_class
        why = "No usable/fresh Quiver data; final action equals raw TFE action."
    env = {
        "ticker": ticker,
        "raw_tfe_classification": raw_class,
        "raw_tfe_score": raw.get("score") or raw.get("raw_tfe_score"),
        "raw_pillars": raw.get("pillars") if raw.get("pillars") is not None else raw.get("raw_pillars"),
        "raw_entry": raw.get("entry"),
        "raw_stop": raw.get("stop"),
        "raw_target": raw.get("target"),
        "raw_size": raw.get("size") if raw.get("size") is not None else raw.get("shares"),
        "quiver_posture": posture,
        "quiver_reason_codes": _reason_codes(ctx),
        "quiver_freshness": ctx.get("quiver_freshness") or ctx.get("freshness_state"),
        "quiver_review_flag": bool(review),
        "final_advisory_action": final,
        "quiver_evidence": _plain_reason(ctx),
        "public_filing_dates": ctx.get("public_filing_dates") or [ev.get("public_availability_date") for ev in (ctx.get("contributing_public_evidence") or []) if isinstance(ev, dict) and ev.get("public_availability_date")],
        "missing_or_empty_datasets": ctx.get("missing_or_empty_datasets") or ctx.get("endpoint_completeness") or {},
        "why": why,
        "authority": AUTHORITY,
        "mutation_guards": {"classification": "PRESERVED", "score": "PRESERVED", "pillars": "PRESERVED", "entry": "PRESERVED", "stop": "PRESERVED", "target": "PRESERVED", "size": "PRESERVED", "status": "PRESERVED", "broker": "NO_AUTHORITY"},
        "source_run_id": ctx.get("source_run_id"),
        "packet_digest": ctx.get("packet_digest"),
    }
    canonical = json.dumps(env, sort_keys=True, separators=(",", ":"), default=str)
    env["envelope_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
    return env

def is_actionable_buy(envelope: dict[str, Any]) -> bool:
    return _is_buy_family(envelope.get("final_advisory_action")) and not envelope.get("quiver_review_flag")

def render_decision_block(envelope: dict[str, Any]) -> str:
    if envelope.get("quiver_posture") == "NO_USABLE_DATA":
        return f"QUIVER CONTEXT: NO USABLE DATA — final action remains {envelope.get('raw_tfe_classification')}"
    if envelope.get("quiver_posture") == "DATA_UNAVAILABLE":
        return "QUIVER DATA UNAVAILABLE"
    return "\n".join([
        f"TFE CLASSIFICATION: {envelope.get('raw_tfe_classification')}",
        f"ACTION NOW: {envelope.get('final_advisory_action')}",
        f"QUIVER CONTEXT: {envelope.get('quiver_posture')}",
        f"QUIVER EVIDENCE: {envelope.get('quiver_evidence')}",
        f"WHY: {envelope.get('why')}",
    ])

def open_decision_sidecar(path: str | os.PathLike[str] = DEFAULT_DECISION_SIDECAR) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.executescript(SCHEMA_SQL)
    return conn

def persist_decision_envelope(envelope: dict[str, Any], path: str | os.PathLike[str] = DEFAULT_DECISION_SIDECAR) -> str:
    conn = open_decision_sidecar(path)
    try:
        payload = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
        conn.execute("""INSERT OR IGNORE INTO quiver_decision_envelopes
        (source_run_id, packet_digest, ticker, raw_tfe_classification, raw_tfe_score, raw_pillars_json,
         raw_entry, raw_stop, raw_target, raw_size, quiver_posture, quiver_reason_codes_json,
         quiver_freshness, quiver_review_flag, final_advisory_action, envelope_json, envelope_digest)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            envelope.get("source_run_id"), envelope.get("packet_digest"), envelope.get("ticker"),
            envelope.get("raw_tfe_classification"), str(envelope.get("raw_tfe_score")),
            json.dumps(envelope.get("raw_pillars"), sort_keys=True, default=str),
            str(envelope.get("raw_entry")), str(envelope.get("raw_stop")), str(envelope.get("raw_target")), str(envelope.get("raw_size")),
            envelope.get("quiver_posture"), json.dumps(envelope.get("quiver_reason_codes") or [], sort_keys=True),
            envelope.get("quiver_freshness"), 1 if envelope.get("quiver_review_flag") else 0,
            envelope.get("final_advisory_action"), payload, envelope.get("envelope_digest")
        ))
        conn.commit()
    finally:
        conn.close()
    return str(envelope.get("envelope_digest"))

def load_latest_envelope(ticker: str, path: str | os.PathLike[str] = DEFAULT_DECISION_SIDECAR) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT envelope_json FROM quiver_decision_envelopes WHERE ticker=? ORDER BY id DESC LIMIT 1", (_norm_ticker(ticker),)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def enrich_many(raw_results: list[dict[str, Any]], packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [apply_quiver_review_overlay(r, context_from_packet(str(r.get("ticker") or ""), packet)) for r in raw_results]
