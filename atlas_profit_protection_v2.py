#!/usr/bin/env python3
"""Profit Protection v2 deterministic advisory policy.

Staging-only closure artifact. No production writes, no Telegram, no broker action,
no protected alpha imports.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any
import hashlib
import json

POLICY_VERSION = "profit_protection_v2_recommended_2026_07_11"  # formulas unchanged; report contract hardened for already-applied stops

POLICY_PARAMS = {
    "activation_min_peak_gain_pct": 8.0,
    "activation_min_peak_R": 1.0,
    "activation_min_holding_completed_sessions": 0,
    "severe_giveback_fraction_of_peak_profit": 0.35,
    "critical_current_gain_fraction_of_peak_gain": 0.50,
    "peak_gain_pct_for_critical_current_gain": 12.0,
    "standard_profit_floor_capture": 0.20,
    "severe_profit_floor_capture": 0.30,
    "breakeven_R_buffer": 0.10,
    "breakeven_pct_buffer": 0.005,
    "min_clearance_atr_fraction": 0.20,
    "min_clearance_price_fraction": 0.015,
    "ema_atr_buffer": 0.25,
    "swing_atr_buffer": 0.25,
    "near_target_pct": 3.0,
    "target_progress_for_trim": 0.90,
    "target_extend_sessions_above_target": 2,
    "stale_price_max_hours_after_expected_session_close": 36,
}


def sha_json(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def r2(x: float | None) -> float | None:
    if x is None:
        return None
    return round(float(x) + 1e-12, 2)


def pct(numer: float, denom: float) -> float:
    return (numer / denom * 100.0) if denom else 0.0


def valid_num(x: Any) -> bool:
    try:
        v = float(x)
        return isfinite(v)
    except Exception:
        return False


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    text = str(s).replace("Z", "+00:00")
    try:
        if "T" in text:
            d = datetime.fromisoformat(text)
        else:
            d = datetime.fromisoformat(text.replace(" ", "T"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


@dataclass(frozen=True)
class PolicyResult:
    ticker: str
    action: str
    current_price: float | None
    peak_price: float | None
    entry_price: float | None
    risk_per_share: float | None
    peak_gain_pct: float | None
    current_gain_pct: float | None
    giveback_pct_points: float | None
    giveback_fraction: float | None
    peak_R: float | None
    old_stop: float | None
    proposed_new_stop: float | None
    stop_formula: str
    old_target: float | None
    proposed_new_target: float | None
    target_decision: str
    why: str
    recheck_condition: str
    data_freshness: str
    provenance: dict[str, Any]
    rejected: list[dict[str, Any]]


def _candidate(name: str, value: float | None, formula: str, provenance: str) -> dict[str, Any]:
    return {"name": name, "value": r2(value), "formula": formula, "provenance": provenance}


def _reject(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    c = dict(candidate)
    c["rejected_reason"] = reason
    return c


def compute_atr14(bars: list[dict[str, Any]], idx: int) -> float | None:
    trs: list[float] = []
    start = max(0, idx - 20)
    for i in range(start, idx + 1):
        b = bars[i]
        if not all(valid_num(b.get(k)) for k in ("high", "low")):
            continue
        h, l = float(b["high"]), float(b["low"])
        if i > 0 and valid_num(bars[i - 1].get("close")):
            pc = float(bars[i - 1]["close"])
            tr = max(h - l, abs(h - pc), abs(l - pc))
        else:
            tr = h - l
        trs.append(tr)
    tail = trs[-14:]
    return sum(tail) / len(tail) if tail else None


def ema(values: list[float], n: int) -> float | None:
    if not values:
        return None
    a = 2 / (n + 1)
    z = values[0]
    for v in values[1:]:
        z = a * v + (1 - a) * z
    return z


def indicators_to_idx(bars: list[dict[str, Any]], idx: int) -> dict[str, float | None]:
    upto = bars[: idx + 1]
    closes = [float(b["close"]) for b in upto if valid_num(b.get("close"))]
    lows = [float(b["low"]) for b in upto[-10:] if valid_num(b.get("low"))]
    return {
        "atr14": compute_atr14(bars, idx),
        "ema10": ema(closes, 10),
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "confirmed_swing_low": min(lows) if lows else None,
    }


def find_entry_index(bars: list[dict[str, Any]], entry_at: str | None) -> int:
    if not bars:
        return 0
    d = parse_dt(entry_at)
    if not d:
        return 0
    entry_date = d.date().isoformat()
    for i, b in enumerate(bars):
        if str(b.get("session_date")) >= entry_date:
            return i
    return 0


def is_stale(last_provider_ts: str | None, captured_at: str | None, max_hours: float = 36.0) -> tuple[bool, str]:
    provider_dt = parse_dt(last_provider_ts)
    cap_dt = parse_dt(captured_at)
    if not provider_dt or not cap_dt:
        return True, "STALE_OR_MISSING timestamp missing"
    age = (cap_dt - provider_dt).total_seconds() / 3600.0
    if age > max_hours:
        return True, f"STALE provider_age_hours={age:.1f} max={max_hours}"
    return False, f"FRESH provider_ts={last_provider_ts} captured_at={captured_at} age_hours={age:.1f}"


def evaluate(
    *,
    ticker: str,
    entry: float | None,
    old_stop: float | None,
    old_target: float | None,
    bars: list[dict[str, Any]],
    entry_at: str | None = None,
    original_stop: float | None = None,
    captured_at: str | None = None,
    provider_name: str | None = None,
    force_stale: bool = False,
) -> PolicyResult:
    ticker = str(ticker).upper()
    rejected: list[dict[str, Any]] = []
    if not (valid_num(entry) and valid_num(old_stop) and bars):
        return PolicyResult(ticker, "HOLD", None, None, float(entry) if valid_num(entry) else None, None, None, None, None, None, None, float(old_stop) if valid_num(old_stop) else None, None, "INCOMPLETE", float(old_target) if valid_num(old_target) else None, None, "KEEP", "missing entry/stop/bars; fail closed", "refresh provider packet and evidence bake", "STALE_OR_MISSING", {"policy_version": POLICY_VERSION}, rejected)
    entry = float(entry)  # type: ignore[arg-type]
    old_stop = float(old_stop)  # type: ignore[arg-type]
    old_target = float(old_target) if valid_num(old_target) else None
    eidx = find_entry_index(bars, entry_at)
    post = bars[eidx:]
    last = post[-1]
    current = float(last.get("close")) if valid_num(last.get("close")) else None
    if current is None:
        return PolicyResult(ticker, "HOLD", None, None, entry, None, None, None, None, None, None, old_stop, None, "INCOMPLETE", old_target, None, "KEEP", "missing current close; fail closed", "refresh price evidence", "STALE_OR_MISSING price", {"policy_version": POLICY_VERSION}, rejected)
    stale, freshness = is_stale(last.get("provider_timestamp"), captured_at, POLICY_PARAMS["stale_price_max_hours_after_expected_session_close"])
    if force_stale or stale:
        return PolicyResult(ticker, "HOLD", r2(current), None, entry, None, None, r2(pct(current-entry, entry)), None, None, None, old_stop, None, "STALE_FAIL_CLOSED", old_target, None, "KEEP", "stale or missing price evidence; no advisory stop/target change", "refresh provider packet", "STALE_FAIL_CLOSED " + freshness, {"policy_version": POLICY_VERSION, "provider": provider_name}, rejected)
    highs = [float(b["high"]) for b in post if valid_num(b.get("high"))]
    peak = max(highs) if highs else current
    orig_stop = float(original_stop) if valid_num(original_stop) else old_stop
    raw_risk = entry - min(orig_stop, entry * (1.0 - 0.02))
    risk = max(raw_risk, entry * 0.02)
    peak_profit = max(0.0, peak - entry)
    cur_profit = current - entry
    peak_gain_pct = pct(peak_profit, entry)
    current_gain_pct = pct(cur_profit, entry)
    giveback_abs = max(0.0, peak - current)
    giveback_fraction = giveback_abs / peak_profit if peak_profit > 0 else 0.0
    peak_R = peak_profit / risk if risk > 0 else 0.0
    ind = indicators_to_idx(bars, len(bars) - 1)
    atr = ind.get("atr14")
    clearance = None
    if atr is not None:
        clearance = max(POLICY_PARAMS["min_clearance_atr_fraction"] * atr, POLICY_PARAMS["min_clearance_price_fraction"] * current)
    else:
        clearance = POLICY_PARAMS["min_clearance_price_fraction"] * current
    max_allowed = current - clearance
    activated = peak_gain_pct >= POLICY_PARAMS["activation_min_peak_gain_pct"] and peak_R >= POLICY_PARAMS["activation_min_peak_R"]
    severe = activated and (giveback_fraction >= POLICY_PARAMS["severe_giveback_fraction_of_peak_profit"] or (peak_gain_pct >= POLICY_PARAMS["peak_gain_pct_for_critical_current_gain"] and current_gain_pct <= peak_gain_pct * POLICY_PARAMS["critical_current_gain_fraction_of_peak_gain"]))
    capture = POLICY_PARAMS["severe_profit_floor_capture"] if severe else POLICY_PARAMS["standard_profit_floor_capture"]
    candidates = [
        _candidate("old_stop", old_stop, "canonical current DB stop", "trades.stop_loss"),
        _candidate("breakeven_buffer", entry + max(POLICY_PARAMS["breakeven_R_buffer"] * risk, POLICY_PARAMS["breakeven_pct_buffer"] * entry), "entry + max(0.10R, 0.5% entry)", "entry and reconstructed original risk"),
        _candidate("profit_floor", entry + capture * peak_profit, f"entry + {capture:.0%} * (peak_high - entry)", "provider completed-bar peak high"),
    ]
    if atr is not None:
        candidates.append(_candidate("volatility_clearance", current - clearance, "current_close - max(0.20*ATR14, 1.5%*current_close)", "provider completed close and ATR14"))
        if ind.get("ema20") is not None:
            candidates.append(_candidate("ema20_buffer", float(ind["ema20"]) - POLICY_PARAMS["ema_atr_buffer"] * atr, "EMA20 - 0.25*ATR14", "provider daily bars through current close"))
        if ind.get("confirmed_swing_low") is not None:
            candidates.append(_candidate("swing_buffer", float(ind["confirmed_swing_low"]) - POLICY_PARAMS["swing_atr_buffer"] * atr, "confirmed 10-session swing low - 0.25*ATR14", "provider completed daily lows"))
    valid: list[dict[str, Any]] = []
    for c in candidates:
        v = c.get("value")
        if v is None:
            rejected.append(_reject(c, "missing inputs")); continue
        v = float(v)
        if v < old_stop - 0.0001:
            rejected.append(_reject(c, "REJECTED_WIDENING below old stop")); continue
        if v >= current:
            rejected.append(_reject(c, "REJECTED_AT_OR_ABOVE_PRICE")); continue
        if v > max_allowed + 0.0001:
            rejected.append(_reject(c, "REJECTED_MIN_VOLATILITY_CLEARANCE")); continue
        valid.append(c)
    proposed_stop = max([float(c["value"]) for c in valid], default=old_stop if old_stop < current else None)
    if proposed_stop is not None and proposed_stop < old_stop:
        proposed_stop = old_stop
    if proposed_stop is not None and proposed_stop >= current:
        rejected.append(_reject(_candidate("selected_stop", proposed_stop, "max(valid candidates)", "derived"), "REJECTED_AT_OR_ABOVE_PRICE"))
        proposed_stop = None
    stop_formula = "max(valid non-widening candidates below current minus volatility clearance): old_stop, breakeven_buffer, profit_floor, volatility_clearance, EMA20_buffer, swing_buffer"
    target_decision = "KEEP"
    proposed_target = old_target
    target_reason = "target not reached; canonical target retained"
    target_hit = bool(old_target is not None and peak >= old_target)
    near_target = bool(old_target is not None and current >= old_target * (1 - POLICY_PARAMS["near_target_pct"] / 100.0))
    progress = ((current - entry) / (old_target - entry)) if old_target and old_target > entry else 0.0
    if target_hit:
        closes_above = 0
        for b in reversed(post):
            if valid_num(b.get("close")) and float(b["close"]) > old_target:
                closes_above += 1
            else:
                break
        if closes_above >= POLICY_PARAMS["target_extend_sessions_above_target"] and atr is not None:
            target_decision = "EXTEND"
            proposed_target = max(old_target, current + 1.5 * atr, peak + 0.5 * atr)
            target_reason = "target reached and two completed closes above target; advisory extension only"
        else:
            target_decision = "TARGET REACHED"
            proposed_target = old_target
            target_reason = "verified high reached canonical target; no automatic target mutation"
    elif severe and current_gain_pct > 0 and atr is not None and old_target and (old_target - current) > 2 * atr:
        target_decision = "LOWER"
        proposed_target = max(current + 1.0 * atr, entry + 1.0 * risk)
        proposed_target = min(proposed_target, old_target)
        target_reason = "severe giveback with target more than 2 ATR away; advisory lower-review only"
    # action mapping
    if old_stop is not None and current <= old_stop:
        action = "EXIT REVIEW"
        why = "current verified close is at/below old stop"
    elif proposed_stop is not None and current <= proposed_stop:
        action = "EXIT REVIEW"
        why = "current verified close is at/below proposed protective stop"
    elif target_decision == "TARGET REACHED" or near_target or progress >= POLICY_PARAMS["target_progress_for_trim"]:
        action = "TRIM REVIEW"
        why = target_reason
    elif severe:
        action = "PROTECT PROFIT"
        why = f"activated; peak gain {peak_gain_pct:.2f}% / {peak_R:.2f}R and giveback {giveback_fraction:.1%} of peak profit"
    elif activated and proposed_stop is not None and proposed_stop > old_stop + 0.004:
        action = "TIGHTEN"
        why = f"activated; peak gain {peak_gain_pct:.2f}% / {peak_R:.2f}R with valid non-widening stop improvement"
    else:
        action = "HOLD"
        why = "activation thresholds not met or no safe stop improvement"
    recheck = "after each completed NYSE session; intraday only if provider current and prior high-water already breached"
    prov = {
        "policy_version": POLICY_VERSION,
        "provider": provider_name,
        "last_provider_timestamp": last.get("provider_timestamp"),
        "session_date": last.get("session_date"),
        "atr14": r2(atr),
        "ema20": r2(ind.get("ema20")),
        "confirmed_swing_low": r2(ind.get("confirmed_swing_low")),
        "clearance": r2(clearance),
        "max_allowed_stop": r2(max_allowed),
        "valid_stop_candidates": valid,
        "target_reason": target_reason,
        "policy_digest": sha_json({"version": POLICY_VERSION, "params": POLICY_PARAMS}),
    }
    return PolicyResult(ticker, action, r2(current), r2(peak), r2(entry), r2(risk), r2(peak_gain_pct), r2(current_gain_pct), r2(pct(giveback_abs, entry)), r2(giveback_fraction), r2(peak_R), r2(old_stop), r2(proposed_stop), stop_formula, r2(old_target), r2(proposed_target), target_decision, why, recheck, freshness, prov, rejected)


def as_dict(result: PolicyResult) -> dict[str, Any]:
    return asdict(result)


__all__ = ["POLICY_VERSION", "POLICY_PARAMS", "PolicyResult", "evaluate", "as_dict", "indicators_to_idx", "find_entry_index"]


def advisory_contract(result: PolicyResult) -> dict[str, Any]:
    """Human-report contract: only actionable actions expose recommended changes.

    Internal candidates remain in result.provenance['valid_stop_candidates'] and
    result.rejected for audit JSON. HOLD/INCOMPLETE never displays an inactive
    candidate as a recommendation.
    """
    d = as_dict(result)
    action = d["action"]
    active_action = action in {"TIGHTEN", "PROTECT PROFIT", "TRIM REVIEW", "EXIT REVIEW"}
    stop_supported = action in {"TIGHTEN", "PROTECT PROFIT", "TRIM REVIEW", "EXIT REVIEW"}
    target_supported = action in {"TRIM REVIEW", "PROTECT PROFIT", "EXIT REVIEW"} and d["target_decision"] in {"LOWER", "EXTEND", "TARGET REACHED"}
    data_ok = not str(d.get("data_freshness") or "").startswith("STALE")
    recommended_stop = d["proposed_new_stop"] if active_action and stop_supported and data_ok else None
    recommended_target = d["proposed_new_target"] if active_action and target_supported and data_ok else None
    if recommended_stop is not None and d["old_stop"] is not None and abs(float(recommended_stop) - float(d["old_stop"])) < 0.005:
        # Already applied canonical stop: do not repeat the same recommendation in human reports.
        recommended_stop = None
    if recommended_target is not None and d["old_target"] is not None and abs(float(recommended_target) - float(d["old_target"])) < 0.005:
        # Already-applied or unchanged canonical target: do not repeat as a recommendation.
        recommended_target = None
    d.update({
        "recommended_stop": recommended_stop,
        "recommended_stop_display": "NO CHANGE" if recommended_stop is None else f"${recommended_stop:,.2f}",
        "recommended_target": recommended_target,
        "recommended_target_display": "NO CHANGE" if recommended_target is None else f"${recommended_target:,.2f}",
        "approval_required": "YES" if (recommended_stop is not None or recommended_target is not None or action in {"PROTECT PROFIT", "TRIM REVIEW", "EXIT REVIEW"}) else "NO",
        "audit_only_candidates_retained": True,
    })
    return d


def render_human_block(results: list[PolicyResult]) -> str:
    lines = ["PROFIT PROTECTION v2 — ADVISORY ONLY", ""]
    for res in results:
        d = advisory_contract(res)
        old_stop = "N/A" if d["old_stop"] is None else f"${d['old_stop']:,.2f}"
        old_target = "N/A" if d["old_target"] is None else f"${d['old_target']:,.2f}"
        lines += [
            f"{d['ticker']}",
            f"ACTION: {d['action']}",
            f"OLD STOP: {old_stop}",
            f"RECOMMENDED STOP: {d['recommended_stop_display']}",
            f"OLD TARGET: {old_target}",
            f"RECOMMENDED TARGET: {d['recommended_target_display']}",
            f"WHY: {d['why']}",
            f"DATA FRESHNESS: {d['data_freshness']}",
            f"APPROVAL REQUIRED: {d['approval_required']}",
            "",
        ]
    return "\n".join(lines).rstrip()


def latest_evidence_snapshot(default_dir: str = "/Users/yasser/Library/Application Support/Atlas/position_evidence_bake/snapshots") -> str | None:
    from pathlib import Path
    files = sorted(Path(default_dir).glob("snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


def _safe_num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except Exception:
        return {}


def _row_levels(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    sig = _safe_json(row.get("signal_json"))
    rc = sig.get("risk_card") if isinstance(sig.get("risk_card"), dict) else {}
    entry = _safe_num(row.get("entry_price")) or _safe_num(row.get("trigger_price")) or _safe_num(row.get("reference_price")) or _safe_num(sig.get("entry_price"))
    stop = _safe_num(row.get("stop_loss")) or _safe_num(rc.get("stop_loss"))
    target = _safe_num(row.get("target_price")) or _safe_num(rc.get("target_price"))
    if entry and stop and not target and entry > stop:
        target = entry + 2 * (entry - stop)
    return entry, stop, target


def _original_stop_from_notes(row: dict[str, Any]) -> float | None:
    import re
    notes = str(row.get("notes") or "")
    for pat in (r"Atlas v2 entry:.*?stop\s+\$?([0-9]+(?:\.[0-9]+)?)", r"; stop\s+\$?([0-9]+(?:\.[0-9]+)?)", r"implied stop\s+([0-9]+(?:\.[0-9]+)?)"):
        m = re.search(pat, notes, re.I | re.S)
        if m:
            return float(m.group(1))
    return _safe_num(row.get("stop_loss"))


def evaluate_current_open_from_snapshot(snapshot_path: str | None = None) -> list[PolicyResult]:
    from pathlib import Path
    path = snapshot_path or latest_evidence_snapshot()
    if not path:
        return []
    snap = json.loads(Path(path).read_text())
    out: list[PolicyResult] = []
    provider = snap.get("provider") or {}
    for row in snap.get("buckets", {}).get("current_open", []):
        ticker = str(row.get("ticker") or "").upper()
        entry, stop, target = _row_levels(row)
        bars = list((provider.get(ticker) or {}).get("bars") or [])
        source = provider.get(ticker) or {}
        out.append(evaluate(
            ticker=ticker,
            entry=entry,
            old_stop=stop,
            old_target=target,
            bars=bars,
            entry_at=row.get("entry_at") or row.get("updated_at"),
            original_stop=_original_stop_from_notes(row),
            captured_at=snap.get("captured_at"),
            provider_name=f"{source.get('provider')}:{source.get('dataset')}",
        ))
    return out


def render_report_block_from_snapshot(snapshot_path: str | None = None) -> str:
    results = evaluate_current_open_from_snapshot(snapshot_path)
    if not results:
        return ""
    return render_human_block(results)


# Hardening override: live advisory verifies canonical OPEN state via read-only DB.
def canonical_open_rows(db_path: str = "/Users/yasser/scripts/atlas.db") -> dict[int, dict[str, Any]]:
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        rows = con.execute("SELECT id,ticker,status,entry_price,entry_at,stop_loss,target_price,notes FROM trades").fetchall()
        cols = ["id", "ticker", "status", "entry_price", "entry_at", "stop_loss", "target_price", "notes"]
        return {int(r[0]): dict(zip(cols, r)) for r in rows}
    finally:
        con.close()


def evaluate_current_open_from_snapshot(snapshot_path: str | None = None, db_path: str = "/Users/yasser/scripts/atlas.db") -> list[PolicyResult]:
    from pathlib import Path
    path = snapshot_path or latest_evidence_snapshot()
    if not path:
        return []
    snap = json.loads(Path(path).read_text())
    canonical_rows = canonical_open_rows(db_path)
    out: list[PolicyResult] = []
    provider = snap.get("provider") or {}
    for row in snap.get("buckets", {}).get("current_open", []):
        trade_id = int(row.get("id") or 0)
        dbrow = canonical_rows.get(trade_id)
        if not dbrow or dbrow.get("status") != "OPEN":
            continue
        ticker = str(dbrow.get("ticker") or row.get("ticker") or "").upper()
        entry = _safe_num(dbrow.get("entry_price"))
        stop = _safe_num(dbrow.get("stop_loss"))
        target = _safe_num(dbrow.get("target_price"))
        bars = list((provider.get(ticker) or {}).get("bars") or [])
        source = provider.get(ticker) or {}
        out.append(evaluate(
            ticker=ticker,
            entry=entry,
            old_stop=stop,
            old_target=target,
            bars=bars,
            entry_at=dbrow.get("entry_at") or row.get("entry_at") or row.get("updated_at"),
            original_stop=_original_stop_from_notes(row),
            captured_at=snap.get("captured_at"),
            provider_name=f"{source.get('provider')}:{source.get('dataset')}",
        ))
    return out


def render_report_block_from_snapshot(snapshot_path: str | None = None, db_path: str = "/Users/yasser/scripts/atlas.db") -> str:
    """Render the PP report leaf; evaluation remains an unconditional producer."""
    from atlas_holding_state_consumer_projection import select_leaf
    def legacy_leaf() -> str:
        results = evaluate_current_open_from_snapshot(snapshot_path, db_path=db_path)
        return render_human_block(results) if results else ""
    return select_leaf(
        "DAILY_PP_HOLDING_SECTIONS",
        legacy_leaf,
        reference="atlas_profit_protection_v2.render_report_block_from_snapshot",
        projector=lambda projection: "\n".join(projection.lines),
    )

