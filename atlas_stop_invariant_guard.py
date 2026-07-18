#!/usr/bin/env python3
"""Deterministic, stdlib-only, read-only Atlas stop-invariant guard.

The evaluator never mutates SQLite and never performs network or broker activity.
Current ATR14 values and session dates are explicit cycle inputs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo
import atlas_nyse_calendar as nyse_calendar

PACKET_VERSION = "stop_invariant_guard.v1"
ENGINE_SOURCE = "atlas_portfolio.py:trailing_stop"
PP_SOURCE = "atlas_profit_protection_apply.py"
ENGINE_REASONS = {
    "PEAK_1R_BREAKEVEN", "PEAK_2R_LOCK_1R", "REGIME_RISK_OFF_BREAKEVEN",
    "BREAKEVEN_STOP_RAISED", "RUNNER_STOP_RAISED"
}
CENT = Decimal("0.01")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode()).hexdigest()


def _dec(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise InvalidOperation
    value = Decimal(str(value))
    if not value.is_finite():
        raise InvalidOperation
    return value


def _cent(value: Any) -> Decimal:
    return _dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_ts(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    try:
        out = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if out.tzinfo is None:
            out = out.replace(tzinfo=dt.timezone.utc)
        return out.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _ro_connect(db_path: str, deployment_mode: str | None = None,
                canonical_production_db: str = "/Users/yasser/scripts/atlas.db",
                retries: int = 2) -> sqlite3.Connection:
    real = os.path.realpath(db_path)
    production = os.path.realpath(canonical_production_db)
    if deployment_mode in (None, "staging") and real == production:
        raise PermissionError("production DB realpath rejected by stop guard")
    if deployment_mode == "production" and real != production:
        raise PermissionError("non-canonical DB realpath rejected in production mode")
    if deployment_mode not in (None, "staging", "production"):
        raise ValueError("unsupported deployment_mode")
    uri = Path(real).as_uri() + "?mode=ro"
    last = None
    for attempt in range(retries + 1):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=0.15)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            return con
        except sqlite3.Error as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.05 * (attempt + 1))
    raise last or sqlite3.OperationalError("read-only connection unavailable")


def allowed_session_dates(cycle_started_at: Any = None) -> set[str]:
    """Latest two governed NYSE sessions (including holiday/closure rules)."""
    stamp = _parse_ts(cycle_started_at) or dt.datetime.now(dt.timezone.utc)
    day = stamp.astimezone(ZoneInfo("America/New_York")).date()
    sessions = []
    while len(sessions) < 2:
        schedule = nyse_calendar.session_schedule_governed(day)
        if schedule.get("calendar_blocker"):
            raise ValueError("CALENDAR_AUTHORITY_BLOCKER")
        if schedule.get("is_trading_day"):
            sessions.append(day.isoformat())
        day -= dt.timedelta(days=1)
    return set(sessions)


def _session_eligible(created_at: Any, allowed_session_dates: set[str]) -> tuple[bool, str | None]:
    stamp = _parse_ts(created_at)
    if stamp is None:
        return False, "BROKER_CONFIRMATION_TIME_UNPROVABLE"
    session_date = stamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if session_date not in allowed_session_dates:
        return False, "BROKER_CONFIRMATION_STALE"
    return True, None


def _valid_event(event: sqlite3.Row, trade: sqlite3.Row, cycle_ts: dt.datetime) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(event["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError
    except Exception:
        return None, "STOP_EVENT_PAYLOAD_INVALID"
    effective = _parse_ts(event["effective_at"])
    recorded = _parse_ts(event["recorded_at"])
    entry_at = _parse_ts(trade["entry_at"])
    if not effective or not recorded or not entry_at or effective < entry_at or recorded > cycle_ts:
        return None, "STOP_EVENT_TIME_INVALID"
    if event["legacy_trades_id"] != trade["id"] or str(event["ticker"] or "").upper() != str(trade["ticker"]).upper():
        return None, "STOP_EVENT_LINK_MISMATCH"
    if str(event["event_type"]) != "MANUAL_CORRECTION":
        return None, "STOP_EVENT_TYPE_UNAPPROVED"
    if int(payload.get("trade_id")) != int(trade["id"]) or str(payload.get("ticker") or "").upper() != str(trade["ticker"]).upper():
        return None, "STOP_EVENT_PAYLOAD_LINK_MISMATCH"
    if _cent(payload.get("old_stop")) >= _cent(payload.get("new_stop")):
        return None, "STOP_EVENT_NOT_A_RAISE"
    source = str(event["source"] or "")
    if source == ENGINE_SOURCE:
        required = {"trade_id", "ticker", "old_stop", "new_stop", "trail_reason", "entry_price", "calculation_timestamp", "cycle_id"}
        if int(event["prof_approved"] or 0) != 0 or payload.get("trail_reason") not in ENGINE_REASONS or not required.issubset(payload) or not event["idempotency_key"]:
            return None, "STOP_EVENT_ENGINE_AUTHORITY_INVALID"
    elif source == PP_SOURCE:
        required = {"trade_id", "ticker", "old_stop", "new_stop", "action", "policy_version", "policy_digest", "evidence_event_id", "provider_timestamp", "calculation_timestamp"}
        if int(event["prof_approved"] or 0) != 1 or not required.issubset(payload) or not event["idempotency_key"] or not payload.get("policy_digest") or not payload.get("evidence_event_id"):
            return None, "STOP_EVENT_PP_AUTHORITY_INVALID"
    else:
        return None, "STOP_EVENT_SOURCE_UNAPPROVED"
    return payload, None


def _authorizing_chain(con: sqlite3.Connection, trade: sqlite3.Row, cycle_ts: dt.datetime, baseline: Decimal, tolerance: Decimal) -> tuple[int | None, list[str]]:
    events = con.execute("""
        SELECT * FROM portfolio_event_journal e
        WHERE e.legacy_trades_id=? AND e.event_type='MANUAL_CORRECTION'
          AND NOT EXISTS (SELECT 1 FROM portfolio_event_journal r
              WHERE r.event_type='REVERSAL' AND (r.linked_reversal_id=e.id OR r.supersedes_id=e.id))
          AND NOT EXISTS (SELECT 1 FROM portfolio_event_journal s
              WHERE s.supersedes_id=e.id)
        ORDER BY e.effective_at ASC, e.id ASC
    """, (trade["id"],)).fetchall()
    previous = None
    matched_id = None
    failures: list[str] = []
    for event in events:
        try:
            payload, failure = _valid_event(event, trade, cycle_ts)
        except Exception:
            payload, failure = None, "STOP_EVENT_PAYLOAD_INVALID"
        if failure:
            failures.append(failure)
            continue
        old_stop = _cent(payload["old_stop"])
        if previous is None:
            if abs(old_stop - baseline) > tolerance:
                failures.append("STOP_EVENT_CHAIN_INITIAL_BASELINE_MISMATCH")
                continue
        elif old_stop != previous:
            failures.append("STOP_EVENT_CHAIN_BROKEN")
            continue
        previous = _cent(payload["new_stop"])
        matched_id = int(event["id"])
    if previous != _cent(trade["stop_loss"]):
        failures.append("STOP_EVENT_CURRENT_STOP_MISMATCH")
        return None, failures
    return matched_id, failures


def evaluate_cycle(*, db_path: str, cycle_id: str, current_atr14: Mapping[Any, Any],
                   allowed_broker_session_dates: set[str] | list[str], cycle_started_at: Any = None,
                   deployment_mode: str | None = None,
                   canonical_production_db: str = "/Users/yasser/scripts/atlas.db") -> dict[str, Any]:
    """Evaluate every OPEN lot from one consistent read transaction."""
    started = _parse_ts(cycle_started_at) or dt.datetime.now(dt.timezone.utc)
    base = {"packet_version": PACKET_VERSION, "cycle_id": str(cycle_id), "cycle_started_at": started.isoformat()}
    con = None
    try:
        con = _ro_connect(db_path, deployment_mode=deployment_mode,
                          canonical_production_db=canonical_production_db)
        cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
        if "entry_atr14" not in cols:
            raise RuntimeError("entry_atr14 schema unavailable")
        trades = con.execute("SELECT id,ticker,quantity,entry_price,entry_at,stop_loss,entry_atr14,broker_ref FROM trades WHERE status='OPEN' ORDER BY ticker,id").fetchall()
        counts = {r[0]: r[1] for r in con.execute("SELECT ticker,COUNT(*) FROM trades WHERE status='OPEN' GROUP BY ticker")}
        lots = []
        for trade in trades:
            reasons: list[str] = []
            violations: list[str] = []
            matched_event = None
            try:
                entry, stop = _dec(trade["entry_price"]), _dec(trade["stop_loss"])
                if entry <= 0 or stop <= 0:
                    raise InvalidOperation
            except Exception:
                entry = stop = None
                violations.append("STOP_INVALID")
            try:
                entry_atr = _dec(trade["entry_atr14"])
                if entry_atr <= 0:
                    raise InvalidOperation
            except Exception:
                entry_atr = None
                reasons.append("ENTRY_ATR14_PROVENANCE_MISSING")
            atr_raw = current_atr14.get(trade["id"], current_atr14.get(str(trade["id"]), current_atr14.get(str(trade["ticker"]).upper())))
            try:
                atr = _dec(atr_raw)
                if atr <= 0:
                    raise InvalidOperation
            except Exception:
                atr = None
                reasons.append("CURRENT_ATR14_UNAVAILABLE")
            baseline = (entry - Decimal("1.5") * entry_atr).quantize(CENT) if entry is not None and entry_atr is not None else None
            tolerance = max(CENT, Decimal("0.25") * atr) if atr is not None else None
            if entry is not None and stop is not None:
                if stop >= entry:
                    if baseline is None or tolerance is None:
                        violations.append("STOP_ABOVE_ENTRY_WITHOUT_AUTHORIZING_EVENT")
                    else:
                        matched_event, chain_failures = _authorizing_chain(con, trade, started, baseline, tolerance)
                        if matched_event is None:
                            violations.append("STOP_ABOVE_ENTRY_WITHOUT_AUTHORIZING_EVENT")
                            reasons.extend(chain_failures)
                elif baseline is not None and tolerance is not None:
                    canonical_current = entry - Decimal("1.5") * atr
                    if abs(stop - canonical_current) > tolerance:
                        violations.append("STOP_ATR_FORMULA_OUTSIDE_TOLERANCE")
            snapshots = con.execute("SELECT * FROM broker_position_display_snapshots WHERE ticker=? ORDER BY created_at DESC,id DESC", (trade["ticker"],)).fetchall()
            linked = [s for s in snapshots if s["legacy_trades_id"] == trade["id"] or (counts.get(trade["ticker"], 0) == 1 and trade["broker_ref"])]
            if counts.get(trade["ticker"], 0) > 1 and not any(s["legacy_trades_id"] == trade["id"] or s["lot_id"] for s in snapshots):
                reasons.append("BROKER_QUANTITY_PER_LOT_UNPROVABLE")
            elif not linked:
                reasons.append("BROKER_QUANTITY_MISSING")
            else:
                snap = linked[0]
                fresh, freshness_reason = _session_eligible(snap["created_at"], set(allowed_broker_session_dates))
                if not fresh:
                    reasons.append(freshness_reason)
                else:
                    try:
                        shares = _dec(snap["shares_text"])
                        scaled = _dec(snap["shares_scaled"]) / _dec(snap["shares_scale"])
                        if shares != scaled:
                            reasons.append("BROKER_QUANTITY_ENCODING_INVALID")
                        elif _dec(trade["quantity"]) != shares:
                            violations.append("BROKER_QUANTITY_MISMATCH")
                    except Exception:
                        reasons.append("BROKER_QUANTITY_MALFORMED")
            result = "VIOLATION" if violations else ("DATA_INCOMPLETE" if reasons else "PASS")
            codes = sorted(set(violations + reasons))
            lots.append({"ticker": trade["ticker"], "trade_id": trade["id"], "result": result,
                         "reason_codes": codes, "matched_event_id": matched_event,
                         "entry_price": str(entry) if entry is not None else None,
                         "stop_loss": str(stop) if stop is not None else None,
                         "canonical_entry_stop": str(baseline) if baseline is not None else None})
        con.rollback()
        base["lots"] = lots
        base["cycle_result"] = "VIOLATION" if any(x["result"] == "VIOLATION" for x in lots) else ("DATA_INCOMPLETE" if any(x["result"] == "DATA_INCOMPLETE" for x in lots) else "PASS")
    except Exception as exc:
        base["lots"] = []
        base["cycle_result"] = "DATA_INCOMPLETE"
        base["cycle_reason_codes"] = ["OPEN_LOT_INVENTORY_UNAVAILABLE"]
        base["error_type"] = type(exc).__name__
    finally:
        if con is not None:
            con.close()
    base["digest"] = _digest(base)
    return base


def veto_by_trade(receipt: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    return {int(x["trade_id"]): x for x in receipt.get("lots", []) if x.get("result") != "PASS"}


def alert_hard_violations(receipt: Mapping[str, Any], sender=None) -> int:
    """Dispatch exactly one logical Professor-DM alert for all hard violations."""
    violations = [x for x in receipt.get("lots", []) if x.get("result") == "VIOLATION"]
    if not violations:
        return 0
    if sender is None:
        from atlas_notify import send_telegram as sender
    lines = ["STOP INVARIANT GUARD VIOLATION", f"cycle={receipt.get('cycle_id')} digest={receipt.get('digest')}"]
    for lot in violations:
        lines.append(f"{lot['ticker']} trade={lot['trade_id']} reason={','.join(lot['reason_codes'])} entry={lot.get('entry_price')} stop={lot.get('stop_loss')} event={lot.get('matched_event_id')}")
    lines.append("DATA INCOMPLETE — NO TRADE INSTRUCTION")
    sender("\n".join(lines), route="professor_dm", report_type="stop_invariant_guard")
    return 1
