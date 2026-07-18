#!/usr/bin/env python3
"""Deterministic, presentation-only authority for Atlas intraday advice.

This module is pure standard library.  It never mutates its input, writes a database,
fetches data, or sends notifications.  Raw TFE fields are copied verbatim into the
result; the advisory action is a separate presentation decision.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

RVOL_MIN = 1.5
MAX_AGE_MINUTES = 35
BUY_FAMILY = ("BUY", "BUY SMALL", "BUY NOW", "REVIEW")
ACTIONS = ("BUY NOW", "REVIEW", "WAIT — DO NOT CHASE", "AVOID")
_RAW_KEYS = ("signal", "score", "pillars", "timestamp")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper().replace("_", " ")


def canonical_signal(value: Any) -> str:
    """Normalize for classification only; the raw signal remains untouched."""
    text = re.sub(r"^[^A-Z0-9]+", "", _upper(value))
    text = re.sub(r"[()\[\]{}:;,.!\-/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def signal_family(value: Any) -> str:
    signal = canonical_signal(value)
    if signal.startswith("AVOID"):
        return "AVOID"
    if signal.startswith("WATCH"):
        return "WATCH"
    if signal.startswith(BUY_FAMILY):
        return "BUY"
    return "OTHER"


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> _dt.datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = _dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed
    except (TypeError, ValueError):
        return None


def _age_minutes(timestamp: Any, now: _dt.datetime) -> float | None:
    parsed = _parse_time(timestamp)
    if parsed is None:
        return None
    if parsed.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    elif parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return (now - parsed).total_seconds() / 60.0


def _bool_value(row: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            value = row[key]
            if isinstance(value, bool):
                return value
            if _upper(value) in {"TRUE", "YES", "PASS", "PASSED", "OK", "1"}:
                return True
            if _upper(value) in {"FALSE", "NO", "FAIL", "FAILED", "BLOCKED", "0"}:
                return False
    return None


def _pillar_number(row: Mapping[str, Any]) -> int:
    value = row.get("score", row.get("pillars", "0"))
    match = re.search(r"(\d+)\s*/", _text(value))
    return int(match.group(1)) if match else 0


def _evidence_text(row: Mapping[str, Any]) -> str:
    fields = ("warnings", "reason", "catalyst", "catalyst_reason", "gap_context", "relative_strength")
    return " | ".join(_text(row.get(key)) for key in fields if row.get(key) not in (None, ""))


def blockers(row: Mapping[str, Any], *, now: _dt.datetime | None = None) -> tuple[str, ...]:
    """Return blockers using only supplied evidence, in stable precedence order."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    evidence = _evidence_text(row)
    upper = evidence.upper()
    found: list[str] = []
    age = _age_minutes(row.get("timestamp", row.get("signal_timestamp")), now)
    if age is None:
        found.append("Signal timestamp missing; freshness cannot be verified")
    elif age < 0:
        found.append("Signal timestamp is in the future")
    elif age > MAX_AGE_MINUTES:
        found.append(f"Signal stale: {age:.1f} minutes old (maximum {MAX_AGE_MINUTES})")
    rvol = _number(row.get("rvol"))
    if rvol is None:
        found.append(f"RVOL missing; required at least {RVOL_MIN:.1f}")
    elif rvol < RVOL_MIN:
        found.append(f"RVOL {rvol:g} below {RVOL_MIN:.1f}")
    rsi = _number(row.get("rsi"))
    weak = _bool_value(row, "momentum_weak") is True or "MOMENTUM WEAK" in upper or "WEAK MOMENTUM" in upper
    if rsi is not None and rsi > 70 and weak:
        found.append(f"RSI {rsi:g} with weak momentum")
    rs = _bool_value(row, "relative_strength_pass", "relative_strength_ok")
    rs_text = _upper(row.get("relative_strength"))
    if rs is False or rs_text.startswith("NO") or "RELATIVE STRENGTH FAIL" in upper or "RELATIVE STRENGTH: FAIL" in upper:
        found.append("Relative Strength failed")
    gap = _bool_value(row, "material_earnings_gap_reversal", "earnings_gap_reversal")
    if gap is True or ("EARNINGS" in upper and "GAP" in upper and "REVERS" in upper):
        found.append("Material earnings-gap reversal")
    gates = row.get("mandatory_report_gates")
    if isinstance(gates, Mapping):
        if not gates:
            found.append("Mandatory report gates missing")
        for name in sorted(gates):
            if gates[name] is not True:
                found.append(f"Mandatory gate failed: {name}")
    else:
        # Integration must construct this map from facts it already owns.  Do
        # not couple presentation authority to a nonexistent database column.
        found.append("Mandatory report gates missing")
    return tuple(dict.fromkeys(found))


@dataclass(frozen=True)
class Advisory:
    ticker: str
    raw: Mapping[str, Any]
    action_now: str
    status: str
    why: tuple[str, ...]
    blockers: tuple[str, ...]
    freshness: str
    top_pick: bool

    def as_dict(self) -> dict[str, Any]:
        return {"ticker": self.ticker, "raw": dict(self.raw), "action_now": self.action_now,
                "status": self.status, "why": list(self.why), "blockers": list(self.blockers),
                "freshness": self.freshness, "top_pick": self.top_pick}


def advise(row: Mapping[str, Any], *, now: _dt.datetime | None = None) -> Advisory:
    """Derive ACTION NOW without altering or relabeling the raw TFE decision."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    raw = MappingProxyType({
        "signal": row.get("signal"),
        "score": row.get("score"),
        # The production signals schema stores the pillar expression in score;
        # fixtures/newer callers may also provide a distinct pillars field.
        "pillars": row.get("pillars") if row.get("pillars") not in (None, "") else row.get("score"),
        "timestamp": row.get("timestamp"),
    })
    signal = canonical_signal(row.get("signal"))
    family = signal_family(row.get("signal"))
    blocked = blockers(row, now=now)
    age = _age_minutes(row.get("timestamp", row.get("signal_timestamp")), now)
    timestamp = _text(row.get("timestamp", row.get("signal_timestamp"))) or "missing"
    source = _text(row.get("data_source", row.get("source"))) or "source missing"
    age_text = ("age unavailable" if age is None else f"age {age:.1f} minutes")
    state = ("timestamp missing" if age is None else "future timestamp" if age < 0 else
             "fresh" if age <= MAX_AGE_MINUTES else "stale")
    freshness = f"timestamp {timestamp} · source {source} · {age_text} · {state}"
    why = [f"Raw TFE signal {_text(row.get('signal')) or 'missing'}"]
    if row.get("score") not in (None, ""):
        why.append(f"Raw TFE score {_text(row.get('score'))}")
    if row.get("rvol") not in (None, ""):
        why.append(f"RVOL {_number(row.get('rvol')):g}")
    if family == "AVOID":
        action, status = "AVOID", "AVOID"
    elif family == "BUY":
        if blocked:
            action = "WAIT — DO NOT CHASE"
            status = "TECHNICALLY QUALIFIED — WAIT"
        else:
            action = "BUY NOW" if _pillar_number(row) >= 4 else "REVIEW"
            status = action
    else:
        action, status = "REVIEW", "REVIEW"
    top = family == "BUY" and not blocked and action in {"BUY NOW", "REVIEW"}
    return Advisory(_upper(row.get("ticker")), raw, action, status, tuple(why), blocked, freshness, top)


@dataclass(frozen=True)
class AdvisoryRouting:
    current_buy_family: frozenset[str]
    buy_now: tuple[Advisory, ...]
    top_picks: tuple[Advisory, ...]
    qualified_wait: tuple[Advisory, ...]
    explicitly_excluded: Mapping[str, str]
    watch: tuple[Advisory, ...]
    avoid: tuple[Advisory, ...]

    @property
    def destination_sets(self) -> Mapping[str, frozenset[str]]:
        return MappingProxyType({
            "buy_now": frozenset(x.ticker for x in self.buy_now),
            "top_picks": frozenset(x.ticker for x in self.top_picks),
            "qualified_wait": frozenset(x.ticker for x in self.qualified_wait),
            "explicitly_excluded": frozenset(self.explicitly_excluded),
        })

    def diagnostics(self) -> dict[str, Any]:
        sets = self.destination_sets
        return {"current_buy_family_count": len(self.current_buy_family),
                "current_buy_family": sorted(self.current_buy_family),
                "counts": {k: len(v) for k, v in sets.items()},
                "sets": {k: sorted(v) for k, v in sets.items()},
                "exclusion_reasons": dict(self.explicitly_excluded),
                "watch": sorted(x.ticker for x in self.watch),
                "avoid": sorted(x.ticker for x in self.avoid),
                "equation_holds": self.current_buy_family == frozenset().union(*sets.values())}


def build_advisory_routing(rows: Iterable[Mapping[str, Any]], *, now: _dt.datetime | None = None,
                           buy_now_tickers: Iterable[str] = (), open_tickers: Iterable[str] = (),
                           pending_tickers: Iterable[str] = (), top_pick_limit: int = 5) -> AdvisoryRouting:
    """Partition every current-cycle BUY ticker exactly once; WATCH/AVOID stay separate."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    buy_now_set, open_set, pending_set = ({_upper(x) for x in values} for values in
                                          (buy_now_tickers, open_tickers, pending_tickers))
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    watch: dict[str, Advisory] = {}; avoid: dict[str, Advisory] = {}
    for row in rows:
        ticker, family = _upper(row.get("ticker")), signal_family(row.get("signal"))
        if family == "BUY" and ticker:
            grouped.setdefault(ticker, []).append(row)
        elif family == "WATCH" and ticker:
            watch.setdefault(ticker, advise(row, now=now))
        elif family == "AVOID" and ticker:
            avoid.setdefault(ticker, advise(row, now=now))
    buy_now: list[Advisory] = []; candidates: list[Advisory] = []; waits: list[Advisory] = []
    excluded: dict[str, str] = {}
    for ticker in sorted(grouped):
        ticker_rows = grouped[ticker]
        if len(ticker_rows) != 1:
            excluded[ticker] = f"duplicate current-cycle BUY-family rows ({len(ticker_rows)})"; continue
        row = ticker_rows[0]; decision = advise(row, now=now); evidence = _evidence_text(row).upper()
        if ticker in open_set:
            excluded[ticker] = "open position"
        elif ticker in pending_set:
            excluded[ticker] = "pending entry/WAITING"
        elif any("stale:" in b.lower() or "timestamp missing" in b.lower() or "future" in b.lower()
                 for b in decision.blockers):
            excluded[ticker] = "stale data"
        elif "TOO HOT" in evidence or "TOO EXTENDED" in evidence or row.get("is_too_hot") is True:
            excluded[ticker] = "Too Hot"
        elif row.get("score") in (None, "") or not re.search(r"\d+\s*/\s*\d+", _text(row.get("score"))):
            excluded[ticker] = "malformed/incomplete evidence: score"
        elif row.get("mandatory_report_gates") is None:
            excluded[ticker] = "malformed/incomplete evidence: mandatory report gates"
        elif ticker in buy_now_set:
            buy_now.append(decision)
        elif decision.status == "TECHNICALLY QUALIFIED — WAIT":
            waits.append(decision)
        elif decision.top_pick:
            candidates.append(decision)
        else:
            excluded[ticker] = "malformed/incomplete evidence: no advisory destination"
    candidates.sort(key=lambda x: (-_pillar_number(x.raw), x.ticker)); limit = max(0, int(top_pick_limit))
    top = candidates[:limit]
    for item in candidates[limit:]: excluded[item.ticker] = f"top-pick display cap ({limit})"
    route = AdvisoryRouting(frozenset(grouped), tuple(sorted(buy_now, key=lambda x: x.ticker)), tuple(top),
        tuple(sorted(waits, key=lambda x: (-_pillar_number(x.raw), x.ticker))),
        MappingProxyType(dict(sorted(excluded.items()))), tuple(watch.values()), tuple(avoid.values()))
    sets = route.destination_sets; destinations = [x for values in sets.values() for x in values]
    if len(destinations) != len(set(destinations)) or set(destinations) != set(route.current_buy_family):
        raise AssertionError("current-cycle BUY-family routing equation violated")
    return route


def top_picks(rows: Iterable[Mapping[str, Any]], *, now: _dt.datetime | None = None, limit: int = 5) -> tuple[Advisory, ...]:
    picks = [advise(row, now=now) for row in rows]
    picks = [item for item in picks if item.top_pick]
    return tuple(sorted(picks, key=lambda item: (-_pillar_number(item.raw), item.ticker))[:limit])


def regime(summary: Mapping[str, Any]) -> str:
    """Return exactly one regime with conservative precedence."""
    text = " ".join(_upper(summary.get(key)) for key in ("regime", "regime_detail"))
    macro = summary.get("macro_context") if isinstance(summary.get("macro_context"), Mapping) else {}
    sent = summary.get("macro_sentiment") if isinstance(summary.get("macro_sentiment"), Mapping) else {}
    sent_text = _upper(sent.get("sentiment"))
    if "RISK-OFF" in text or "RISK OFF" in text or sent_text in {"RISK OFF", "RISK-OFF"}:
        return "RISK-OFF"
    if macro.get("cautious") or sent_text == "CAUTION" or "CAUTION" in text:
        return "CAUTION"
    return "RISK-ON" if ("RISK-ON" in text or "RISK ON" in text or summary.get("regime_ok")) else "CAUTION"


def earnings_wording(row: Mapping[str, Any]) -> str:
    text = _evidence_text(row).lower()
    related = any(term in text for term in ("earnings", "guidance", "analyst"))
    timestamp = row.get("earnings_timestamp") or row.get("catalyst_timestamp")
    if related:
        return "Earnings-related catalyst present" + (f" ({timestamp})" if timestamp else "; timestamp missing")
    if row.get("earnings_stale"):
        return "Earnings information stale" + (f" ({timestamp})" if timestamp else "; timestamp missing")
    if row.get("no_earnings") is True:
        return "No earnings catalyst reported by source"
    return "Earnings information missing"


def naturalize(text: str) -> str:
    replacements = {"[DB]": "Recorded", "[TFE]": "TFE", "[PROVIDER]": "Market data",
                    "[RENDER-CALC]": "Calculated", "STRUCTURED_MACRO_FACTS": "Macro facts",
                    "Perme Engine Packet": "Market context"}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


__all__ = ["ACTIONS", "Advisory", "AdvisoryRouting", "MAX_AGE_MINUTES", "RVOL_MIN", "advise",
           "blockers", "build_advisory_routing", "canonical_signal", "earnings_wording", "naturalize",
           "regime", "signal_family", "top_picks"]


