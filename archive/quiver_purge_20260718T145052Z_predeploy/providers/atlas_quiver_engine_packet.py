#!/usr/bin/env python3
"""Quiver Engine Packet v1.

Deterministic read-only packet renderer for the Quiver observation sidecar.
Annotation-only: no DB writes, no network, no Telegram, no broker authority.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "quiver_engine_packet_v1"
CALC_VERSION = "quiver_dual_output_bridge_v1_annotation_only"
DEFAULT_SIDECAR = "/Users/yasser/Library/Application Support/Atlas/quiver_shadow/db/quiver_sidecar.sqlite"
DEFAULT_OUTBOX = "/Users/yasser/atlas_inbox"
DEFAULT_PACKET = "/Users/yasser/atlas_inbox/quiver_engine_packet_v1.json"
VALID_VIEWS = {"SUPPORTIVE", "CAUTION", "MIXED", "NO_USABLE_DATA", "DATA_UNAVAILABLE"}


def sha_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ro_conn(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def health(path: str | Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {"status": "DATA_UNAVAILABLE", "reason": "sidecar_missing"}
    con = ro_conn(path)
    try:
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        return {"status": "PASS" if quick == integrity == "ok" and not fk else "FAIL", "quick_check": quick, "integrity_check": integrity, "fk_rows": len(fk)}
    except Exception as exc:
        return {"status": "FAIL", "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        con.close()


def _load_latest_run(con: sqlite3.Connection) -> dict[str, Any]:
    row = con.execute("SELECT run_id, run_type, started_at, completed_at, status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    if not row:
        return {"run_id": None, "status": "NO_RUNS"}
    return dict(zip(["run_id", "run_type", "started_at", "completed_at", "status"], row))


def _latest_completed_session(con: sqlite3.Connection) -> str | None:
    row = con.execute("SELECT max(availability_ts) FROM evidence_events WHERE availability_ts IS NOT NULL").fetchone()
    if row and row[0]:
        return str(row[0])[:10]
    row = con.execute("SELECT max(signal_timestamp) FROM candidates").fetchone()
    return str(row[0])[:10] if row and row[0] else None


def _endpoint_status(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute("SELECT dataset, classification, http_status, max(checked_at) FROM endpoint_entitlements GROUP BY dataset, classification, http_status ORDER BY dataset").fetchall()
    out = []
    for dataset, classification, status, checked_at in rows:
        if classification == "ENTITLED" and status == 200:
            endpoint_state = "ENTITLED"
        elif classification in {"UNENTITLED", "NOT_FOUND", "NOT FOUND"}:
            endpoint_state = str(classification).replace(" ", "_")
        else:
            endpoint_state = "DATA_UNAVAILABLE"
        out.append({"dataset": dataset, "state": endpoint_state, "http_status": status, "checked_at": checked_at})
    return out


def _score_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT c.ticker, c.signal_id, c.signal_timestamp, s.total_score, s.bucket,
               s.dataset_contrib_json, s.contributing_events_json, s.excluded_events_json,
               s.calc_version, s.input_digest
        FROM shadow_scores s JOIN candidates c ON c.candidate_id=s.candidate_id
        ORDER BY c.ticker, c.signal_id DESC
        """
    ).fetchall()
    keys = ["ticker", "signal_id", "signal_timestamp", "total_score", "bucket", "dataset_contrib_json", "contributing_events_json", "excluded_events_json", "calc_version", "input_digest"]
    return [dict(zip(keys, row)) for row in rows]


def _events_by_uid(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    out = {}
    for row in con.execute("SELECT event_uid,dataset,ticker,raw_event_id,availability_ts,availability_field,transaction_ts_seen,transaction_date_ignored,excluded,excluded_reason,polarity FROM evidence_events"):
        out[str(row[0])] = dict(zip(["event_uid","dataset","ticker","raw_event_id","availability_ts","availability_field","transaction_ts_seen","transaction_date_ignored","excluded","excluded_reason","polarity"], row))
    return out


def _view(total: float | None, contrib: dict[str, Any], contributing: list[dict[str, Any]], health_ok: bool) -> str:
    if not health_ok:
        return "DATA_UNAVAILABLE"
    if not contributing:
        return "NO_USABLE_DATA"
    pos = any(float(x.get("contribution") or 0) > 0 for x in contributing)
    neg = any(float(x.get("contribution") or 0) < 0 for x in contributing)
    if pos and neg or contrib.get("conflict_penalty"):
        return "MIXED"
    if (total or 0) > 0:
        return "SUPPORTIVE"
    if (total or 0) < 0:
        return "CAUTION"
    return "NO_USABLE_DATA"


def _ticker_context(row: dict[str, Any], events: dict[str, dict[str, Any]], endpoint_status: list[dict[str, Any]], health_ok: bool) -> dict[str, Any]:
    contrib = json.loads(row.get("dataset_contrib_json") or "{}")
    contributing = json.loads(row.get("contributing_events_json") or "[]")
    excluded = json.loads(row.get("excluded_events_json") or "[]")
    enriched = []
    for item in contributing:
        ev = events.get(str(item.get("event_uid"))) or {}
        enriched.append({
            "event_uid": item.get("event_uid"),
            "dataset": item.get("dataset") or ev.get("dataset"),
            "contribution": item.get("contribution"),
            "public_availability_date": item.get("publication_ts") or ev.get("availability_ts"),
            "availability_field": ev.get("availability_field"),
            "transaction_date_seen": ev.get("transaction_ts_seen"),
            "transaction_date_ignored": bool(ev.get("transaction_date_ignored")),
            "age_days": item.get("age_days"),
            "freshness_weight": item.get("freshness_weight"),
        })
    endpoint_completeness = {e["dataset"]: e["state"] for e in endpoint_status}
    total = float(row.get("total_score") or 0)
    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "quiver_view": _view(total, contrib, enriched, health_ok),
        "primary_shadow_score": total,
        "congress_contribution": float(contrib.get("congress") or 0),
        "government_contract_contribution": float(contrib.get("government_contracts") or 0),
        "lobbying_contribution": float(contrib.get("lobbying") or 0),
        "off_exchange_contribution": {"value": float(contrib.get("off_exchange") or 0), "authority": "EXPLORATORY"},
        "contributing_public_evidence": enriched,
        "excluded_evidence": excluded,
        "public_availability_dates_used": [x.get("public_availability_date") for x in enriched if x.get("public_availability_date")],
        "age_days": [x.get("age_days") for x in enriched if x.get("age_days") is not None],
        "conflict_penalty": float(contrib.get("conflict_penalty") or 0),
        "endpoint_completeness": endpoint_completeness,
        "calculation_version": row.get("calc_version") or CALC_VERSION,
        "input_digest": row.get("input_digest"),
    }


def build_packet(sidecar: str = DEFAULT_SIDECAR, now_value: str | None = None) -> dict[str, Any]:
    h = health(sidecar)
    if h.get("status") != "PASS":
        packet = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_value or now_iso(),
            "source_sidecar_sha": sha_file(sidecar) if Path(sidecar).exists() else None,
            "source_run_id": None,
            "source_health": h,
            "latest_completed_session": None,
            "freshness_state": "DATA_UNAVAILABLE",
            "endpoint_status": [],
            "ticker_contexts": {},
        }
        packet["packet_digest"] = sha_json({k: v for k, v in packet.items() if k != "packet_digest"})
        return packet
    con = ro_conn(sidecar)
    try:
        latest_run = _load_latest_run(con)
        endpoints = _endpoint_status(con)
        events = _events_by_uid(con)
        contexts = {}
        for row in _score_rows(con):
            ctx = _ticker_context(row, events, endpoints, True)
            if ctx["ticker"]:
                contexts[ctx["ticker"]] = ctx
        packet = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_value or now_iso(),
            "source_sidecar_sha": sha_file(sidecar),
            "source_run_id": latest_run.get("run_id"),
            "source_health": h,
            "latest_completed_session": _latest_completed_session(con),
            "freshness_state": "FRESH" if latest_run.get("status") in {"PASS", "NO_RUNS"} else "DATA_UNAVAILABLE",
            "endpoint_status": endpoints,
            "ticker_contexts": contexts,
        }
        packet["packet_digest"] = sha_json({k: v for k, v in packet.items() if k != "packet_digest"})
        return packet
    finally:
        con.close()


def validate_packet(packet: dict[str, Any]) -> tuple[bool, str]:
    req = {"schema_version","generated_at","source_sidecar_sha","source_run_id","source_health","latest_completed_session","freshness_state","endpoint_status","ticker_contexts","packet_digest"}
    if set(packet) != req:
        return False, "schema_fields"
    if packet.get("schema_version") != SCHEMA_VERSION:
        return False, "schema_version"
    if packet.get("freshness_state") not in {"FRESH","STALE","DATA_UNAVAILABLE"}:
        return False, "freshness_state"
    calc_digest = sha_json({k: v for k, v in packet.items() if k != "packet_digest"})
    if calc_digest != packet.get("packet_digest"):
        return False, "digest"
    for t, ctx in (packet.get("ticker_contexts") or {}).items():
        if ctx.get("quiver_view") not in VALID_VIEWS:
            return False, f"view:{t}"
    return True, "ok"


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    with os.fdopen(fd, "w") as f:
        f.write(data)
    os.replace(tmp, p)


def write_packet_outputs(packet: dict[str, Any], outbox: str = DEFAULT_OUTBOX) -> dict[str, str]:
    out = Path(outbox)
    archive = out / "quiver_engine_packets"
    archive.mkdir(parents=True, exist_ok=True)
    digest = packet["packet_digest"]
    archived = archive / f"quiver_engine_packet_v1_{packet['generated_at'].replace(':','').replace('-','')}_{digest[:12]}.json"
    latest = out / "quiver_engine_packet_v1.json"
    pointer = out / "quiver_engine_packet_v1.pointer"
    atomic_write_json(archived, packet)
    atomic_write_json(latest, packet)
    pointer.write_text(str(archived) + "\n")
    return {"latest_packet": str(latest), "current_pointer": str(pointer), "archive_packet": str(archived)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", default=DEFAULT_SIDECAR)
    ap.add_argument("--outbox", default=DEFAULT_OUTBOX)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    pkt = build_packet(args.sidecar)
    ok, reason = validate_packet(pkt)
    if not ok:
        raise SystemExit(f"packet_invalid:{reason}")
    result = {"packet": pkt}
    if args.write:
        result["paths"] = write_packet_outputs(pkt, args.outbox)
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
