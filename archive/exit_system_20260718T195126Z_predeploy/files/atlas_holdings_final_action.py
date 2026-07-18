#!/usr/bin/env python3
"""Shared Atlas holdings final-action merger.

Advisory/report-only.  Does not modify atlas.db, broker state, Profit Protection,
Daily Holdings Re-Underwriting, stops, targets, TFE scores, or Telegram routing.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PACKET_VERSION = "holdings_merged_action.v1"
DEFAULT_HOLDINGS_PACKET = "/Users/yasser/atlas_inbox/holdings_reunderwrite/latest/holdings_reunderwrite_packet_v1.json"
DEFAULT_MERGED_PACKET = "/Users/yasser/atlas_inbox/holdings_reunderwrite/latest/holdings_merged_action_packet_v1.json"
DAILY_PACKET_VERSION = "holdings_reunderwrite.v1"
ACTION_PRECEDENCE = {
    "SELL NOW": 0,
    "EXIT REVIEW": 1,
    "TRIM REVIEW": 2,
    "STOP BREACHED / URGENT STOP REVIEW": 3,
    "URGENT STOP REVIEW": 3,
    "STOP BREACHED": 3,
    "HOLD TIGHT": 4,
    "HOLD": 5,
    "DATA INCOMPLETE": 6,
}
CANONICAL_ACTION = {
    "SELL": "SELL NOW",
    "SELL NOW": "SELL NOW",
    "EXIT": "EXIT REVIEW",
    "EXIT REVIEW": "EXIT REVIEW",
    "TRIM": "TRIM REVIEW",
    "TRIM REVIEW": "TRIM REVIEW",
    "STOP BREACHED": "STOP BREACHED / URGENT STOP REVIEW",
    "URGENT STOP REVIEW": "STOP BREACHED / URGENT STOP REVIEW",
    "STOP BREACHED / URGENT STOP REVIEW": "STOP BREACHED / URGENT STOP REVIEW",
    "HOLD TIGHT": "HOLD TIGHT",
    "WATCH CLOSELY": "HOLD TIGHT",
    "HOLD": "HOLD",
    "DATA INCOMPLETE": "DATA INCOMPLETE",
    "MISSING": "DATA INCOMPLETE",
    "STALE": "DATA INCOMPLETE",
}


def _utcnow() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sha_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def normalize_action(action: Any) -> str:
    text = str(action or "DATA INCOMPLETE").strip().upper().replace("_", " ")
    return CANONICAL_ACTION.get(text, text if text in ACTION_PRECEDENCE else "DATA INCOMPLETE")


def strongest_action(*actions: Any) -> str:
    vals = [normalize_action(a) for a in actions]
    vals = [v for v in vals if v in ACTION_PRECEDENCE]
    if not vals:
        return "DATA INCOMPLETE"
    return min(vals, key=lambda a: ACTION_PRECEDENCE[a])


def parse_dt(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = dt.datetime.fromisoformat(text if "T" in text else text.replace(" ", "T"))
        if out.tzinfo is None:
            out = out.replace(tzinfo=dt.timezone.utc)
        return out.astimezone(dt.timezone.utc)
    except Exception:
        return None


def validate_daily_packet(packet: Mapping[str, Any] | None, *, now: dt.datetime | None = None, ttl_seconds: int = 36 * 3600, expected_session: str | None = None) -> tuple[bool, str]:
    if not packet:
        return False, "PACKET_MISSING"
    if packet.get("packet_version") != DAILY_PACKET_VERSION:
        return False, "SCHEMA_INVALID"
    if not isinstance(packet.get("positions"), list):
        return False, "SCHEMA_INVALID"
    if expected_session and packet.get("run_date") != expected_session:
        return False, "SESSION_MISMATCH"
    if not (packet.get("packet_digest") or packet.get("input_digest")):
        return False, "DIGEST_MISSING"
    ts = parse_dt(packet.get("created_at") or packet.get("generated_at"))
    if not ts:
        return False, "TIMESTAMP_INVALID"
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if (now - ts).total_seconds() > ttl_seconds:
        return False, "PACKET_STALE"
    return True, "FRESH"


def load_json(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def load_latest_daily_packet(path: str | Path = DEFAULT_HOLDINGS_PACKET) -> dict[str, Any] | None:
    return load_json(path)


def _pp_action_for(ticker: str, profit_protection: Any) -> tuple[str, str, dict[str, Any]]:
    if profit_protection is None:
        return "HOLD", "MISSING", {}
    if isinstance(profit_protection, Mapping):
        freshness = str(profit_protection.get("freshness") or profit_protection.get("status") or "FRESH").upper()
        if freshness in {"STALE", "TIMESTAMP_INVALID", "MISSING", "INVALID"}:
            return "HOLD", freshness, dict(profit_protection)
        if any(k in profit_protection for k in ("action", "profit_protection_action", "recommended_action")):
            return normalize_action(profit_protection.get("action") or profit_protection.get("profit_protection_action") or profit_protection.get("recommended_action") or "HOLD"), freshness, dict(profit_protection)
        row = (profit_protection.get("positions") or profit_protection.get("results") or profit_protection.get("by_ticker") or {})
        item = None
        if isinstance(row, Mapping):
            item = row.get(ticker) or row.get(ticker.upper())
        elif isinstance(row, list):
            item = next((x for x in row if str((x or {}).get("ticker") or "").upper() == ticker.upper()), None)
        if isinstance(item, Mapping):
            return normalize_action(item.get("action") or item.get("profit_protection_action") or item.get("recommended_action") or "HOLD"), freshness, dict(item)
        return "HOLD", freshness, {}
    return normalize_action(profit_protection), "FRESH", {}


def stop_action(stop_status: Any) -> str:
    text = str(stop_status or "").upper()
    if "BREACH" in text or "BELOW STOP" in text or text in {"TRUE", "1"}:
        return "STOP BREACHED / URGENT STOP REVIEW"
    return "HOLD"


def broker_status_label(value: Any) -> str:
    text = str(value or "NOT CONFIRMED").strip().upper()
    if text in {"", "NONE", "MISSING"}:
        return "NOT CONFIRMED"
    return text


def merge_position(daily_position: Mapping[str, Any], *, daily_valid: bool, daily_freshness: str, profit_protection: Any = None, stop_status: Any = None, broker_status: Any = None, stop_invariant_guard: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ticker = str(daily_position.get("ticker") or "").upper()
    guard = dict(stop_invariant_guard or {})
    if guard and guard.get("result") != "PASS":
        codes = sorted(set(list(daily_position.get("reason_codes") or []) + list(guard.get("reason_codes") or [])))
        return {
            "ticker": ticker, "trade_id": daily_position.get("trade_id") or guard.get("trade_id"),
            "daily_action": "DATA INCOMPLETE", "profit_protection_action": "DATA INCOMPLETE",
            "profit_protection_freshness": "NOT_EVALUATED_GUARD_VETO",
            "stop_status": "UNKNOWN — STOP INVARIANT UNVERIFIED",
            "broker_status": broker_status_label(broker_status), "final_action": "DATA INCOMPLETE",
            "final_reason_codes": codes, "daily_reason_codes": list(daily_position.get("reason_codes") or []),
            "source_timestamps": {"daily_packet_position_as_of": daily_position.get("as_of")},
            "freshness_states": {"daily_packet": daily_freshness, "profit_protection": "NOT_EVALUATED_GUARD_VETO"},
            "recheck_condition": "Resolve stop invariant evidence: " + ", ".join(codes),
            "stop_invariant_guard": guard,
            "input_digest": sha_json({"daily": daily_position, "stop_invariant_guard": guard}),
        }
    if not daily_valid:
        daily_action = "DATA INCOMPLETE"
        final_action = "DATA INCOMPLETE"
        reason_codes = [daily_freshness]
    else:
        daily_action = normalize_action(daily_position.get("action"))
        pp_action, pp_freshness, pp_source = _pp_action_for(ticker, profit_protection)
        st_action = stop_action(stop_status)
        final_action = strongest_action(daily_action, pp_action, st_action)
        reason_codes = list(daily_position.get("reason_codes") or [])
        if pp_action != "HOLD":
            reason_codes.append("PROFIT_PROTECTION_" + pp_action.replace(" ", "_"))
        if st_action != "HOLD":
            reason_codes.append("STOP_BREACH_VISIBLE_SEPARATE_FROM_BROKER")
        return {
            "ticker": ticker,
            "trade_id": daily_position.get("trade_id"),
            "daily_action": daily_action,
            "profit_protection_action": pp_action,
            "profit_protection_freshness": pp_freshness,
            "stop_status": str(stop_status or "NOT BREACHED"),
            "broker_status": broker_status_label(broker_status),
            "final_action": final_action,
            "final_reason_codes": reason_codes,
            "daily_reason_codes": list(daily_position.get("reason_codes") or []),
            "source_timestamps": {"daily_packet_position_as_of": daily_position.get("as_of")},
            "freshness_states": {"daily_packet": daily_freshness, "profit_protection": pp_freshness},
            "recheck_condition": daily_position.get("recheck_condition"),
            "input_digest": sha_json({"daily": daily_position, "pp": pp_source, "stop": stop_status, "broker": broker_status}),
        }
    return {
        "ticker": ticker,
        "trade_id": daily_position.get("trade_id"),
        "daily_action": daily_action,
        "profit_protection_action": "DATA INCOMPLETE",
        "profit_protection_freshness": "NOT_EVALUATED_DAILY_INVALID",
        "stop_status": str(stop_status or "UNKNOWN"),
        "broker_status": broker_status_label(broker_status),
        "final_action": final_action,
        "final_reason_codes": reason_codes,
        "daily_reason_codes": list(daily_position.get("reason_codes") or []),
        "source_timestamps": {"daily_packet_position_as_of": daily_position.get("as_of")},
        "freshness_states": {"daily_packet": daily_freshness, "profit_protection": "NOT_EVALUATED_DAILY_INVALID"},
        "recheck_condition": "Daily Holdings packet must refresh before a confident holding action is shown.",
        "input_digest": sha_json({"daily_invalid": daily_position, "reason": daily_freshness}),
    }


def build_merged_packet(daily_packet: Mapping[str, Any] | None, *, profit_protection_by_ticker: Mapping[str, Any] | None = None, stop_status_by_ticker: Mapping[str, Any] | None = None, broker_status_by_ticker: Mapping[str, Any] | None = None, stop_invariant_guard: Mapping[str, Any] | None = None, now: dt.datetime | None = None, ttl_seconds: int = 36 * 3600, expected_session: str | None = None) -> dict[str, Any]:
    ok, freshness = validate_daily_packet(daily_packet, now=now, ttl_seconds=ttl_seconds, expected_session=expected_session)
    positions = []
    guards = (stop_invariant_guard or {}).get("lots") or []
    for pos in ((daily_packet or {}).get("positions") or []):
        ticker = str(pos.get("ticker") or "").upper()
        guard = next((g for g in guards if int(g.get("trade_id") or -1) == int(pos.get("trade_id") or -2)), None)
        positions.append(merge_position(pos, daily_valid=ok, daily_freshness=freshness, profit_protection=(profit_protection_by_ticker or {}).get(ticker), stop_status=(stop_status_by_ticker or {}).get(ticker), broker_status=(broker_status_by_ticker or {}).get(ticker), stop_invariant_guard=guard))
    packet = {
        "packet_version": PACKET_VERSION,
        "created_at": ((now or dt.datetime.utcnow()).replace(microsecond=0).isoformat() + ("Z" if (now or dt.datetime.utcnow()).tzinfo is None else "")),
        "daily_packet_path": DEFAULT_HOLDINGS_PACKET,
        "daily_packet_freshness": freshness,
        "daily_packet_digest": (daily_packet or {}).get("packet_digest") or (daily_packet or {}).get("input_digest"),
        "run_date": (daily_packet or {}).get("run_date"),
        "positions": positions,
        "authority": {"broker_authority": "NO", "automatic_trade_closure": "NO", "trading_authority": "ADVISORY_ONLY"},
        "precedence": ["SELL NOW", "EXIT REVIEW", "TRIM REVIEW", "STOP BREACHED / URGENT STOP REVIEW", "HOLD TIGHT", "HOLD", "DATA INCOMPLETE"],
    }
    packet["stop_invariant_guard_digest"] = (stop_invariant_guard or {}).get("digest")
    packet["input_digest"] = sha_json({"daily_packet": daily_packet, "pp": profit_protection_by_ticker, "stop": stop_status_by_ticker, "broker": broker_status_by_ticker, "stop_invariant_guard": stop_invariant_guard})
    packet["packet_digest"] = sha_json(packet)
    return packet


def packet_by_ticker(packet: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    return {str(p.get("ticker") or "").upper(): p for p in ((packet or {}).get("positions") or [])}


def render_merged_action_block(packet: Mapping[str, Any] | None, *, title: str = "━━━ 🧭 FINAL HOLDING ACTION — SHARED AUTHORITY ━━━") -> list[str]:
    positions = (packet or {}).get("positions") or []
    if not positions:
        return ["", title, "DATA INCOMPLETE — no merged holdings packet available", ""]
    groups = {a: [] for a in ["SELL NOW", "EXIT REVIEW", "TRIM REVIEW", "STOP BREACHED / URGENT STOP REVIEW", "HOLD TIGHT", "HOLD", "DATA INCOMPLETE"]}
    for p in positions:
        groups.setdefault(str(p.get("final_action") or "DATA INCOMPLETE"), []).append(p)
    lines = ["", title, ""]
    for action in groups:
        items = sorted(groups[action], key=lambda x: str(x.get("ticker") or ""))
        lines.append(action)
        if not items:
            lines.append("none")
        else:
            for p in items:
                lines.append(f"- {p.get('ticker')}: FINAL ACTION {p.get('final_action')} | DAILY RE-UNDERWRITING {p.get('daily_action')} | PROFIT PROTECTION {p.get('profit_protection_action')} | STOP STATUS {p.get('stop_status')} | BROKER CONFIRMATION {p.get('broker_status')}")
        lines.append("")
    lines.append("Authority: atlas_holdings_final_action.py; advisory only; broker_authority=NO; automatic_trade_closure=NO")
    return lines


def render_ticker_answer(ticker: str, packet: Mapping[str, Any] | None) -> tuple[str, dict[str, Any], str]:
    t = str(ticker or "").upper()
    row = packet_by_ticker(packet).get(t)
    if not row:
        struct = {"ticker": t, "error": "NO_MERGED_PACKET_POSITION", "authority": "HOLDINGS_MERGED_ACTION_PACKET"}
        return f"HOLDINGS DATA UNAVAILABLE — NO_MERGED_PACKET_POSITION", struct, "NO_MERGED_PACKET_POSITION"
    struct = {"ticker": t, **dict(row), "authority": "HOLDINGS_MERGED_ACTION_PACKET", "packet_digest": (packet or {}).get("packet_digest")}
    lines = [
        f"ATLAS HOLDINGS ANSWER — {t}",
        f"DAILY RE-UNDERWRITING: {row.get('daily_action')}",
        f"PROFIT PROTECTION: {row.get('profit_protection_action')}",
        f"STOP STATUS: {row.get('stop_status')}",
        f"BROKER CONFIRMATION: {row.get('broker_status')}",
        f"FINAL ACTION: {row.get('final_action')}",
        "WHY NOW: " + ", ".join(row.get("final_reason_codes") or []),
        f"PACKET FRESHNESS: daily={row.get('freshness_states',{}).get('daily_packet')} profit_protection={row.get('freshness_states',{}).get('profit_protection')}",
        f"PACKET DIGEST: {(packet or {}).get('packet_digest')}",
    ]
    return "\n".join(lines), struct, str(row.get("freshness_states", {}).get("daily_packet") or "UNKNOWN")


def load_or_build_merged_packet(path: str | Path | None = None, daily_path: str | Path | None = None) -> dict[str, Any] | None:
    import os
    path = path or os.environ.get('ATLAS_HOLDINGS_MERGED_PACKET_PATH') or DEFAULT_MERGED_PACKET
    daily_path = daily_path or os.environ.get('ATLAS_HOLDINGS_PACKET_PATH') or DEFAULT_HOLDINGS_PACKET
    existing = load_json(path)
    if existing:
        return existing
    daily = load_latest_daily_packet(daily_path)
    if daily:
        return build_merged_packet(daily)
    return None


__all__ = [
    "ACTION_PRECEDENCE", "DEFAULT_HOLDINGS_PACKET", "DEFAULT_MERGED_PACKET", "PACKET_VERSION",
    "build_merged_packet", "load_or_build_merged_packet", "render_merged_action_block", "render_ticker_answer",
    "strongest_action", "validate_daily_packet",
]


