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
        sys.path.insert(0, _path)

import atlas_db  # noqa: E402
from atlas_notify import send_telegram  # noqa: E402


_EVENT_UNKNOWN = "UNKNOWN"
_EVENT_BUY = "BUY_FILL"
_EVENT_SELL = "SELL_FILL"


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
    out["stop_loss"] = _number_after([r"(?:Stop|SL)\s*[:#]?\s*\$?([0-9.,]+)"], text)
    out["target_price"] = _number_after([r"(?:Target|TP)\s*[:#]?\s*\$?([0-9.,]+)"], text)
    return out


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
                stop_loss=data.get("stop_loss"), target_price=data.get("target_price"), status="PENDING_FILL",
            )
            row = atlas_db.confirm_trade_fill(trade_id, data["quantity"], data["entry_price"], data.get("fees") or 0.0, data["broker_ref"])
            _notify(f"✅ Broker ingest: BUY {data['ticker']} {data['entry_price']} registered automatically")
            return {"event": _EVENT_BUY, "status": "registered", "trade_id": trade_id, "row": row, "source": source_filename}

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


if __name__ == "__main__":
    payload = sys.stdin.read()
    print(detect_and_register(payload, "stdin"))
