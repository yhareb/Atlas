#!/usr/bin/env python3
"""Atlas production conversational determinism router — closure v1 staged build.

No LLM may calculate or select trading numbers/actions. This module classifies
intent, selects an authoritative packet, validates freshness/provenance, and
renders only deterministic fields requested by the user.
"""
from __future__ import annotations

import argparse, json, re, sqlite3, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from atlas_conversation_schemas import (
    Authority, PriceInput, RouterError, SourceField, attach_digest, digest_obj,
    field, freeze_mapping, normalize_raw_tfe, parse_dt, preserve_strong_action,
    validate_freshness, validate_holdings_packet, verify_digest,
)
from atlas_holdings_final_action import build_merged_packet, render_ticker_answer

FRESH_TFE_REQUIRED = "FRESH_TFE_REQUIRED"
HOLDINGS_PACKET_REQUIRED = "HOLDINGS_PACKET_REQUIRED"
PERME_PACKET_REQUIRED = "PERME_PACKET_REQUIRED"
QUIVER_PACKET_REQUIRED = "QUIVER_PACKET_REQUIRED"
FDA_CONTEXT_REQUIRED = "FDA_CONTEXT_REQUIRED"
CONVERSATIONAL_CONFIRMATION = "CONVERSATIONAL_CONFIRMATION"
FAIL_CLOSED = "FAIL_CLOSED"

DEFAULT_FRESHNESS_SECONDS = 300
DEFAULT_GAP_FRESHNESS_SECONDS = 180
MAX_TIMEOUT_SECONDS = 45.0
STRONG_HOLDING_ACTIONS = {"SELL NOW", "EXIT REVIEW", "TRIM REVIEW", "HOLD TIGHT", "HOLD", "DATA INCOMPLETE"}

@dataclass(frozen=True)
class RouterPolicy:
    regular_ttl_seconds: int = DEFAULT_FRESHNESS_SECONDS
    gap_ttl_seconds: int = DEFAULT_GAP_FRESHNESS_SECONDS
    holdings_ttl_seconds: int = 36 * 3600
    price_move_pct: float = 1.0

@dataclass(frozen=True)
class RouteResult:
    route: str
    ticker: str
    source: str
    packet: Mapping[str, Any]
    structured: Mapping[str, Any]
    rendered_answer: str
    freshness: str
    invalidation_reasons: tuple[str, ...]
    fresh_run_occurred: bool
    latency_seconds: float


def _num(v: Any) -> float | None:
    try:
        if isinstance(v, Mapping):
            v = v.get("value")
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def _field(packet: Mapping[str, Any], key: str) -> SourceField | None:
    raw = packet.get(key)
    if isinstance(raw, Mapping) and "value" in raw:
        return SourceField(raw.get("value"), str(raw.get("authority") or "UNKNOWN"), str(raw.get("source") or "UNKNOWN"), raw.get("timestamp"), raw.get("freshness"))
    if raw is None:
        return None
    return SourceField(raw, Authority.TFE_PACKET.value, "packet", packet.get("generated_at") or packet.get("timestamp"), packet.get("freshness_state"))


def _value(packet: Mapping[str, Any], key: str) -> Any:
    f = _field(packet, key)
    return f.value if f else None


def _fmt(v: Any, digits: int = 2) -> str:
    if isinstance(v, Mapping):
        v = v.get("value")
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return str(v)


def _price(v: Any) -> str:
    return "$" + _fmt(v, 2) if v is not None else "N/A"


def _bounded_call(fn: Callable[[str], Mapping[str, Any]], ticker: str, timeout: float) -> Mapping[str, Any]:
    timeout = min(max(float(timeout), 0.001), MAX_TIMEOUT_SECONDS)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="atlas-tfe-runner") as pool:
        fut = pool.submit(fn, ticker)
        try:
            out = fut.result(timeout=timeout)
        except FutureTimeout as exc:
            fut.cancel()
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:PROVIDER_TIMEOUT") from exc
    if not isinstance(out, Mapping):
        raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:NON_MAPPING")
    return out


def immutable_tfe_packet(data: Mapping[str, Any]) -> Mapping[str, Any]:
    pkt = dict(data)
    if "schema_version" not in pkt:
        now = pkt.get("generated_at") or pkt.get("timestamp") or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        source = str(pkt.get("source") or "TFE_PACKET")
        raw = pkt.get("raw_tfe_classification") or pkt.get("signal") or pkt.get("classification")
        pkt = {
            "schema_version": "atlas_single_ticker_tfe_packet_v1",
            "generated_at": now,
            "ticker": pkt.get("ticker"),
            "raw_tfe_classification": field(raw, Authority.TFE_PACKET.value, source, now, "FRESH"),
            "score": field(pkt.get("score"), Authority.TFE_PACKET.value, source, now, "FRESH"),
            "pillars": field(pkt.get("pillars"), Authority.TFE_PACKET.value, source, now, "FRESH"),
            "current_price": field(pkt.get("current_price") or pkt.get("price"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "entry": field(pkt.get("entry") or pkt.get("entry_price"), Authority.TFE_PACKET.value, source, now, "FRESH"),
            "stop": field(pkt.get("stop") or pkt.get("stop_loss"), Authority.TFE_PACKET.value, source, now, "FRESH"),
            "target": field(pkt.get("target") or pkt.get("target_price") or pkt.get("analyst_target"), Authority.TFE_PACKET.value, source, now, "FRESH"),
            "rsi": field(pkt.get("rsi"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "macd": field(pkt.get("macd"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "rvol": field(pkt.get("rvol"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "atr": field(pkt.get("atr"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "ema10": field(pkt.get("ema10"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "ema21": field(pkt.get("ema21"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "ema50": field(pkt.get("ema50"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "sma50": field(pkt.get("sma50"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "sma200": field(pkt.get("sma200"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
            "catalyst_state": field(pkt.get("catalyst_state") or pkt.get("catalyst"), Authority.TFE_PACKET.value, source, now, "FRESH"),
            "fda_context": pkt.get("fda_context"),
        }
    return freeze_mapping(attach_digest(pkt) if not pkt.get("packet_digest") else pkt)


def read_latest_snapshot(db_path: str | Path, ticker: str) -> Optional[Mapping[str, Any]]:
    uri = "file:" + str(Path(db_path).resolve()) + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        row = con.execute("SELECT * FROM signals WHERE UPPER(ticker)=? ORDER BY datetime(timestamp) DESC,id DESC LIMIT 1", (ticker.upper(),)).fetchone()
        if not row:
            return None
        d = dict(row)
        pillars = {"trend": d.get("trend_stack"), "relative_strength": d.get("relative_strength"), "volume": d.get("volume"), "catalyst": d.get("catalyst")}
        source = "atlas.db.signals read-only"
        now = d.get("timestamp")
        pkt = {
            "schema_version": "atlas_signal_snapshot_v1",
            "generated_at": now,
            "ticker": ticker.upper(),
            "raw_tfe_classification": field(d.get("signal"), Authority.TFE_PACKET.value, source, now, None),
            "score": field(d.get("score"), Authority.TFE_PACKET.value, source, now, None),
            "pillars": field(pillars, Authority.TFE_PACKET.value, source, now, None),
            "entry": field(d.get("entry_price"), Authority.TFE_PACKET.value, source, now, None),
            "stop": field(d.get("stop_loss"), Authority.TFE_PACKET.value, source, now, None),
            "rvol": field(d.get("rvol"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, None),
            "atr": field(d.get("atr"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, None),
            "catalyst_state": field(d.get("catalyst"), Authority.TFE_PACKET.value, source, now, None),
            "warnings": d.get("warnings"),
        }
        return freeze_mapping(attach_digest(pkt))
    finally:
        con.close()


def requested_fields(prompt: str) -> set[str]:
    text = prompt.lower()
    fields: set[str] = set()
    mapping = {
        "current_price": ["price", "current", "now"],
        "entry": ["entry"], "stop": ["stop"], "target": ["target"],
        "score": ["score"], "pillars": ["pillar", "four"],
        "rsi": ["rsi"], "macd": ["macd"], "rvol": ["rvol", "relative volume"], "atr": ["atr"],
        "moving_averages": ["moving average", "ema", "sma", "ema10", "ema21", "ema50", "sma50", "sma200"],
        "reward_risk": ["reward/risk", "reward risk", "risk reward"],
        "catalyst_state": ["catalyst", "news"], "fda_context": ["fda"],
        "perme_regime": ["perme"], "quiver_posture": ["quiver"],
        "holdings_action": ["sell", "hold", "holding", "valid holding", "exit review", "trim review"],
        "recheck_condition": ["recheck"],
        "profit": ["peak gain", "current gain", "profit surrendered", "giveback"],
        "raw_final": ["should", "buy", "avoid", "action", "classification", "override", "ignore"],
    }
    for f, needles in mapping.items():
        if any(n in text for n in needles):
            fields.add(f)
    if not fields:
        fields.update({"raw_final", "score", "entry", "stop"})
    return fields


def classify_intent(prompt: str, ticker: str, snapshot: Mapping[str, Any] | None, *, price_input: PriceInput | None, policy: RouterPolicy, now: datetime | None = None, source_conflict: bool=False) -> tuple[str, tuple[str, ...]]:
    text = prompt.lower()
    reasons: list[str] = []
    if any(w in text for w in ["perme"]):
        return PERME_PACKET_REQUIRED, ()
    if any(w in text for w in ["quiver"]):
        return QUIVER_PACKET_REQUIRED, ()
    if "fda" in text:
        return FDA_CONTEXT_REQUIRED, ()
    if any(w in text for w in ["sell", "hold", "holding", "recheck", "valid holding", "exit review", "trim review"]):
        return HOLDINGS_PACKET_REQUIRED, ()
    exact = bool(re.search(r"\b(now|current|today|fresh|exact|score|pillars?|entry|stop|target|rsi|macd|rvol|atr|ema|sma|price|buy|avoid|override|estimate)\b", text))
    ok, fresh_reason, _age = validate_freshness(snapshot, now=now, ttl_seconds=policy.regular_ttl_seconds) if snapshot else (False, "PACKET_MISSING", None)
    if not snapshot:
        reasons.append("no_recent_structured_result")
    if exact:
        reasons.append("exact_or_fresh_numbers_requested")
    if snapshot and not ok:
        reasons.append(fresh_reason.lower())
    if price_input is not None:
        price_input.validate()
        ref = _num(_value(snapshot or {}, "current_price") or _value(snapshot or {}, "entry"))
        if ref and abs((float(price_input.value) - ref) / ref * 100.0) >= policy.price_move_pct:
            reasons.append("material_price_move_pct")
    if source_conflict:
        reasons.append("source_conflict")
    return (FRESH_TFE_REQUIRED, tuple(dict.fromkeys(reasons))) if reasons else (CONVERSATIONAL_CONFIRMATION, ())


def compute_reward_risk(packet: Mapping[str, Any]) -> SourceField | None:
    explicit = _field(packet, "reward_risk")
    if explicit and explicit.value is not None:
        return explicit
    entry, stop, target = _num(_value(packet, "entry")), _num(_value(packet, "stop")), _num(_value(packet, "target"))
    if entry is None or stop is None or target is None or entry <= stop:
        return None
    rr = (target - entry) / (entry - stop)
    return SourceField(round(rr, 4), Authority.RENDERER_CALC.value, "entry/stop/target from authoritative packet", packet.get("generated_at"), packet.get("freshness_state"))


def render_fda_context(ctx: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not ctx:
        return "FDA DATA UNAVAILABLE — FDA_PACKET_MISSING", {"status": "FDA_DATA_UNAVAILABLE", "reason": "FDA_PACKET_MISSING"}
    status = str(ctx.get("status") or ctx.get("fda_status") or "").upper()
    if status in {"STALE", "PACKET_STALE"}:
        return "FDA DATA UNAVAILABLE — PACKET_STALE", {"status":"FDA_DATA_UNAVAILABLE","reason":"PACKET_STALE"}
    if ctx.get("relevant") is True or status == "FDA_RELEVANT":
        detail = {
            "status":"FDA_RELEVANT", "matched_event":ctx.get("matched_event"), "event_type":ctx.get("event_type"),
            "event_date":ctx.get("event_date"), "outcome":ctx.get("outcome") or ctx.get("status_outcome"),
            "source_freshness":ctx.get("source_freshness") or ctx.get("freshness_state") or "FRESH",
            "authority":Authority.FDA_PACKET.value,
        }
        line = f"FDA_RELEVANT — {detail['matched_event']} · {detail['event_type']} · {detail['event_date']} · {detail['outcome']} · freshness {detail['source_freshness']}"
        return line, detail
    if ctx.get("relevant") is False or status == "NOT_FDA_RELEVANT":
        return "NOT_FDA_RELEVANT", {"status":"NOT_FDA_RELEVANT", "authority":Authority.FDA_PACKET.value}
    reason = ctx.get("reason") or "FDA_CONTEXT_UNAVAILABLE"
    return f"FDA DATA UNAVAILABLE — {reason}", {"status":"FDA_DATA_UNAVAILABLE", "reason":reason, "authority":Authority.FDA_PACKET.value}


def render_tfe(packet: Mapping[str, Any], fields: set[str], *, quiver_context: Mapping[str, Any] | None = None, fda_context: Mapping[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    raw = normalize_raw_tfe(_value(packet, "raw_tfe_classification"))
    qposture = str((quiver_context or {}).get("quiver_posture") or (quiver_context or {}).get("quiver_view") or "NO_USABLE_DATA").upper()
    if raw == "AVOID":
        final = "AVOID"
    elif raw.upper().startswith("BUY") and qposture == "CAUTION":
        final = "WAIT / REVIEW"
    elif raw.upper().startswith("BUY") and qposture == "MIXED":
        final = "REVIEW"
    else:
        final = raw if raw in {"BUY", "BUY Small", "AVOID"} else "REVIEW"
    struct: dict[str, Any] = {
        "ticker": packet.get("ticker"),
        "raw_tfe_classification": {"value": raw, "authority": Authority.TFE_PACKET.value},
        "final_advisory_action": {"value": final, "authority": Authority.TFE_PACKET.value if not quiver_context else Authority.QUIVER_PACKET.value},
        "packet_digest": packet.get("packet_digest"),
        "source_labels": {},
    }
    lines=[f"ATLAS DETERMINISTIC ANSWER — {packet.get('ticker')}", f"RAW TFE CLASSIFICATION: {raw}"]
    if quiver_context:
        lines.append(f"QUIVER OVERLAY: {qposture}")
    lines.append(f"FINAL ADVISORY ACTION: {final}")
    def add(label: str, key: str, formatter=lambda x: str(x), digits: int | None = None):
        f = _field(packet, key)
        if f and f.value is not None:
            val = formatter(f.value) if digits is None else _fmt(f.value, digits)
            lines.append(f"{label}: {val} [{f.authority}]")
            struct[key] = f.to_dict()
            struct["source_labels"][key] = f.authority
        else:
            lines.append(f"{label}: DATA UNAVAILABLE")
            struct[key] = {"value": None, "authority": "MISSING", "reason": f"{key.upper()}_MISSING"}
    if "current_price" in fields: add("CURRENT PRICE", "current_price", _price)
    if "entry" in fields or "raw_final" in fields: add("ENTRY", "entry", _price)
    if "stop" in fields or "raw_final" in fields: add("STOP", "stop", _price)
    if "target" in fields: add("TARGET", "target", _price)
    if "score" in fields or "raw_final" in fields: add("TFE SCORE", "score")
    if "pillars" in fields:
        f=_field(packet,"pillars")
        pv=f.value if f else None
        lines.append("FOUR PILLARS: " + (json.dumps(pv, sort_keys=True) if pv is not None else "DATA UNAVAILABLE") + (f" [{f.authority}]" if f else ""))
        struct["pillars"] = f.to_dict() if f else {"value":None,"authority":"MISSING"}
        if f: struct["source_labels"]["pillars"] = f.authority
    if "rsi" in fields: add("RSI", "rsi", digits=2)
    if "macd" in fields: add("MACD", "macd", digits=4)
    if "rvol" in fields: add("RVOL", "rvol", digits=2)
    if "atr" in fields: add("ATR", "atr", digits=2)
    if "moving_averages" in fields:
        for label,key in [("EMA10","ema10"),("EMA21","ema21"),("EMA50","ema50"),("SMA50","sma50"),("SMA200","sma200")]:
            add(label,key,_price)
    if "reward_risk" in fields or "raw_final" in fields:
        rr=compute_reward_risk(packet)
        if rr:
            lines.append(f"REWARD/RISK: {_fmt(rr.value,4)} [{rr.authority}]")
            struct["reward_risk"] = rr.to_dict(); struct["source_labels"]["reward_risk"] = rr.authority
        else:
            lines.append("REWARD/RISK: DATA UNAVAILABLE")
    if "catalyst_state" in fields: add("CATALYST STATE", "catalyst_state")
    if "fda_context" in fields:
        fline, fstruct=render_fda_context(fda_context if fda_context is not None else packet.get("fda_context"))
        lines.append("FDA CONTEXT: " + fline)
        struct["fda_context"] = fstruct
    lines.append(f"PACKET FRESHNESS: {packet.get('freshness_state','FRESH')} | digest {packet.get('packet_digest')}")
    return "\n".join(lines), struct


def render_holdings(ticker: str, holdings_packet: Mapping[str, Any] | None, fields: set[str], *, now: datetime | None, policy: RouterPolicy) -> tuple[str, dict[str, Any], str]:
    if (holdings_packet or {}).get("packet_version") == "holdings_merged_action.v1":
        return render_ticker_answer(ticker, holdings_packet)
    merged = build_merged_packet(holdings_packet, now=now, ttl_seconds=policy.holdings_ttl_seconds)
    return render_ticker_answer(ticker, merged)


def render_perme(ticker: str, packet: Mapping[str, Any] | None, *, now: datetime | None = None) -> tuple[str, dict[str, Any], str]:
    from atlas_perme_engine_packet import validate_packet
    if not packet:
        return "PERME DATA UNAVAILABLE — PACKET_MISSING", {"ticker":ticker,"error":"PACKET_MISSING"}, "PACKET_MISSING"
    res = validate_packet(dict(packet), now_et=now)
    if not res.ok:
        return f"PERME DATA UNAVAILABLE — {res.error}", {"ticker":ticker,"error":res.error,"authority":Authority.PERME_PACKET.value}, res.error.upper()
    pkt=res.packet or {}
    relevant = ticker.upper() in {str(t).upper() for t in pkt.get("tickers") or []}
    regime = pkt.get("direction")
    line = f"PERME CONTEXT: {'DIRECT' if relevant else 'NO_DIRECT_TICKER_MATCH'} · regime {regime} · severity {pkt.get('severity')} [PERME_PACKET]"
    return line, {"ticker":ticker.upper(),"perme_regime":{"value":regime,"authority":Authority.PERME_PACKET.value},"severity":pkt.get("severity"),"direct_match":relevant}, "FRESH"


def render_quiver(ticker: str, tfe_packet: Mapping[str, Any], quiver_packet: Mapping[str, Any] | None) -> tuple[str, dict[str, Any], str]:
    from atlas_quiver_decision_envelope import context_from_packet, apply_quiver_review_overlay, render_decision_block
    ctx = context_from_packet(ticker, dict(quiver_packet) if quiver_packet else None)
    raw = {"ticker":ticker, "raw_tfe_classification": normalize_raw_tfe(_value(tfe_packet,"raw_tfe_classification")), "score": _value(tfe_packet,"score"), "pillars": _value(tfe_packet,"pillars"), "entry": _value(tfe_packet,"entry"), "stop": _value(tfe_packet,"stop"), "target": _value(tfe_packet,"target")}
    env = apply_quiver_review_overlay(raw, ctx)
    block = render_decision_block(env)
    block += f"\nRAW TFE CLASSIFICATION: {env.get('raw_tfe_classification')}\nFINAL ADVISORY ACTION: {env.get('final_advisory_action')}\nPACKET DIGEST: {env.get('packet_digest')}"
    return block, env, str(ctx.get("quiver_freshness") or "DATA_UNAVAILABLE")


class ConversationRouter:
    def __init__(self, *, db_path: str | Path | None = None, tfe_runner: Callable[[str], Mapping[str, Any]] | None = None, timeout_seconds: float = 10.0, policy: RouterPolicy = RouterPolicy()):
        self.db_path = db_path
        self.tfe_runner = tfe_runner
        self.timeout_seconds = timeout_seconds
        self.policy = policy

    def route(self, prompt: str, ticker: str, *, envelope: Mapping[str, Any] | None = None, price_input: PriceInput | None = None, holdings_packet: Mapping[str, Any] | None = None, perme_packet: Mapping[str, Any] | None = None, quiver_packet: Mapping[str, Any] | None = None, fda_context: Mapping[str, Any] | None = None, now: datetime | None = None, source_conflict: bool=False) -> RouteResult:
        started=time.perf_counter(); ticker=str(ticker or "").strip().upper(); now=now or datetime.now(timezone.utc)
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker): raise RouterError("INVALID_TICKER")
        snapshot = immutable_tfe_packet(envelope) if envelope is not None else (read_latest_snapshot(self.db_path, ticker) if self.db_path else None)
        route, reasons = classify_intent(prompt, ticker, snapshot, price_input=price_input, policy=self.policy, now=now, source_conflict=source_conflict)
        fields=requested_fields(prompt)
        fresh_run=False; source=""
        if route == HOLDINGS_PACKET_REQUIRED:
            ans, struct, freshness = render_holdings(ticker, holdings_packet, fields, now=now, policy=self.policy)
            return RouteResult(route,ticker,"holdings packet",freeze_mapping(holdings_packet or {}),freeze_mapping(struct),ans,freshness,reasons,False,time.perf_counter()-started)
        if route == PERME_PACKET_REQUIRED:
            ans, struct, freshness = render_perme(ticker, perme_packet, now=now)
            return RouteResult(route,ticker,"Perme packet",freeze_mapping(perme_packet or {}),freeze_mapping(struct),ans,freshness,reasons,False,time.perf_counter()-started)
        if route == FDA_CONTEXT_REQUIRED:
            if snapshot is None or "exact_or_fresh_numbers_requested" in reasons or not validate_freshness(snapshot, now=now, ttl_seconds=self.policy.regular_ttl_seconds)[0]:
                if not self.tfe_runner: raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:NO_RUNNER_CONFIGURED")
                snapshot = immutable_tfe_packet(_bounded_call(self.tfe_runner, ticker, self.timeout_seconds)); fresh_run=True
            ans, struct = render_tfe(snapshot, fields | {"fda_context"}, fda_context=fda_context)
            return RouteResult(route,ticker,"FDA context + TFE packet",snapshot,freeze_mapping(struct),ans,"FRESH",reasons,fresh_run,time.perf_counter()-started)
        if route in {FRESH_TFE_REQUIRED, CONVERSATIONAL_CONFIRMATION, QUIVER_PACKET_REQUIRED}:
            if route == FRESH_TFE_REQUIRED or snapshot is None:
                if not self.tfe_runner: raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:NO_RUNNER_CONFIGURED")
                snapshot = immutable_tfe_packet(_bounded_call(self.tfe_runner, ticker, self.timeout_seconds)); fresh_run=True; source="injected production-safe single-ticker TFE runner"
            else:
                source="fresh immutable TFE/signal packet"
            if route == QUIVER_PACKET_REQUIRED:
                ans, struct, freshness = render_quiver(ticker, snapshot, quiver_packet)
                return RouteResult(route,ticker,"Quiver packet + TFE packet",snapshot,freeze_mapping(struct),ans,freshness,reasons,fresh_run,time.perf_counter()-started)
            ans, struct = render_tfe(snapshot, fields, fda_context=fda_context)
            return RouteResult(route,ticker,source,snapshot,freeze_mapping(struct),ans,"FRESH",reasons,fresh_run,time.perf_counter()-started)
        raise RouterError("UNHANDLED_ROUTE")


def holdings_reunderwrite_conversation_answer(ticker: str, packet: Mapping[str, Any] | None, *, now: datetime | None = None, ttl_seconds: int = 36*3600, expected_session: str | None = None) -> dict[str, Any]:
    t=str(ticker or "").upper()
    merged = packet if (packet or {}).get("packet_version") == "holdings_merged_action.v1" else build_merged_packet(packet, now=now, ttl_seconds=ttl_seconds, expected_session=expected_session)
    _text, struct, freshness = render_ticker_answer(t, merged)
    if struct.get("error"):
        return {"ticker":t,"daily_reunderwrite_action":"DATA INCOMPLETE","profit_protection_action":"DATA INCOMPLETE","stop_status":"UNKNOWN","final_advisory_action":"DATA INCOMPLETE","reason_codes":[struct.get("error")],"authority":"HOLDINGS_MERGED_ACTION_PACKET","packet_freshness":freshness}
    return {"ticker":t,"daily_reunderwrite_action":struct.get("daily_action"),"profit_protection_action":struct.get("profit_protection_action"),"stop_status":struct.get("stop_status"),"broker_status":struct.get("broker_status"),"final_advisory_action":struct.get("final_action"),"reason_codes":struct.get("final_reason_codes") or [],"recheck_condition":struct.get("recheck_condition"),"authority":"HOLDINGS_MERGED_ACTION_PACKET","packet_freshness":freshness,"packet_digest":(merged or {}).get("packet_digest")}


def dispatch_atlas_trading_question(question: str, ticker: str, *, router: ConversationRouter, **kwargs: Any) -> RouteResult:
    """Production conversation entry contract: all Atlas trading questions enter here."""
    return router.route(question, ticker, **kwargs)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("ticker"); ap.add_argument("question"); ap.add_argument("--db"); ap.add_argument("--envelope")
    args=ap.parse_args(); env=json.loads(Path(args.envelope).read_text()) if args.envelope else None
    router=ConversationRouter(db_path=args.db, tfe_runner=None)
    res=router.route(args.question,args.ticker,envelope=env)
    print(res.rendered_answer)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
