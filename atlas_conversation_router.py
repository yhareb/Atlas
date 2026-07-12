#!/usr/bin/env python3
"""Staging-only Atlas conversational advisory router.

This module is an additive adapter.  It never imports or changes protected alpha
logic, never writes SQLite, and has no messaging/Telegram integration.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

FRESH_TFE_REQUIRED = "FRESH_TFE_REQUIRED"
CONVERSATIONAL_CONFIRMATION = "CONVERSATIONAL_CONFIRMATION"
DEFAULT_FRESHNESS_SECONDS = 5 * 60
DEFAULT_GAP_FRESHNESS_SECONDS = 3 * 60
DEFAULT_PRICE_MOVE_PCT = 1.0
DEFAULT_ATR_MOVE_FRACTION = 0.25
MAX_TIMEOUT_SECONDS = 10.0


class RouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteResult:
    route: str
    ticker: str
    snapshot: Mapping[str, Any]
    metrics: Mapping[str, Any]
    news: tuple[Mapping[str, Any], ...]
    news_status: str
    source: str
    latency_seconds: float
    latency_label: str = "router harness latency; not a live provider benchmark"
    invalidation_reasons: tuple[str, ...] = ()
    fresh_run_occurred: bool = False


@dataclass(frozen=True)
class RouterPolicy:
    regular_ttl_seconds: int = DEFAULT_FRESHNESS_SECONDS
    gap_ttl_seconds: int = DEFAULT_GAP_FRESHNESS_SECONDS
    price_move_pct: float = DEFAULT_PRICE_MOVE_PCT
    atr_move_fraction: float = DEFAULT_ATR_MOVE_FRACTION
    gap_name_threshold_pct: float = 8.0


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def calculate_metrics(snapshot: Mapping[str, Any], now: datetime,
                      current_price: Optional[float] = None,
                      policy: RouterPolicy = RouterPolicy()) -> Mapping[str, Any]:
    """Pure deterministic calculations; does not infer unavailable values."""
    timestamp = snapshot.get("timestamp") or snapshot.get("generated_at")
    age = max(0.0, (now.astimezone(timezone.utc) - _utc(timestamp)).total_seconds()) if timestamp else None
    entry, stop = _num(snapshot.get("entry")), _num(snapshot.get("stop"))
    if entry is None:
        entry = _num(snapshot.get("entry_price"))
    if stop is None:
        stop = _num(snapshot.get("stop_loss"))
    price = _num(current_price)
    analysis_price = _num(snapshot.get("price_at_analysis"))
    if analysis_price is None:
        analysis_price = entry
    target = _num(snapshot.get("analyst_target"))
    risk = (entry - stop) if entry is not None and stop is not None else None
    rr = ((target - entry) / risk) if target is not None and entry is not None and risk and risk > 0 else None
    movement = ((price - analysis_price) / analysis_price * 100.0) if price is not None and analysis_price else None
    prior_close = _num(snapshot.get("prior_close"))
    gap = _num(snapshot.get("gap_pct"))
    if gap is None and entry is not None and prior_close:
        gap = (entry - prior_close) / prior_close * 100.0
    atr = _num(snapshot.get("atr"))
    atr_move = abs(price - analysis_price) / atr if price is not None and analysis_price is not None and atr else None
    is_gap_name = gap is not None and abs(gap) >= policy.gap_name_threshold_pct
    ttl = policy.gap_ttl_seconds if is_gap_name else policy.regular_ttl_seconds
    return MappingProxyType({
        "age_seconds": age,
        "fresh": age is not None and age <= ttl,
        "ttl_seconds": ttl,
        "price_movement_pct": movement,
        "reward_risk": rr,
        "gap_pct": gap,
        "risk_per_share": risk,
        "atr_movement_fraction": atr_move,
        "is_gap_name": is_gap_name,
    })


def immutable_envelope(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Defensive top-level immutable copy for injected/saved evidence."""
    return MappingProxyType(json.loads(json.dumps(dict(data))))


def _parse_signal_row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["entry"] = out.get("entry_price")
    out["stop"] = out.get("stop_loss")
    score = out.get("score")
    if isinstance(score, int):
        out["score"] = f"{score}/4 Pillars"
    warnings = out.get("warnings")
    if isinstance(warnings, str):
        try:
            parsed = json.loads(warnings)
            if isinstance(parsed, dict):
                out.update({k: v for k, v in parsed.items() if k not in out or out[k] is None})
            else:
                out["warnings"] = parsed
        except json.JSONDecodeError:
            pass
    return out


def read_latest_snapshot(db_path: str | Path, ticker: str) -> Optional[Mapping[str, Any]]:
    """Read allowlisted tables through a URI read-only/query-only connection."""
    uri = f"file:{Path(db_path).resolve()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, timeout=1.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        row = con.execute(
            "SELECT * FROM signals WHERE UPPER(ticker)=? ORDER BY datetime(timestamp) DESC,id DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
        if row:
            return immutable_envelope(_parse_signal_row(row))
        # report_snapshots has no ticker column: bounded newest-first search only.
        rows = con.execute(
            "SELECT generated_at,inputs_manifest_json FROM report_snapshots "
            "ORDER BY datetime(generated_at) DESC,id DESC LIMIT 20"
        ).fetchall()
        for report in rows:
            try:
                manifest = json.loads(report["inputs_manifest_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            candidates = manifest if isinstance(manifest, list) else manifest.get("signals", manifest.get("tickers", []))
            if isinstance(candidates, dict):
                candidates = [candidates]
            for item in candidates if isinstance(candidates, list) else []:
                if isinstance(item, dict) and str(item.get("ticker", "")).upper() == ticker.upper():
                    result = dict(item)
                    result.setdefault("timestamp", report["generated_at"])
                    return immutable_envelope(result)
        return None
    finally:
        con.close()


def _bounded_call(fn: Callable[[str], Any], ticker: str, timeout: float) -> Any:
    timeout = min(max(float(timeout), 0.001), MAX_TIMEOUT_SECONDS)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atlas-targeted")
    future = pool.submit(fn, ticker)  # API admits exactly one ticker; never a universe/full scan.
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        future.cancel()
        raise RouterError(f"targeted call timed out after {timeout:g}s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def classify(prompt: str, snapshot: Optional[Mapping[str, Any]], metrics: Mapping[str, Any], *, policy: RouterPolicy = RouterPolicy(), source_conflict: bool = False, catalyst_changed: bool = False, regime_changed: bool = False, boundary_crossed: bool = False) -> tuple[str, tuple[str, ...]]:
    text = prompt.lower()
    confirmation = bool(re.search(r"\b(confirm|why|explain|still|that signal|this signal|should i|do i|act|chase|wait|trust|is .* a buy)\b", text))
    referential_signal = "that signal" in text or "this signal" in text
    fresh_intent = bool(re.search(r"\b(now|current|currently|today|fresh|rerun|re-run|analy[sz]e|check|scout|price|score|entry|stop|target|rsi|macd|rvol|signal|pillars?)\b", text)) and not (confirmation and referential_signal)
    reasons = []
    if snapshot is None: reasons.append("no_recent_structured_result")
    if fresh_intent: reasons.append("exact_or_fresh_numbers_requested")
    if snapshot is not None and not metrics.get("fresh"): reasons.append("stale_result")
    if metrics.get("price_movement_pct") is not None and abs(metrics["price_movement_pct"]) >= policy.price_move_pct: reasons.append("material_price_move_pct")
    if metrics.get("atr_movement_fraction") is not None and metrics["atr_movement_fraction"] >= policy.atr_move_fraction: reasons.append("material_price_move_atr")
    if source_conflict: reasons.append("conflicting_sources")
    if catalyst_changed: reasons.append("material_catalyst_change")
    if regime_changed: reasons.append("regime_change")
    if boundary_crossed: reasons.append("deterministic_boundary_crossed")
    return (FRESH_TFE_REQUIRED, tuple(reasons)) if reasons else (CONVERSATIONAL_CONFIRMATION if confirmation or snapshot else FRESH_TFE_REQUIRED, ())


class ConversationRouter:
    def __init__(self, db_path: Optional[str | Path] = None,
                 tfe_runner: Optional[Callable[[str], Mapping[str, Any]]] = None,
                 news_fetcher: Optional[Callable[[str], Any]] = None,
                 timeout_seconds: float = 3.0, policy: RouterPolicy = RouterPolicy()):
        self.db_path = db_path
        self.tfe_runner = tfe_runner
        self.news_fetcher = news_fetcher
        self.timeout_seconds = min(float(timeout_seconds), MAX_TIMEOUT_SECONDS)
        self.policy = policy

    def route(self, prompt: str, ticker: str, *, envelope: Optional[Mapping[str, Any]] = None,
              now: Optional[datetime] = None, current_price: Optional[float] = None,
              targeted_news: bool = False, source_conflict: bool = False, catalyst_changed: bool = False,
              regime_changed: bool = False, boundary_crossed: bool = False) -> RouteResult:
        started = time.perf_counter()
        ticker = ticker.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
            raise RouterError("invalid ticker")
        now = now or datetime.now(timezone.utc)
        snapshot = immutable_envelope(envelope) if envelope is not None else (
            read_latest_snapshot(self.db_path, ticker) if self.db_path else None)
        metrics = calculate_metrics(snapshot or {}, now, current_price, self.policy)
        route, invalidation_reasons = classify(prompt, snapshot, metrics, policy=self.policy, source_conflict=source_conflict, catalyst_changed=catalyst_changed, regime_changed=regime_changed, boundary_crossed=boundary_crossed)
        source = "immutable envelope" if envelope is not None else "SQLite read-only"
        fresh_run_occurred = False
        if route == FRESH_TFE_REQUIRED:
            if self.tfe_runner is None:
                raise RouterError("fresh TFE required but no injected single-ticker runner is configured")
            fresh = _bounded_call(self.tfe_runner, ticker, self.timeout_seconds)
            if not isinstance(fresh, Mapping):
                raise RouterError("single-ticker runner returned a non-mapping result")
            snapshot = immutable_envelope(fresh)
            metrics = calculate_metrics(snapshot, now, current_price, self.policy)
            source = "injected single-ticker TFE runner"
            fresh_run_occurred = True
        news: tuple[Mapping[str, Any], ...] = ()
        news_status = "not requested"
        if targeted_news:
            if self.news_fetcher is None:
                news_status = "unavailable; advisory continues without targeted news"
            else:
                try:
                    raw = _bounded_call(self.news_fetcher, ticker, self.timeout_seconds)
                    items = raw if isinstance(raw, (list, tuple)) else []
                    news = tuple(immutable_envelope(x) for x in items[:5] if isinstance(x, Mapping))
                    news_status = "ok" if news else "no targeted results; advisory fallback used"
                except Exception as exc:  # news is enrichment, never a blocker
                    news_status = f"unavailable; advisory fallback used ({type(exc).__name__})"
        return RouteResult(route, ticker, snapshot or immutable_envelope({}), metrics, news,
                           news_status, source, time.perf_counter() - started,
                           invalidation_reasons=tuple(invalidation_reasons), fresh_run_occurred=fresh_run_occurred)


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    return "N/A" if value is None else f"{float(value):.{digits}f}{suffix}"


def action_now(result: RouteResult) -> str:
    s, m = result.snapshot, result.metrics
    raw = str(s.get("signal") or "").upper()
    if "AVOID" in raw: return "AVOID"
    if bool(s.get("momentum_weak")) or (m.get("gap_pct") is not None and m["gap_pct"] >= 10) or (m.get("reward_risk") is not None and m["reward_risk"] < 1): return "WAIT — DO NOT CHASE"
    return "BUY NOW" if "BUY" in raw else "REVIEW"


def render_contract(result: RouteResult) -> str:
    s, m = result.snapshot, result.metrics
    signal = str(s.get("signal", "N/A"))
    if s.get("size") and str(s.get("size")).lower() not in signal.lower(): signal += " " + str(s.get("size"))
    why=[]
    if m.get("gap_pct") is not None: why.append(f"gap {_fmt(m.get('gap_pct'),1,'%')}")
    if s.get("rsi") is not None: why.append(f"RSI {_fmt(s.get('rsi'),0)}")
    if s.get("momentum_weak"): why.append("weak momentum")
    if s.get("relative_strength_pass") is False: why.append("failed relative strength")
    if m.get("reward_risk") is not None: why.append(f"reward/risk {_fmt(m.get('reward_risk'),4)}")
    return "\n".join([
      f"ATLAS ADVISORY — {result.ticker}", f"ROUTE: {result.route}",
      "TFE CLASSIFICATION:", f"{signal}, {s.get('score','N/A')} | timestamp {s.get('timestamp',s.get('generated_at','N/A'))} | source {result.source}",
      "ACTION NOW:", action_now(result), "WHY:", "; ".join(why) if why else "No additional sourced caution flags.",
      "RECHECK:", "stabilization, pullback improving reward/risk, or fresh TFE run after material change",
      "DATA FRESHNESS:", f"{_fmt(m.get('age_seconds'),0,'s old')} / TTL {_fmt(m.get('ttl_seconds'),0,'s')} | fresh_run_occurred={str(result.fresh_run_occurred).lower()} | invalidated_by={','.join(result.invalidation_reasons) or 'none'}",
      f"ENTRY / STOP: ${_fmt(s.get('entry',s.get('entry_price')))} / ${_fmt(s.get('stop',s.get('stop_loss')))}",
      f"REWARD/RISK: {_fmt(m.get('reward_risk'),4)} | GAP: {_fmt(m.get('gap_pct'),2,'%')}", f"TARGETED NEWS: {result.news_status}",
      f"LATENCY: {result.latency_seconds:.4f}s ({result.latency_label})"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("prompt")
    parser.add_argument("--db")
    parser.add_argument("--envelope")
    args = parser.parse_args()
    envelope = json.loads(Path(args.envelope).read_text()) if args.envelope else None
    # CLI intentionally cannot run production TFE implicitly.
    result = ConversationRouter(db_path=args.db).route(args.prompt, args.ticker, envelope=envelope)
    print(render_contract(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

try:
    from atlas_quiver_decision_envelope import render_decision_block as _quiver_render_decision_block, apply_quiver_review_overlay as _quiver_apply_overlay
except Exception:
    _quiver_render_decision_block = None
    _quiver_apply_overlay = None


def quiver_consumer_decision_block(raw_tfe_result, quiver_context):
    """Shared consumer shim: render exactly the authoritative Quiver decision envelope."""
    if not _quiver_apply_overlay or not _quiver_render_decision_block:
        return "QUIVER DATA UNAVAILABLE"
    return _quiver_render_decision_block(_quiver_apply_overlay(raw_tfe_result or {}, quiver_context or {}))


# Daily Holdings Re-Underwriting final release hook (advisory-only, packet consumer).
def holdings_reunderwrite_conversation_answer(ticker, packet):
    t=str(ticker or '').upper()
    for p in (packet or {}).get('positions') or []:
        if str(p.get('ticker') or '').upper()==t:
            return {'ticker':t,'daily_reunderwrite_action':p.get('action'),'reason_codes':p.get('reason_codes'),'recheck_condition':p.get('recheck_condition'),'authority':'ADVISORY_ONLY'}
    return {'ticker':t,'daily_reunderwrite_action':'DATA INCOMPLETE','reason_codes':['NO_PACKET_POSITION'],'authority':'ADVISORY_ONLY'}
