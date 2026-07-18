#!/usr/bin/env python3
"""Broker document parser for Atlas Docling ingest.

Parses broker-confirmation OCR/text and registers confirmed BUY/SELL events in
atlas.db. This module is intentionally conservative: UNKNOWN parses do not write.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from typing import Any

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
for _path in (SCRIPTS_DIR, "/Users/yasser/scripts"):
    if _path not in sys.path:
        # Keep this release unit ahead of the production fallback.  Inserting
        # the fallback at index zero could silently import the legacy live
        # module while a staging CLI/test is running.
        (sys.path.insert(0, _path) if _path == SCRIPTS_DIR else sys.path.append(_path))

import atlas_db  # noqa: E402
from atlas_notify import send_telegram  # noqa: E402
from atlas_registration_gate import BrokerParseV2, deterministic_gate, duplicate_projection
from atlas_registration import migrate, register_buy_atomic, register_sell_atomic, apply_audit, wio_is_retired
from atlas_registration_auditor import audit_image
from atlas_notify import send_professor_media


_EVENT_UNKNOWN = "UNKNOWN"
_EVENT_BUY = "BUY_FILL"
_EVENT_SELL = "SELL_FILL"
_EVENT_DISPLAY = "BROKER_POSITION_DISPLAY"


_COMPANY_TICKER_HINTS = {
    "LAM RESEARCH": "LRCX",
    "KULICKE": "KLIC",
    "BANK OF AMERICA": "BAC",
    "INTEL": "INTC",
    "SYNAPTICS": "SYNA",
    "RALPH LAUREN": "RL",
    "IRIDIUM": "IRDM",
    "ALLEGRO": "ALGM",
}


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] broker_ingest: {msg}"
    print(line, flush=True)
    try:
        with open(os.environ.get("ATLAS_BROKER_INGEST_LOG", "/Users/yasser/scripts/atlas_ingest.log"), "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _notify(msg: str) -> None:
    if os.environ.get("ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM", "0").lower() in ("1", "true", "yes", "on"):
        _log(f"telegram suppressed: {msg}")
        return
    try:
        send_telegram(msg, label="atlas", parse_mode="", print_fallback=True)
    except Exception as exc:
        _log(f"telegram notify failed: {type(exc).__name__}: {exc}")


def _clean_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("\u2212", "-").replace("−", "-").replace("–", "-")
    text = re.sub(r"[\t\r]+", " ", text)
    return text


def _money_value(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    neg = False
    if "(" in s and ")" in s:
        neg = True
    if s.startswith("-"):
        neg = True
    s = re.sub(r"[^0-9.]", "", s)
    if not s:
        return None
    try:
        val = float(s)
    except Exception:
        return None
    return -val if neg else val


def _number_after(patterns: list[str], text: str) -> float | None:
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            val = _money_value(m.group(1))
            if val is not None:
                return val
    return None


def _ref_value(text: str) -> str | None:
    patterns = [
        r"(?:Reference(?:\s+number)?|Ref(?:erence)?|ID\s*#|Order\s+ID)\s*[:#]?\s*([A-Z0-9\-]+)",
        r"#\s*([0-9]{6,})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return None


def _ticker_value(text: str) -> str | None:
    # Prefer explicit ticker in parentheses or direct BUY/SELL ticker patterns.
    for pat in (
        r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)",
        r"\b(?:BUY|SELL)\s+([A-Z]{1,5}(?:\.[A-Z])?)\b",
        r"\b([A-Z]{1,5}(?:\.[A-Z])?)\s+(?:BUY|SELL)\b",
        r"\bTicker\s*[:#]?\s*([A-Z]{1,5}(?:\.[A-Z])?)\b",
    ):
        m = re.search(pat, text, re.I)
        if m:
            candidate = m.group(1).upper()
            if candidate not in {"BUY", "SELL", "OPEN", "CLOSE", "USD", "ID", "ETF"}:
                return candidate
    upper = text.upper()
    for company, ticker in _COMPANY_TICKER_HINTS.items():
        if company in upper:
            return ticker
    return None


def _open_trade_id_for_ticker(ticker: str, quantity: float | None = None) -> int | None:
    conn = atlas_db.get_connection()
    conn.row_factory = None
    cur = conn.cursor()
    cur.execute("SELECT id, quantity FROM trades WHERE ticker=? AND status='OPEN' ORDER BY entry_at ASC, id ASC", (ticker.upper(),))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return None
    if quantity is not None:
        for trade_id, qty in rows:
            try:
                if abs(float(qty) - float(quantity)) <= 0.0001:
                    return int(trade_id)
            except Exception:
                pass
    return int(rows[0][0])


def _broker_ref_exists(ref: str | None) -> bool:
    if not ref:
        return False
    conn = atlas_db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trades WHERE broker_ref=? OR notes LIKE ?", (ref, f"%{ref}%"))
    found = int(cur.fetchone()[0] or 0) > 0
    conn.close()
    return found


def _classify(text: str) -> str:
    upper = text.upper()
    if any(k in upper for k in ("SELL", "CLOSE", "CLOSED")) and any(k in upper for k in ("EXECUTED", "TRADE STORY", "AVERAGE PRICE", "P/L", "REFERENCE")):
        return _EVENT_SELL
    if any(k in upper for k in ("BUY", "ORDER FILLED", "OPEN")) and any(k in upper for k in ("EXECUTED", "TRADE STORY", "AVERAGE PRICE", "UNITS", "REFERENCE")):
        return _EVENT_BUY
    if _ticker_value(text) and any(k in upper for k in ("TP", "TARGET", "SL", "STOP", "CURRENT", "POSITION VALUE", "VALUE", "P/L")):
        return _EVENT_DISPLAY
    return _EVENT_UNKNOWN


def _parse_common(text: str) -> dict[str, Any]:
    return {
        "ticker": _ticker_value(text),
        "broker_ref": _ref_value(text),
        "quantity": _number_after([
            r"Executed\s+quantity\s*[:#]?\s*([0-9.,]+)",
            r"Quantity\s*[:#]?\s*([0-9.,]+)",
            r"Units\s*[:#]?\s*([0-9.,]+)",
        ], text),
        "fees": _number_after([
            r"Commission(?:\s+incl\s+VAT)?\s*[:#]?\s*(-?\$?[0-9.,]+)",
            r"Fees?\s*[:#]?\s*(-?\$?[0-9.,]+)",
            r"Overnight\s+fees\s*[:#]?\s*(-?\$?[0-9.,]+)",
        ], text) or 0.0,
    }


def _parse_buy(text: str) -> dict[str, Any]:
    out = _parse_common(text)
    out["entry_price"] = _number_after([
        r"Average\s+price\s*[:#]?\s*\$?([0-9.,]+)",
        r"Open\s*[:#]?\s*\$?([0-9.,]+)",
        r"BUY\s+[A-Z0-9.\-]+[^\n$]*@\s*\$?([0-9.,]+)",
        r"price\s*[:#]?\s*\$?([0-9.,]+)",
    ], text)
    out["broker_stop_display"] = _number_after([r"(?:Stop|SL)\s*[:#]?\s*\$?([0-9.,]+)"], text)
    out["broker_take_profit_display"] = _number_after([r"(?:Target|TP)\s*[:#]?\s*\$?([0-9.,]+)"], text)
    out["broker_current"] = _number_after([r"Current\s*[:#]?\s*\$?([0-9.,]+)", r"Market\s+value\s*[:#]?\s*\$?([0-9.,]+)"], text)
    out["broker_pl"] = _number_after([r"P\s*/\s*L\s*[:#]?\s*([+-]?\$?[0-9.,]+)", r"Profit\s*/\s*Loss\s*[:#]?\s*([+-]?\$?[0-9.,]+)"], text)
    out["broker_value"] = _number_after([r"Value\s*[:#]?\s*\$?([0-9.,]+)", r"Position\s+value\s*[:#]?\s*\$?([0-9.,]+)"], text)
    return out


def _parse_display(text: str) -> dict[str, Any]:
    out = _parse_buy(text)
    out["shares"] = out.pop("quantity", None)
    out["broker_entry"] = out.pop("entry_price", None)
    out.pop("fees", None)
    # Defense-in-depth: display parse must never expose model field keys.
    out.pop("target_price", None)
    out.pop("stop_loss", None)
    out.pop("risk_pct", None)
    return out


def _has_broker_display_values(data: dict[str, Any]) -> bool:
    return any(data.get(k) not in (None, "") for k in (
        "broker_take_profit_display", "broker_stop_display", "broker_current", "broker_pl", "broker_value"
    ))


def _record_display_snapshot(data: dict[str, Any], source_filename: str) -> dict[str, Any] | None:
    if not data.get("ticker") or not _has_broker_display_values(data):
        return None
    return atlas_db.record_broker_position_display_snapshot(
        ticker=data.get("ticker"), broker_ref=data.get("broker_ref"),
        shares=data.get("shares", data.get("quantity")),
        broker_entry=data.get("broker_entry", data.get("entry_price")),
        broker_current=data.get("broker_current"),
        broker_take_profit_display=data.get("broker_take_profit_display"),
        broker_stop_display=data.get("broker_stop_display"),
        broker_pl=data.get("broker_pl"), broker_value=data.get("broker_value"),
        source_filename=source_filename,
    )


def _parse_sell(text: str) -> dict[str, Any]:
    out = _parse_common(text)
    out["exit_price"] = _number_after([
        r"Average\s+price\s*[:#]?\s*\$?([0-9.,]+)",
        r"Close\s*[:#]?\s*\$?([0-9.,]+)",
        r"SELL\s+[A-Z0-9.\-]+[^\n$]*@\s*\$?([0-9.,]+)",
    ], text)
    out["realized_pnl"] = _number_after([
        r"P\s*/\s*L\s*[:#]?\s*([+-]?\$?[0-9.,]+)",
        r"Profit\s*/\s*Loss\s*[:#]?\s*([+-]?\$?[0-9.,]+)",
        r"Net\s+result\s*[:#]?\s*([+-]?\$?[0-9.,]+)",
    ], text)
    out["realized_pnl_pct"] = _number_after([
        r"P\s*/\s*L[^%\n]*?([+-]?[0-9.]+)\s*%",
        r"Net\s+result[^%\n]*?([+-]?[0-9.]+)\s*%",
    ], text)
    return out


def _missing(fields: dict[str, Any], names: list[str]) -> list[str]:
    return [name for name in names if fields.get(name) in (None, "")]


def detect_and_register(extracted_text: str, source_filename: str) -> dict:
    """Detect broker BUY/SELL fills in extracted text and write atlas.db.

    Returns a dict with event/action details. UNKNOWN or incomplete parses do not
    write to the DB.
    """
    text = _clean_text(extracted_text)
    event = _classify(text)
    source_filename = str(source_filename or "unknown")
    try:
        if event == _EVENT_BUY:
            data = _parse_buy(text)
            missing = _missing(data, ["ticker", "entry_price", "quantity", "broker_ref"])
            if missing:
                msg = f"⚠️ Broker ingest: could not parse {source_filename}"
                _log(f"BUY parse missing={missing} file={source_filename}")
                _notify(msg)
                return {"event": _EVENT_UNKNOWN, "status": "ignored", "reason": "missing_fields", "missing": missing, "source": source_filename}
            if _broker_ref_exists(data["broker_ref"]):
                _log(f"duplicate broker_ref={data['broker_ref']} file={source_filename}")
                return {"event": _EVENT_BUY, "status": "duplicate", "broker_ref": data["broker_ref"], "source": source_filename}
            trade_id = atlas_db.open_trade(
                data["ticker"], data["entry_price"], max(1, int(float(data["quantity"]))),
                fees=0.0,
                notes=f"Broker ingest source={source_filename}; ref={data['broker_ref']}",
                status="PENDING_FILL",
            )
            row = atlas_db.confirm_trade_fill(trade_id, data["quantity"], data["entry_price"], data.get("fees") or 0.0, data["broker_ref"])
            display_snapshot = _record_display_snapshot(data, source_filename)
            _notify(f"✅ Broker ingest: BUY {data['ticker']} {data['entry_price']} registered automatically")
            return {"event": _EVENT_BUY, "status": "registered", "trade_id": trade_id, "row": row, "broker_display_snapshot": display_snapshot, "source": source_filename}

        if event == _EVENT_DISPLAY:
            data = _parse_display(text)
            missing = _missing(data, ["ticker"])
            if missing:
                _log(f"DISPLAY parse missing={missing} file={source_filename}")
                return {"event": _EVENT_UNKNOWN, "status": "ignored", "reason": "missing_fields", "missing": missing, "source": source_filename}
            display_snapshot = _record_display_snapshot(data, source_filename)
            return {"event": _EVENT_DISPLAY, "status": "registered", "broker_display_snapshot": display_snapshot, "source": source_filename}

        if event == _EVENT_SELL:
            data = _parse_sell(text)
            missing = _missing(data, ["ticker", "exit_price", "quantity", "broker_ref"])
            if missing:
                msg = f"⚠️ Broker ingest: could not parse {source_filename}"
                _log(f"SELL parse missing={missing} file={source_filename}")
                _notify(msg)
                return {"event": _EVENT_UNKNOWN, "status": "ignored", "reason": "missing_fields", "missing": missing, "source": source_filename}
            if _broker_ref_exists(data["broker_ref"]):
                _log(f"duplicate broker_ref={data['broker_ref']} file={source_filename}")
                return {"event": _EVENT_SELL, "status": "duplicate", "broker_ref": data["broker_ref"], "source": source_filename}
            trade_id = _open_trade_id_for_ticker(data["ticker"], data.get("quantity"))
            if not trade_id:
                msg = f"⚠️ Broker ingest: could not parse {source_filename}"
                _log(f"SELL parse no open trade ticker={data['ticker']} file={source_filename}")
                _notify(msg)
                return {"event": _EVENT_UNKNOWN, "status": "ignored", "reason": "no_open_trade", "source": source_filename}
            row = atlas_db.close_trade_broker_confirmed(
                data["ticker"], trade_id, data["exit_price"], data["quantity"], data.get("fees") or 0.0,
                data["broker_ref"], realized_pnl=data.get("realized_pnl"), realized_pnl_pct=data.get("realized_pnl_pct"),
            )
            _notify(f"✅ Broker ingest: SELL {data['ticker']} {data['exit_price']} registered automatically")
            return {"event": _EVENT_SELL, "status": "registered", "trade_id": trade_id, "row": row, "source": source_filename}

        msg = f"⚠️ Broker ingest: could not parse {source_filename}"
        _log(f"UNKNOWN file={source_filename}")
        _notify(msg)
        return {"event": _EVENT_UNKNOWN, "status": "ignored", "reason": "unknown", "source": source_filename}
    except Exception as exc:
        msg = f"⚠️ Broker ingest: could not parse {source_filename}"
        _log(f"error file={source_filename}: {type(exc).__name__}: {exc}")
        _notify(msg)
        return {"event": event, "status": "error", "error": f"{type(exc).__name__}: {exc}", "source": source_filename}


def auto_register_from_artifacts(extracted_text: str, image_path, extraction: dict, *, auditor_runner=None, media_sender=None) -> dict:
    """Fail closed unless Docling exported complete confidence/provenance V2 evidence."""
    import json
    from pathlib import Path
    meta = json.loads(Path(extraction["metadata_path"]).read_text())
    raw = meta.get("registration_v2")
    if not isinstance(raw, dict):
        return {"status": "gate_failed", "gate": {"status": "FAIL",
                "failure_codes": ["REG_GATE_CONFIDENCE_MISSING:all",
                                  "REG_GATE_PROVENANCE_MISSING:all"]},
                "registered_row": False}
    raw.setdefault("source_path", str(image_path)); raw.setdefault("artifact_dir", extraction["artifact_dir"])
    raw.setdefault("source_sha256", extraction["sha256"])
    packet = BrokerParseV2(**raw)
    conn = atlas_db.get_connection(); migrate(conn)
    duplicate = duplicate_projection(conn, packet)
    receipt = deterministic_gate(packet, meta.get("market_evidence") or {}, duplicate=duplicate,
                                 open_context=meta.get("open_context") or {},
                                 wio_retired=wio_is_retired(conn))
    if receipt["status"] == "IDEMPOTENT_ALREADY_REGISTERED":
        conn.close(); return {"status": receipt["status"], "gate": receipt}
    if receipt["status"] != "PASS":
        conn.close(); return {"status": "gate_failed", "gate": receipt, "registered_row": False}
    out = register_buy_atomic(conn, packet, receipt) if packet.side.upper() == "BUY" else register_sell_atomic(conn, packet, receipt)
    audit=apply_audit(conn,out['registration_id'],audit_image(image_path,runner=auditor_runner))
    media=None
    if not audit['silent']:
        caption='REGISTERED | VISION AUDIT '+audit['kind']+'\nRegistration: '+out['registration_id']
        media=send_professor_media(image_path,caption,sender=media_sender)
        if not media.get('delivered'):
            conn.execute("INSERT INTO registration_alert_queue(alert_id,registration_id,media_path,message,status,attempts,last_error,created_at) VALUES(?,?,?,?, 'QUEUED',1,?,datetime('now'))",
                         ('alert-'+__import__('uuid').uuid4().hex,out['registration_id'],str(image_path),caption,media.get('error','DELIVERY_FAILED'))); conn.commit()
    pending=conn.execute("SELECT COUNT(*) FROM broker_registrations WHERE registration_id=? AND audit_status='PENDING_AUDIT'",(out['registration_id'],)).fetchone()[0]
    conn.close()
    if pending: raise RuntimeError('registration left PENDING_AUDIT')
    return {"status": "registered_audited", "gate": receipt, "transaction": out,"audit":audit,"media":media}


if __name__ == "__main__":
    payload = sys.stdin.read()
    print(detect_and_register(payload, "stdin"))
