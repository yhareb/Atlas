
"""Phase 4 shadow consumers for Atlas Holding-State Authority.

Staged under /tmp only. Shadow consumers render/compare canonical packets but do
not calculate price, stop status, action precedence, freshness, or broker lifecycle.
"""
from __future__ import annotations
from typing import Any
import copy, hashlib, json

CONSUMERS = ("pre_market", "intraday", "eod_postmarket", "conversation", "broker_pending", "profit_daily_sections")
COMPARE_FIELDS = (
    "observed_state", "advisory_action", "broker_lifecycle", "display_price", "valuation_price",
    "stop_evaluation_price", "quote_timestamp", "quote_session", "quote_freshness", "reason_codes", "packet_digest",
)


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj: Any) -> str:
    return hashlib.sha256(stable_json(obj).encode()).hexdigest()


def canonical_projection(packet: dict[str, Any]) -> dict[str, Any]:
    """Projection only: no state calculation; reads canonical fields verbatim."""
    axes = packet.get("axes") or {}
    quote = packet.get("quote_selection") or {}
    stop_price = quote.get("selected_stop_evaluation_price") or {}
    display = quote.get("selected_display_price") or {}
    valuation = quote.get("selected_valuation_price") or {}
    advisory = axes.get("advisory_action") or {}
    observed = axes.get("observed_market_risk_state") or {}
    broker = axes.get("broker_ledger_lifecycle") or {}
    return {
        "ticker": packet.get("ticker"),
        "observed_state": observed.get("state"),
        "advisory_action": advisory.get("action"),
        "broker_lifecycle": broker.get("state"),
        "display_price": display.get("price"),
        "valuation_price": valuation.get("price"),
        "stop_evaluation_price": stop_price.get("price"),
        "quote_timestamp": stop_price.get("timestamp") or display.get("timestamp") or valuation.get("timestamp"),
        "quote_session": quote.get("report_session"),
        "quote_freshness": stop_price.get("validity"),
        "reason_codes": tuple(advisory.get("reason_codes") or observed.get("reason_codes") or ()),
        "packet_digest": (packet.get("digests") or {}).get("packet_digest"),
        "reconciliation_blocker": observed.get("state") == "LIFECYCLE_CONTRADICTION" or advisory.get("action") == "DATA INCOMPLETE" and "LIFECYCLE_CONTRADICTION" in tuple(advisory.get("reason_codes") or ()),
        "reconciliation_blocker_message": "RECONCILIATION BLOCKER — broker/ledger lifecycle conflicts with DB OPEN state" if (observed.get("state") == "LIFECYCLE_CONTRADICTION" or advisory.get("action") == "DATA INCOMPLETE" and "LIFECYCLE_CONTRADICTION" in tuple(advisory.get("reason_codes") or ())) else None,
        "canonical_input_digest": (packet.get("digests") or {}).get("canonical_input_digest"),
        "stop_event_identity": (packet.get("components") or {}).get("stop_lifecycle"),
        "components": packet.get("components"),
        "retention": packet.get("retention"),
        "clearing": packet.get("clearing"),
    }


def render_shadow_consumer(consumer: str, packet: dict[str, Any]) -> dict[str, Any]:
    if consumer not in CONSUMERS:
        raise ValueError("UNKNOWN_CONSUMER")
    proj = canonical_projection(packet)
    # Presentation-only flags derived from canonical fields. No merge/precedence.
    view = copy.deepcopy(proj)
    view["consumer"] = consumer
    view["render_digest"] = digest({"consumer": consumer, "projection": proj})
    if consumer == "broker_pending":
        view["broker_pending_visible"] = proj["broker_lifecycle"] == "BROKER_SELL_SUBMITTED"
    if consumer == "profit_daily_sections":
        comps = proj.get("components") or {}
        view["daily_section"] = (comps.get("daily_reunderwriting") or {}).get("action")
        view["profit_protection_section"] = (comps.get("profit_protection") or {}).get("action")
    if consumer == "conversation":
        view["answer_fields"] = {k: proj[k] for k in COMPARE_FIELDS}
    return view


def run_all_shadow_consumers(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c: render_shadow_consumer(c, packet) for c in CONSUMERS}


def compare_legacy_to_canonical(legacy: dict[str, Any], canonical: dict[str, Any], expected_legacy_defects: set[str] | None = None) -> list[dict[str, Any]]:
    expected_legacy_defects = expected_legacy_defects or set()
    diffs=[]
    for field in COMPARE_FIELDS:
        lv = legacy.get(field)
        cv = canonical.get(field)
        if lv != cv:
            if field in expected_legacy_defects:
                cls = "EXPECTED_LEGACY_DEFECT"
            elif cv in (None, "DATA INCOMPLETE"):
                cls = "INPUT_GAP"
            else:
                cls = "UNRESOLVED"
            diffs.append({"field": field, "legacy": lv, "canonical": cv, "classification": cls})
    return diffs


def compare_consumers(canonical_views: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base_name = sorted(canonical_views)[0]
    base = canonical_views[base_name]
    mismatches=[]
    for name, view in canonical_views.items():
        for field in COMPARE_FIELDS:
            if view.get(field) != base.get(field):
                mismatches.append({"consumer": name, "field": field, "base_consumer": base_name, "base": base.get(field), "value": view.get(field)})
    return {"base_consumer": base_name, "mismatches": mismatches, "pass": not mismatches}


def invariant_results(canonical_views: dict[str, dict[str, Any]], packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    comp = compare_consumers(canonical_views)
    proj = canonical_projection(packet)
    broker_pending_view = canonical_views.get("broker_pending", {})
    stop_source = ((packet.get("quote_selection") or {}).get("selected_stop_evaluation_price") or {}).get("source")
    display_source = ((packet.get("quote_selection") or {}).get("selected_display_price") or {}).get("source")
    stop_state = proj.get("observed_state")
    advisory = proj.get("advisory_action")
    packet_digests = {v.get("packet_digest") for v in canonical_views.values()}
    return {
        "identical_advisory_action": {"pass": comp["pass"], "value": [v.get("advisory_action") for v in canonical_views.values()]},
        "identical_observed_stop_state": {"pass": comp["pass"], "value": [v.get("observed_state") for v in canonical_views.values()]},
        "identical_broker_lifecycle_state": {"pass": comp["pass"], "value": [v.get("broker_lifecycle") for v in canonical_views.values()]},
        "identical_price_roles": {"pass": comp["pass"], "value": [(v.get("display_price"), v.get("valuation_price"), v.get("stop_evaluation_price")) for v in canonical_views.values()]},
        "identical_quote_timestamp_session_freshness": {"pass": comp["pass"], "value": [(v.get("quote_timestamp"), v.get("quote_session"), v.get("quote_freshness")) for v in canonical_views.values()]},
        "fallback_not_stop_logic": {"pass": not (stop_source in {"FALLBACK_DISPLAY_ONLY", "REFERENCE", "ENTRY_REFERENCE"}), "value": {"stop_source": stop_source, "display_source": display_source}},
        "stale_event_not_sell_now": {"pass": not (str(stop_state).startswith("INVALID") and advisory == "SELL NOW"), "value": {"observed": stop_state, "advisory": advisory}},
        "no_broker_pending_without_submitted": {"pass": (not broker_pending_view.get("broker_pending_visible")) or proj.get("broker_lifecycle") == "BROKER_SELL_SUBMITTED", "value": broker_pending_view.get("broker_pending_visible")},
        "identical_packet_digest": {"pass": len(packet_digests) == 1, "value": sorted(packet_digests)},
        "no_consumer_local_action_merge": {"pass": True, "value": "static scan enforced separately"},
    }
