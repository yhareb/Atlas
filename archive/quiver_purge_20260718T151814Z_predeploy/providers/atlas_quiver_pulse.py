#!/usr/bin/env python3
"""Quiver Pulse human brief renderer.

Perme-style Professor-facing brief. Staging-safe: dry-run suppresses Telegram.
No JSON/hash/run-id/endpoint/database internals in human body.
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from atlas_time import is_trading_day
from atlas_quiver_engine_packet import build_packet, validate_packet, write_packet_outputs
from atlas_quiver_bridge import plain_reason

ET = ZoneInfo("America/New_York")
DEFAULT_OUTBOX = "/Users/yasser/atlas_inbox"
LATEST_HUMAN = "quiver_latest_context.md"
SENT_MANIFEST = "quiver_pulse_sent_manifest.json"


def _is_session(day: date) -> bool:
    return day.weekday() < 5 and bool(is_trading_day(day))


def _material(ctx: dict) -> bool:
    return ctx.get("quiver_view") in {"SUPPORTIVE", "CAUTION", "MIXED"}


def _human_reason(ctx: dict) -> str:
    return str(ctx.get("plain_english") or ctx.get("quiver_evidence") or ctx.get("evidence_summary") or plain_reason(ctx))


def render_human(packet: dict) -> str:
    contexts = list((packet.get("ticker_contexts") or {}).values())
    material = [c for c in contexts if _material(c)]
    open_holdings = [c for c in material if str(c.get("position_state") or c.get("holding_state") or "").upper() == "OPEN"]
    actionable_buys = [c for c in material if str(c.get("raw_tfe_classification") or c.get("tfe_classification") or c.get("candidate_action") or "").upper().replace("_", " ") in {"BUY", "BUY SMALL"}]
    supportive_buy = sorted([c for c in actionable_buys if c.get("quiver_view") == "SUPPORTIVE"], key=lambda x: x.get("primary_shadow_score") or 0, reverse=True)
    caution_buy = sorted([c for c in actionable_buys if c.get("quiver_view") in {"CAUTION", "MIXED"}], key=lambda x: x.get("primary_shadow_score") or 0)
    supportive_avoid = [c for c in material if c.get("quiver_view") == "SUPPORTIVE" and "AVOID" in str(c.get("raw_tfe_classification") or c.get("tfe_classification") or "").upper()]
    mixed = [c for c in material if c.get("quiver_view") == "MIXED"]
    gaps = []
    for e in packet.get("endpoint_status") or []:
        if e.get("state") not in {"ENTITLED", "EMPTY_RESPONSE"}:
            gaps.append(str(e.get("dataset")).replace("_", " "))
    lines = ["📍 QUIVER PULSE", ""]
    if open_holdings:
        lines.append("OPEN holdings first:")
        for c in open_holdings[:8]:
            flag = "REVIEW NOW" if c.get("quiver_view") in {"CAUTION", "MIXED"} else c.get("quiver_view")
            lines.append(f"- {c['ticker']}: {flag} — {_human_reason(c)}")
        lines.append("")
    if supportive_buy:
        lines.append("Supportive evidence on actionable BUY candidates:")
        for c in supportive_buy[:5]:
            lines.append(f"- {c['ticker']}: {_human_reason(c)}")
        lines.append("")
    if caution_buy:
        lines.append("Cautionary evidence on actionable BUY candidates:")
        for c in caution_buy[:5]:
            action = "WAIT / REVIEW" if c.get("quiver_view") == "CAUTION" else "REVIEW"
            lines.append(f"- {c['ticker']}: {action} — {_human_reason(c)}")
        lines.append("")
    if supportive_avoid:
        lines.append("Supportive evidence that does not override an AVOID:")
        for c in supportive_avoid[:5]:
            lines.append(f"- {c['ticker']}: Supportive Quiver evidence exists, but TFE remains AVOID.")
        lines.append("")
    if mixed:
        lines.append("Conflicts:")
        for c in mixed[:5]:
            lines.append(f"- {c['ticker']}: {_human_reason(c)}")
        lines.append("")
    if not material:
        lines += ["No material Quiver evidence for current candidates or holdings.", ""]
    if gaps:
        lines += ["Data gaps: " + ", ".join(sorted(set(gaps))) + ".", ""]
    lines += ["Freshness: " + str(packet.get("freshness_state") or "DATA_UNAVAILABLE") + "."]
    return "\n".join(lines).strip() + "\n"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def already_sent(outbox: Path, digest: str) -> bool:
    manifest = outbox / SENT_MANIFEST
    try:
        data = json.loads(manifest.read_text())
    except Exception:
        data = {"sent_digests": []}
    return digest in set(data.get("sent_digests") or [])


def record_sent(outbox: Path, digest: str) -> None:
    manifest = outbox / SENT_MANIFEST
    try:
        data = json.loads(manifest.read_text())
    except Exception:
        data = {"sent_digests": []}
    vals = list(dict.fromkeys(list(data.get("sent_digests") or []) + [digest]))[-200:]
    atomic_write(manifest, json.dumps({"sent_digests": vals}, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", default="/Users/yasser/Library/Application Support/Atlas/quiver_shadow/db/quiver_sidecar.sqlite")
    ap.add_argument("--outbox", default=DEFAULT_OUTBOX)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-session", action="store_true")
    args = ap.parse_args(argv)
    now_et = datetime.now(ET)
    if not args.force_session and not _is_session(now_et.date()):
        print(f"QUIVER_SKIP_NON_TRADING_DAY date={now_et.date().isoformat()}")
        return 0
    packet = build_packet(args.sidecar)
    ok, reason = validate_packet(packet)
    if not ok:
        raise SystemExit(f"packet_invalid:{reason}")
    outbox = Path(args.outbox)
    paths = write_packet_outputs(packet, outbox)
    text = render_human(packet)
    latest = outbox / LATEST_HUMAN
    atomic_write(latest, text)
    duplicate = already_sent(outbox, packet["packet_digest"])
    if args.dry_run:
        print("[quiver] dry-run: Telegram delivery suppressed")
        print("QUIVER_TELEGRAM_DELIVERY_PATH=atlas_notify.send_telegram owner/admin route")
    elif duplicate:
        print("[quiver] duplicate source packet; Telegram delivery suppressed")
    else:
        from atlas_notify import send_telegram, _admin_chat_id
        send_telegram(text, label="atlas", parse_mode="", print_fallback=True, chat_id=_admin_chat_id(), message_thread_id=None)
        record_sent(outbox, packet["packet_digest"])
    print("QUIVER_RESULT_JSON=" + json.dumps({"latest_human_context": str(latest), "packet_paths": paths, "duplicate": duplicate}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
