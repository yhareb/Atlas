"""ORDER #25 deterministic per-lot exit policy (advisory; no network/broker authority)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib, json
from typing import Any, Callable, Mapping

POLICY_VERSION = "atlas_exit_policy.v1"
ONE = Decimal("1")
BREAKEVEN_GAIN = Decimal("0.05")
STAGE1_GAIN = Decimal("0.08")
STAGE2_GAIN = Decimal("0.15")
FLAT_LOW = Decimal("-0.015")
FLAT_HIGH = Decimal("0.015")
GEAR1_MAX_SESSIONS = 10
GEAR2_MAX_SESSIONS = 5


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def exact_third(original_quantity: Any, broker_increment: Any = None) -> tuple[Decimal | None, str | None]:
    """eToro fractional shares: preserve exact decimal thirds; optionally floor to supplied increment."""
    q = Decimal(str(original_quantity))
    if q <= 0:
        raise ValueError("original quantity must be positive")
    third = q / Decimal("3")
    if broker_increment is None:
        return third, None
    inc = Decimal(str(broker_increment))
    if inc <= 0:
        raise ValueError("broker increment must be positive")
    return (third // inc) * inc, str(inc)


def completed_sessions(entry_at: datetime, evaluation_at: datetime, schedule: Callable[[date], Mapping[str, Any]]) -> tuple[int | None, str | None]:
    """Count governed closes strictly after broker entry through evaluation instant."""
    if not entry_at or not evaluation_at:
        return None, "CALENDAR_DATA_INCOMPLETE"
    if entry_at.tzinfo is None: entry_at = entry_at.replace(tzinfo=timezone.utc)
    if evaluation_at.tzinfo is None: evaluation_at = evaluation_at.replace(tzinfo=timezone.utc)
    day, end, count = entry_at.date(), evaluation_at.date(), 0
    while day <= end:
        s = dict(schedule(day))
        if s.get("calendar_blocker") or s.get("authority_state") == "DATA_INCOMPLETE":
            return None, "CALENDAR_AUTHORITY_BLOCKER"
        close_raw = s.get("close_utc") or s.get("close")
        if s.get("is_trading_day") and close_raw:
            close = datetime.fromisoformat(str(close_raw).replace("Z", "+00:00"))
            if close.tzinfo is None: close = close.replace(tzinfo=timezone.utc)
            if close > entry_at and close <= evaluation_at:
                count += 1
        day = date.fromordinal(day.toordinal() + 1)
    return count, None


def preceding_session(earnings_date: date, schedule: Callable[[date], Mapping[str, Any]]) -> tuple[date | None, str | None]:
    d = date.fromordinal(earnings_date.toordinal() - 1)
    for _ in range(15):
        s = dict(schedule(d))
        if s.get("calendar_blocker"): return None, "CALENDAR_AUTHORITY_BLOCKER"
        if s.get("is_trading_day"): return d, None
        d = date.fromordinal(d.toordinal() - 1)
    return None, "CALENDAR_DATA_INCOMPLETE"


def evaluate_exit_ladder(*, entry_price: Any, current_price: Any, high_water: Any,
                         original_quantity: Any, remaining_quantity: Any,
                         stage1_state: str = "PENDING", stage2_state: str = "PENDING",
                         runner_state: str = "INACTIVE", current_stop: Any = None,
                         manual_stop_lock: bool = False, completed_sessions_held: int | None = None,
                         gear: int = 1, official_close: Any = None,
                         earnings_date: str | None = None, earnings_status: str | None = None,
                         evaluation_session: str | None = None, preceding_earnings_session: str | None = None,
                         calendar_digest: str | None = None, broker_increment: Any = None) -> dict[str, Any]:
    """Pure state-machine decision. Hard stop should be checked by caller first."""
    e, last, high = map(lambda x: Decimal(str(x)), (entry_price, current_price, high_water))
    oq, rq = Decimal(str(original_quantity)), Decimal(str(remaining_quantity))
    if min(e, last, high, oq, rq) <= 0: raise ValueError("prices and quantities must be positive")
    s1, increment = exact_third(oq, broker_increment)
    result = {"policy_version": POLICY_VERSION, "action": "KEEP", "stage": None,
              "sell_quantity": "0", "remaining_quantity": str(rq), "stop_before": None if current_stop is None else str(current_stop),
              "stop_after": None if current_stop is None else str(current_stop), "gear": gear,
              "completed_sessions_held": completed_sessions_held, "calendar_digest": calendar_digest,
              "advisory_only": True, "broker_confirmation_required": False, "reason_codes": []}
    if broker_increment is None:
        result["quantity_note"] = "ETORO FRACTIONAL — EXACT DECIMAL QUANTITY"
    # Confirmed earnings tomorrow: whole remainder SELL today. Missing date never forces.
    if earnings_date and str(earnings_status or "").lower() == "confirmed":
        if evaluation_session and preceding_earnings_session and evaluation_session == preceding_earnings_session:
            result.update(action="SELL", stage="EARNINGS", sell_quantity=str(rq), broker_confirmation_required=True,
                          reason_codes=["CONFIRMED_EARNINGS_TOMORROW"])
            result["packet_digest"] = digest(result); return result
    elif earnings_date and str(earnings_status or "").lower() == "projected":
        result.update(action="REVIEW", reason_codes=["EARNINGS_DATE_UNCONFIRMED"])
    elif earnings_status in {"stale", "conflicting"}:
        result.update(action="DATA INCOMPLETE", reason_codes=["EARNINGS_DATA_INCOMPLETE"])
    # Gear 2 always exits after five completed sessions. Gear 1 only flat at 10, inclusive binding ±1.5%.
    if completed_sessions_held is not None:
        if gear == 2 and completed_sessions_held >= GEAR2_MAX_SESSIONS:
            result.update(action="SELL", stage="TIME", sell_quantity=str(rq), broker_confirmation_required=True,
                          reason_codes=["GEAR2_FIVE_SESSION_MAX"])
            result["packet_digest"] = digest(result); return result
        if gear == 1 and completed_sessions_held >= GEAR1_MAX_SESSIONS and official_close is not None:
            ret = Decimal(str(official_close)) / e - ONE
            if FLAT_LOW <= ret <= FLAT_HIGH:
                result.update(action="SELL", stage="TIME", sell_quantity=str(rq), broker_confirmation_required=True,
                              reason_codes=["TEN_SESSION_FLAT", f"RETURN={ret}"])
                result["packet_digest"] = digest(result); return result
    elif calendar_digest is None:
        result["reason_codes"].append("CALENDAR_DATA_INCOMPLETE")
    # Earliest incomplete stage only.
    if high >= e * (ONE + STAGE1_GAIN) and stage1_state != "FILLED":
        result.update(action="SELL", stage="STAGE_1", sell_quantity=str(min(s1, rq)), broker_confirmation_required=True,
                      reason_codes=["EIGHT_PERCENT_LADDER"])
    elif high >= e * (ONE + STAGE2_GAIN) and stage1_state == "FILLED" and stage2_state != "FILLED":
        result.update(action="SELL", stage="STAGE_2", sell_quantity=str(min(s1, rq)), broker_confirmation_required=True,
                      reason_codes=["FIFTEEN_PERCENT_LADDER"])
    # +5% breakeven replaces legacy +1R. Advice remains valid even when stage advice is present.
    if high >= e * (ONE + BREAKEVEN_GAIN) and not manual_stop_lock:
        before = Decimal(str(current_stop)) if current_stop is not None else Decimal("0")
        after = max(before, e)
        if after > before:
            result["stop_after"] = str(after); result["stop_change"] = "BREAKEVEN_STOP_RAISED"
    if runner_state == "ACTIVE" and current_stop is not None:
        stop = Decimal(str(current_stop))
        if last <= stop:
            result.update(action="SELL", stage="RUNNER", sell_quantity=str(rq), broker_confirmation_required=True,
                          reason_codes=["RUNNER_STOP"])
    result["packet_digest"] = digest(result)
    return result


def runner_stop(current_stop: Any, candidate_stop: Any, current_price: Any, entry_price: Any, *, manual_stop_lock=False) -> Decimal:
    old, candidate, price, entry = map(lambda x: Decimal(str(x)), (current_stop, candidate_stop, current_price, entry_price))
    if manual_stop_lock: return old
    candidate = max(candidate, old, entry)
    if candidate >= price: raise ValueError("runner stop must remain below current price")
    return candidate

__all__ = [n for n in globals() if not n.startswith("_")]
