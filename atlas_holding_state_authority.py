"""Canonical authority from normalized evidence; no consumer-local fallback."""
from __future__ import annotations
from atlas_holding_state_schema import digest,make_packet
STRENGTH={'HOLD':0,'WATCH':1,'TRIM REVIEW':2,'EXIT REVIEW':3,'SELL NOW':4}
def canonical_input_digest(value):return digest(value)
def resolve(normalized):
 prior=((normalized.get('prior_canonical_state') or {}).get('advisory_action') or {}).get('action')
 proposed=str(normalized.get('proposed_action') or 'HOLD').upper()
 clear=normalized.get('explicit_clear') or {}
 action=proposed;retained=False
 if prior and STRENGTH.get(prior,0)>STRENGTH.get(proposed,0) and not (clear.get('attempted') and clear.get('valid')):action=prior;retained=True
 axes={'observed_market_risk_state':dict(normalized.get('observed_market_risk_state') or {'state':'DATA_INCOMPLETE'}),'advisory_action':{'action':action,'prior_action':prior,'retained':retained,'reason_codes':list(normalized.get('reason_codes') or [])},'broker_ledger_lifecycle':dict(normalized.get('broker_ledger_lifecycle') or {'state':'NO_BROKER_EVENT'})}
 payload=dict(normalized.get('identity') or {});payload.update(completed_session=normalized.get('completed_session'),canonical_input_digest=canonical_input_digest(normalized.get('canonical_inputs') or normalized),policy_versions=normalized.get('policy_versions') or ['atlas-authority.v3'],axes=axes,canonical_levels=dict(normalized.get('canonical_levels') or {}),price_roles=dict(normalized.get('price_roles') or {}),provenance=dict(normalized.get('provenance') or {}),retention=dict(normalized.get('retention') or {}))
 return make_packet(payload)

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
import hashlib, json, sqlite3, os
from atlas_holding_state_schema import SCHEMA_VERSION, QUOTE_SELECTION_VERSION, LEDGER_SCHEMA_VERSION, ACTION_RANK, STRONG_ACTIONS, REASON_CODES, LEDGER_EVENT_TYPES, PriceRole, QuoteSelection, AxisState, AdvisoryAction, BrokerLifecycle, RetentionState, validate_packet_shape
SESSION_TTL_SECONDS = {'PRE_MARKET': 15 * 60, 'REGULAR': 5 * 60, 'REGULAR_URGENT': 90, 'AFTER_MARKET': 15 * 60, 'CLOSED': 16 * 3600}
STOP_EVAL_SOURCE_CLASSES = {'PROVIDER_TRADE', 'PROVIDER_MINUTE_CLOSE', 'PROVIDER_AGGREGATE', 'PROVIDER_SNAPSHOT', 'PERSISTED_STOP_EVENT'}
VALUATION_SOURCE_CLASSES = {'PROVIDER_TRADE', 'PROVIDER_MINUTE_CLOSE', 'PROVIDER_AGGREGATE', 'PROVIDER_SNAPSHOT', 'COMPLETED_DAILY_CLOSE', 'CACHE'}
DISPLAY_SOURCE_CLASSES = VALUATION_SOURCE_CLASSES | STOP_EVAL_SOURCE_CLASSES | {'FALLBACK_DISPLAY_ONLY', 'REFERENCE', 'ENTRY_REFERENCE'}
REASON_ALIASES = {'STOP BREACHED REGULAR': 'REGULAR_STOP_BREACH', 'STOP_BREACHED_REGULAR': 'REGULAR_STOP_BREACH', 'STOP BREACHED PRE MARKET': 'PREMARKET_STOP_BREACH', 'STOP_BREACHED_PRE_MARKET': 'PREMARKET_STOP_BREACH', 'STOP BREACHED AFTER MARKET': 'AFTERHOURS_STOP_BREACH', 'PROTECT PROFIT': 'PROFIT_GIVEBACK', 'TIGHTEN': 'PROFIT_GIVEBACK', 'PROFIT PROTECTION': 'PROFIT_GIVEBACK', 'TRIM': 'PROFIT_PROTECTION_TRIM_REVIEW', 'EXIT': 'THESIS_DETERIORATION', 'THESIS WEAK': 'THESIS_DETERIORATION', 'THESIS BROKEN': 'THESIS_BROKEN', 'CATALYST': 'CATALYST_RISK', 'SECTOR': 'SECTOR_BREAKDOWN', 'REGIME': 'REGIME_RISK'}
ACTION_ALIASES = {'SELL': 'SELL NOW', 'SELL_NOW': 'SELL NOW', 'EXIT': 'EXIT REVIEW', 'EXIT_REVIEW': 'EXIT REVIEW', 'TRIM': 'TRIM REVIEW', 'TRIM_REVIEW': 'TRIM REVIEW', 'HOLD_TIGHT': 'HOLD TIGHT', 'WATCH CLOSELY': 'HOLD TIGHT', 'PROTECT PROFIT': 'TRIM REVIEW', 'TIGHTEN': 'HOLD TIGHT', 'MISSING': 'DATA INCOMPLETE', 'STALE': 'DATA INCOMPLETE', '': 'DATA INCOMPLETE', None: 'DATA INCOMPLETE'}

def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(text if 'T' in text else text.replace(' ', 'T'))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)

def sha_json(obj: Any) -> str:
    return hashlib.sha256(stable_json(obj).encode()).hexdigest()

def normalize_action(action: Any) -> str:
    if action is None:
        return 'DATA INCOMPLETE'
    text = str(action).strip().upper().replace('_', ' ')
    return ACTION_ALIASES.get(text, text if text in ACTION_RANK else 'DATA INCOMPLETE')

def normalize_reason_codes(reasons: Iterable[Any] | Any) -> tuple[str, ...]:
    if reasons is None:
        return ()
    if isinstance(reasons, (str, bytes)):
        items = [reasons]
    else:
        try:
            items = list(reasons)
        except TypeError:
            items = [reasons]
    out: list[str] = []
    for r in items:
        text = str(r or '').strip().upper().replace('_', ' ').replace('-', ' ')
        if not text:
            continue
        code = REASON_ALIASES.get(text) or text.replace(' ', '_')
        if code not in REASON_CODES and code not in {'EXPLICIT_STOP_CLEAR', 'EXPLICIT_PROFIT_CLEAR', 'EXPLICIT_THESIS_CLEAR'}:
            code = 'DATA_STALE_OR_MISSING' if 'STALE' in code or 'MISSING' in code else code
        if code not in out:
            out.append(code)
    return tuple(out)

def strongest_action(*actions: Any) -> str:
    vals = [normalize_action(a) for a in actions if a is not None]
    vals = [v for v in vals if v in ACTION_RANK]
    return min(vals or ['DATA INCOMPLETE'], key=lambda a: ACTION_RANK[a])

def _quote_reject(q: dict[str, Any], reason: str) -> dict[str, Any]:
    return {'source': q.get('source_class') or q.get('source'), 'timestamp': q.get('timestamp'), 'price': q.get('price'), 'reason': reason}

def _valid_price(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except Exception:
        return None

def _age_ok(ts: datetime, now: datetime, session: str, role: str) -> bool:
    ttl_key = 'REGULAR_URGENT' if session == 'REGULAR' and role == 'stop_urgent' else session
    ttl = SESSION_TTL_SECONDS.get(ttl_key, 300)
    age = (now - ts).total_seconds()
    return -30 <= age <= ttl

def _session_ok(qsession: str, report_session: str, role: str, source_class: str) -> bool:
    qsession = (qsession or 'UNKNOWN').upper()
    report_session = (report_session or 'UNKNOWN').upper()
    if source_class == 'PERSISTED_STOP_EVENT':
        return True
    if role == 'valuation' and source_class == 'COMPLETED_DAILY_CLOSE':
        return report_session in {'CLOSED', 'PRE_MARKET'}
    if qsession == report_session:
        return True
    if role == 'display' and qsession in {'PRE_MARKET', 'REGULAR', 'AFTER_MARKET', 'CLOSED'}:
        return True
    return False

def _sort_key(q: dict[str, Any], role: str) -> tuple[int, float]:
    cls = q.get('source_class') or q.get('source') or ''
    pref = {'PERSISTED_STOP_EVENT': 0 if role == 'stop' else 99, 'PROVIDER_TRADE': 1, 'PROVIDER_MINUTE_CLOSE': 2, 'PROVIDER_AGGREGATE': 3, 'PROVIDER_SNAPSHOT': 4, 'COMPLETED_DAILY_CLOSE': 5, 'CACHE': 6, 'FALLBACK_DISPLAY_ONLY': 90, 'REFERENCE': 91, 'ENTRY_REFERENCE': 92}.get(cls, 80)
    ts = parse_dt(q.get('timestamp'))
    return (pref, -(ts.timestamp() if ts else 0.0))

def select_quotes(quotes: list[dict[str, Any]], *, report_session: str, now: datetime, prior_event_timestamp: Any=None) -> dict[str, Any]:
    """Select separate display, valuation, and stop-evaluation prices.

    Persisted stop events may feed stop_evaluation only; they never silently become display/valuation.
    """
    now = now.astimezone(timezone.utc)
    report_session = report_session.upper()
    prior_ts = parse_dt(prior_event_timestamp)
    rejected: list[dict[str, Any]] = []
    candidates = {'display': [], 'valuation': [], 'stop': []}
    valid_for_conflict: list[dict[str, Any]] = []
    for q in quotes or []:
        q = dict(q)
        price = _valid_price(q.get('price'))
        cls = str(q.get('source_class') or q.get('source') or '').upper()
        q['source_class'] = cls
        qsession = str(q.get('session') or 'UNKNOWN').upper()
        q['session'] = qsession
        ts = parse_dt(q.get('timestamp'))
        if q.get('rejection_reason'):
            rejected.append(_quote_reject(q, str(q.get('rejection_reason'))))
            continue
        if price is None:
            rejected.append(_quote_reject(q, 'PRICE_INVALID'))
            continue
        if q.get('bid') not in (None, '') and q.get('ask') not in (None, ''):
            try:
                if float(q['bid']) > float(q['ask']):
                    rejected.append(_quote_reject(q, 'CROSSED_QUOTE_REJECTED'))
                    continue
            except Exception:
                rejected.append(_quote_reject(q, 'BID_ASK_MALFORMED'))
                continue
        if cls not in DISPLAY_SOURCE_CLASSES:
            rejected.append(_quote_reject(q, 'SOURCE_CLASS_INVALID'))
            continue
        if cls not in {'FALLBACK_DISPLAY_ONLY', 'REFERENCE', 'ENTRY_REFERENCE'}:
            if not ts:
                rejected.append(_quote_reject(q, 'TIMESTAMP_MISSING_OR_MALFORMED'))
                continue
            if (ts - now).total_seconds() > 30:
                rejected.append(_quote_reject(q, 'FUTURE_TIMESTAMP_REJECTED'))
                continue
        if cls != 'PERSISTED_STOP_EVENT' and _session_ok(qsession, report_session, 'display', cls):
            candidates['display'].append(q)
        if cls in VALUATION_SOURCE_CLASSES and ts and _age_ok(ts, now, report_session if cls != 'COMPLETED_DAILY_CLOSE' else 'CLOSED', 'valuation') and _session_ok(qsession, report_session, 'valuation', cls):
            candidates['valuation'].append(q)
        if cls in STOP_EVAL_SOURCE_CLASSES:
            if cls == 'PERSISTED_STOP_EVENT':
                if not q.get('event_id'):
                    rejected.append(_quote_reject(q, 'STOP_EVENT_ID_MISSING'))
                    continue
                if q.get('trade_id') in (None, ''):
                    rejected.append(_quote_reject(q, 'STOP_EVENT_TRADE_ID_MISSING'))
                    continue
                if q.get('event_stop') in (None, '') and q.get('stop') in (None, ''):
                    rejected.append(_quote_reject(q, 'STOP_EVENT_STOP_MISSING'))
                    continue
                if ts:
                    candidates['stop'].append(q)
                else:
                    rejected.append(_quote_reject(q, 'STOP_EVENT_TIMESTAMP_INVALID'))
            elif ts and _age_ok(ts, now, report_session, 'stop') and _session_ok(qsession, report_session, 'stop', cls):
                if prior_ts and ts <= prior_ts and q.get('clears_prior_event'):
                    rejected.append(_quote_reject(q, 'OLDER_THAN_PRIOR_EVENT_CANNOT_CLEAR'))
                    continue
                candidates['stop'].append(q)
                valid_for_conflict.append(q)
    conflict = False
    fresh_stop = [q for q in valid_for_conflict if q.get('source_class') != 'PERSISTED_STOP_EVENT']
    for i, a in enumerate(fresh_stop):
        for b in fresh_stop[i + 1:]:
            ta, tb = (parse_dt(a.get('timestamp')), parse_dt(b.get('timestamp')))
            if ta and tb and (abs((ta - tb).total_seconds()) <= 60) and (a.get('session') == b.get('session')):
                pa, pb = (float(a['price']), float(b['price']))
                if abs(pa - pb) / max(pa, pb) > 0.005:
                    conflict = True
                    rejected.append(_quote_reject(a, 'CONFLICTING_SAME_SESSION_QUOTES'))
                    rejected.append(_quote_reject(b, 'CONFLICTING_SAME_SESSION_QUOTES'))

    def pick(role: str) -> Optional[dict[str, Any]]:
        arr = candidates[role]
        if role == 'stop' and conflict:
            return None
        return sorted(arr, key=lambda q: _sort_key(q, role))[0] if arr else None
    d, v, s = (pick('display'), pick('valuation'), pick('stop'))

    def role(q: Optional[dict[str, Any]], name: str) -> dict[str, Any]:
        if not q:
            return asdict(PriceRole(None, 'UNAVAILABLE', None, f'{name.upper()}_UNAVAILABLE', 'no valid quote'))
        cls = q.get('source_class')
        out = asdict(PriceRole(float(q['price']), cls, parse_dt(q.get('timestamp')).isoformat().replace('+00:00', 'Z') if parse_dt(q.get('timestamp')) else q.get('timestamp'), f'{name.upper()}_VALID', q.get('reason')))
        if cls == 'PERSISTED_STOP_EVENT':
            out.update({'event_id': q.get('event_id'), 'trade_id': q.get('trade_id'), 'lot_id': q.get('lot_id'), 'ticker': q.get('ticker'), 'event_timestamp': q.get('timestamp'), 'event_price': q.get('price'), 'event_stop': q.get('event_stop') if q.get('event_stop') not in (None, '') else q.get('stop'), 'validity_state': q.get('validity_state') or 'ACTIVE_STOP_BREACH', 'supersession_proof': q.get('supersession_proof') or 'NO_SUPERSEDING_EVENT_IN_FIXTURE', 'source_digest': sha_json({k: q.get(k) for k in ('event_id', 'trade_id', 'lot_id', 'ticker', 'timestamp', 'price', 'event_stop', 'stop', 'source_class')})})
        return out
    proof = 'separate display/valuation/stop-evaluation selection; persisted stop event cannot become current market display/valuation'
    return {'selection_policy_version': QUOTE_SELECTION_VERSION, 'report_session': report_session, 'selected_display_price': role(d, 'display'), 'selected_valuation_price': role(v, 'valuation'), 'selected_stop_evaluation_price': role(s, 'stop_eval'), 'rejected_quotes': rejected, 'timestamp_ordering_proof': proof}

def retention_expiry(reason_codes: Iterable[str], since: datetime) -> tuple[datetime, str, tuple[str, ...], str]:
    reasons = set(normalize_reason_codes(reason_codes))
    if 'PREMARKET_STOP_BREACH' in reasons:
        return (since + timedelta(hours=8), 'PREMARKET_STOP_RETAIN_UNTIL_REGULAR_VERIFICATION', ('FRESH_REGULAR_QUOTE_ABOVE_STOP', 'NO_ACTIVE_REGULAR_STOP_EVENT'), 'DATA_INCOMPLETE_STALE_REVIEW')
    if 'REGULAR_STOP_BREACH' in reasons:
        return (since + timedelta(hours=24), 'REGULAR_STOP_RETAIN_UNTIL_CLEAR_OR_NEXT_CLOSE_PLUS_RUN', ('BROKER_FILL_OR_VALID_STOP_CLEAR',), 'DATA_INCOMPLETE_LIFECYCLE_CONTRADICTION')
    if 'PROFIT_GIVEBACK' in reasons or 'PROFIT_PROTECTION_TRIM_REVIEW' in reasons or 'TARGET_ZONE_REACHED' in reasons:
        return (since + timedelta(days=2), 'PROFIT_REVIEW_RETAIN_TWO_COMPLETED_SESSIONS', ('FRESH_PP_EXPLICIT_CLEAR',), 'DATA_INCOMPLETE_EXPIRED_STRONG_ACTION')
    if 'CATALYST_RISK' in reasons:
        return (since + timedelta(days=3), 'CATALYST_RETAIN_UNTIL_EVENT_RESOLUTION', ('EVENT_OUTCOME_OR_POST_EVENT_EVIDENCE',), 'DATA_INCOMPLETE_EXPIRED_STRONG_ACTION')
    return (since + timedelta(days=2), 'THESIS_REVIEW_RETAIN_TWO_COMPLETED_SESSIONS', ('FRESH_DAILY_EXPLICIT_CLEAR',), 'DATA_INCOMPLETE_EXPIRED_STRONG_ACTION')

def can_clear(prior: dict[str, Any] | None, clearing: dict[str, Any] | None, *, now: datetime) -> tuple[bool, Optional[dict[str, Any]], str]:
    if not prior or not prior.get('action'):
        return (False, None, 'NO_PRIOR_ACTION')
    if not clearing:
        return (False, None, 'NO_CLEARING_EVIDENCE')
    prior_reasons = set(normalize_reason_codes(prior.get('reason_codes') or ()))
    clear_reasons = set(normalize_reason_codes(clearing.get('reason_codes') or ()))
    ts = parse_dt(clearing.get('timestamp'))
    prior_ts = parse_dt(prior.get('timestamp') or prior.get('retained_since'))
    if not ts or (prior_ts and ts <= prior_ts):
        return (False, None, 'CLEARING_TIMESTAMP_NOT_AFTER_PRIOR')
    if str(clearing.get('freshness') or '').upper() not in {'FRESH', 'VALID'}:
        return (False, None, 'CLEARING_SOURCE_NOT_FRESH')
    reason_ok = False
    if 'PREMARKET_STOP_BREACH' in prior_reasons:
        reason_ok = 'EXPLICIT_STOP_CLEAR' in clear_reasons and bool(clearing.get('fresh_regular_quote_above_stop')) and (not clearing.get('active_regular_stop_event'))
    elif 'REGULAR_STOP_BREACH' in prior_reasons:
        reason_ok = 'EXPLICIT_STOP_CLEAR' in clear_reasons and bool(clearing.get('broker_or_manual_or_stop_change_clear'))
    elif prior_reasons & {'PROFIT_GIVEBACK', 'PROFIT_PROTECTION_TRIM_REVIEW', 'TARGET_ZONE_REACHED'}:
        reason_ok = 'EXPLICIT_PROFIT_CLEAR' in clear_reasons and bool(clearing.get('profit_metrics_resolved'))
    elif prior_reasons & {'THESIS_DETERIORATION', 'THESIS_BROKEN', 'SECTOR_BREAKDOWN', 'REGIME_RISK', 'CATALYST_RISK'}:
        reason_ok = 'EXPLICIT_THESIS_CLEAR' in clear_reasons and bool(clearing.get('dimensions_recovered') or clearing.get('event_resolved'))
    if not reason_ok:
        return (False, None, 'GENERIC_HOLD_DOES_NOT_CLEAR')
    cleared_by = {'source': clearing.get('source'), 'timestamp': iso(ts), 'digest': clearing.get('digest') or sha_json(clearing), 'reason_code': sorted(clear_reasons)[0] if clear_reasons else 'UNKNOWN', 'human_reason': clearing.get('human_reason') or 'explicit reason-based clearing evidence accepted'}
    return (True, cleared_by, 'CLEARED')

def _component_action(comp: dict[str, Any] | None) -> tuple[str, tuple[str, ...], str]:
    comp = comp or {}
    freshness = str(comp.get('freshness') or 'MISSING').upper()
    if freshness not in {'FRESH', 'VALID'}:
        return ('DATA INCOMPLETE', ('DATA_STALE_OR_MISSING',), freshness)
    return (normalize_action(comp.get('action')), normalize_reason_codes(comp.get('reason_codes') or ()), freshness)

def _prepare_quotes_for_trade(quotes: list[dict[str, Any]], trade: dict[str, Any], stop: float | None) -> list[dict[str, Any]]:
    """Attach fail-closed rejection reasons to malformed persisted stop events.

    This preserves raw fixture shape while ensuring `select_quotes()` cannot use
    a persisted stop event for stop evaluation unless event id, trade/ticker/lot
    match, timestamp, event price, and event stop evidence are present.
    """
    out = []
    trade_id = trade.get('trade_id') or trade.get('id')
    lot_id = trade.get('lot_id')
    ticker = str(trade.get('ticker') or '').upper()
    for raw in quotes or []:
        q = dict(raw)
        if str(q.get('source_class') or q.get('source') or '').upper() == 'PERSISTED_STOP_EVENT':
            reason = None
            if not q.get('event_id'):
                reason = 'STOP_EVENT_ID_MISSING'
            elif q.get('trade_id') in (None, ''):
                reason = 'STOP_EVENT_TRADE_ID_MISSING'
            elif str(q.get('ticker') or '').upper() != ticker:
                reason = 'STOP_EVENT_TICKER_MISMATCH'
            elif trade_id is not None and str(q.get('trade_id')) != str(trade_id):
                reason = 'STOP_EVENT_TRADE_ID_MISMATCH'
            elif lot_id not in (None, '') and q.get('lot_id') not in (None, '') and (str(q.get('lot_id')) != str(lot_id)):
                reason = 'STOP_EVENT_LOT_ID_MISMATCH'
            elif not q.get('timestamp'):
                reason = 'STOP_EVENT_TIMESTAMP_INVALID'
            elif q.get('price') in (None, ''):
                reason = 'STOP_EVENT_PRICE_MISSING'
            elif q.get('event_stop') in (None, '') and q.get('stop') in (None, ''):
                reason = 'STOP_EVENT_STOP_MISSING'
            if reason:
                q['rejection_reason'] = reason
        out.append(q)
    return out

def build_holding_state(*, trade: dict[str, Any], quotes: list[dict[str, Any]], report_session: str, now: datetime, daily: dict[str, Any] | None=None, profit_protection: dict[str, Any] | None=None, broker: dict[str, Any] | None=None, prior_action: dict[str, Any] | None=None, clearing_evidence: dict[str, Any] | None=None, ledger: 'ActionLedger' | None=None) -> dict[str, Any]:
    now = now.astimezone(timezone.utc)
    ticker = str(trade.get('ticker') or '').upper()
    stop = _valid_price(trade.get('stop') or trade.get('stop_loss'))
    quotes = _prepare_quotes_for_trade(quotes, trade, stop)
    qs = select_quotes(quotes, report_session=report_session, now=now, prior_event_timestamp=(prior_action or {}).get('timestamp'))
    stop_price = qs['selected_stop_evaluation_price'].get('price')
    observed_state = 'PRICE_UNAVAILABLE'
    obs_reasons: tuple[str, ...] = ()
    stop_action = None
    if stop_price is not None and stop is not None:
        sp = float(stop_price)
        if sp <= stop:
            if report_session == 'REGULAR':
                observed_state = 'STOP_BREACHED_REGULAR'
                obs_reasons = ('REGULAR_STOP_BREACH',)
                stop_action = 'SELL NOW'
            elif report_session == 'PRE_MARKET':
                observed_state = 'STOP_BREACHED_PRE_MARKET'
                obs_reasons = ('PREMARKET_STOP_BREACH',)
                stop_action = 'EXIT REVIEW'
            elif report_session == 'AFTER_MARKET':
                observed_state = 'STOP_BREACHED_AFTER_MARKET'
                obs_reasons = ('AFTERHOURS_STOP_BREACH',)
                stop_action = 'EXIT REVIEW'
            else:
                observed_state = 'STOP_BREACHED_REGULAR'
                obs_reasons = ('REGULAR_STOP_BREACH',)
                stop_action = 'SELL NOW'
        elif sp <= stop * 1.015:
            observed_state = 'NEAR_STOP'
            obs_reasons = ()
        else:
            observed_state = 'ABOVE_STOP'
            obs_reasons = ()
    elif qs['rejected_quotes']:
        observed_state = 'INVALID_OR_STALE_EVENT'
        obs_reasons = ('DATA_STALE_OR_MISSING',)
    daily_action, daily_reasons, daily_fresh = _component_action(daily)
    pp_action, pp_reasons, pp_fresh = _component_action(profit_protection)
    current_action = strongest_action(stop_action, daily_action, pp_action, 'HOLD')
    current_reasons = normalize_reason_codes(obs_reasons + daily_reasons + pp_reasons)
    daily_missing = daily is None
    if daily_missing and (not prior_action):
        current_action = 'DATA INCOMPLETE'
        current_reasons = normalize_reason_codes(current_reasons + ('DATA_STALE_OR_MISSING',))
    broker = broker or {'state': 'NO_BROKER_EVENT', 'event_ids': []}
    broker_state = str(broker.get('state') or 'NO_BROKER_EVENT').upper()
    broker_lifecycle = BrokerLifecycle(state=broker_state, event_ids=tuple(broker.get('event_ids') or ()))
    lifecycle_reconciliation_blocked = broker_state in {'BROKER_SELL_FILLED', 'CASH_CREDIT_POSTED'} and str(trade.get('status') or 'OPEN').upper() == 'OPEN'
    if lifecycle_reconciliation_blocked:
        observed_state = 'LIFECYCLE_CONTRADICTION'
        current_action = 'DATA INCOMPLETE'
        current_reasons = normalize_reason_codes(current_reasons + ('LIFECYCLE_CONTRADICTION',))
        qs['selected_valuation_price'] = {'price': None, 'source': 'RECONCILIATION_BLOCKED', 'timestamp': None, 'validity': 'VALUATION_RECONCILIATION_BLOCKED', 'reason': 'broker filled/cash credited while DB trade remains OPEN'}
        qs['timestamp_ordering_proof'] = (qs.get('timestamp_ordering_proof') or '') + '; valuation blocked by lifecycle reconciliation contradiction'
    ledger_event_type = 'ACTION_CREATED'
    retention = RetentionState()
    cleared_by = None
    prior_norm = normalize_action((prior_action or {}).get('action')) if prior_action else None
    prior_reasons = normalize_reason_codes((prior_action or {}).get('reason_codes') or ()) if prior_action else ()
    if prior_action and prior_norm in STRONG_ACTIONS:
        ok_clear, cleared_by, clear_reason = can_clear(prior_action, clearing_evidence, now=now)
        since = parse_dt(prior_action.get('retained_since') or prior_action.get('timestamp')) or now
        exp = parse_dt(prior_action.get('retention_expires_at'))
        calc_exp, calc_policy, calc_required, calc_expiry_behavior = retention_expiry(prior_reasons, since)
        if not exp:
            exp = calc_exp
        policy = prior_action.get('retention_policy') or calc_policy
        required = tuple(prior_action.get('required_clearing_evidence') or calc_required)
        expiry_behavior = prior_action.get('expiry_behavior') or calc_expiry_behavior
        if policy == 'EXTERNAL_POLICY' or not required:
            policy = calc_policy
            required = calc_required
            expiry_behavior = calc_expiry_behavior
        if ok_clear:
            ledger_event_type = 'ACTION_CLEARED'
            retention = RetentionState(prior_norm, iso(since), iso(exp), policy, prior_reasons, required, cleared_by, expiry_behavior)
        elif now > exp:
            current_action = 'DATA INCOMPLETE'
            current_reasons = ('RETENTION_EXPIRED_WITHOUT_CLEARING_EVIDENCE',)
            ledger_event_type = 'SOURCE_SUPERSEDED'
            retention = RetentionState(prior_norm, iso(since), iso(exp), policy, prior_reasons, required, None, expiry_behavior)
        elif ACTION_RANK.get(prior_norm, 99) < ACTION_RANK.get(current_action, 99):
            current_action = prior_norm
            current_reasons = prior_reasons + tuple((r for r in current_reasons if r not in prior_reasons))
            ledger_event_type = 'ACTION_RETAINED_STALE_INPUT' if clear_reason != 'CLEARED' else 'ACTION_CREATED'
            retention = RetentionState(prior_norm, iso(since), iso(exp), policy, prior_reasons, required, None, expiry_behavior)
        elif ACTION_RANK.get(current_action, 99) < ACTION_RANK.get(prior_norm, 99):
            ledger_event_type = 'ACTION_STRENGTHENED'
    if lifecycle_reconciliation_blocked:
        current_action = 'DATA INCOMPLETE'
        observed_state = 'LIFECYCLE_CONTRADICTION'
        current_reasons = normalize_reason_codes(current_reasons + ('LIFECYCLE_CONTRADICTION',))
        ledger_event_type = 'LIFECYCLE_CONTRADICTION'
    axes = {'observed_market_risk_state': asdict(AxisState(observed_state, current_reasons, None, iso(now))), 'advisory_action': asdict(AdvisoryAction(current_action, current_reasons, 'CANONICAL_PRECEDENCE_ENGINE', None)), 'broker_ledger_lifecycle': asdict(broker_lifecycle)}
    stop_eval = qs.get('selected_stop_evaluation_price') or {}
    components = {'daily_reunderwriting': {'action': daily_action, 'freshness': daily_fresh, 'reason_codes': daily_reasons, 'digest': sha_json(daily or {})}, 'profit_protection': {'action': pp_action, 'freshness': pp_fresh, 'reason_codes': pp_reasons, 'digest': sha_json(profit_protection or {})}, 'stop_lifecycle': {'state': observed_state, 'event_id': stop_eval.get('event_id'), 'trade_id': stop_eval.get('trade_id'), 'lot_id': stop_eval.get('lot_id'), 'ticker': stop_eval.get('ticker'), 'event_timestamp': stop_eval.get('event_timestamp'), 'event_price': stop_eval.get('event_price'), 'event_stop': stop_eval.get('event_stop'), 'validity_state': stop_eval.get('validity_state') or ('ACTIVE_STOP_BREACH' if stop_eval.get('source') == 'PERSISTED_STOP_EVENT' and observed_state.startswith('STOP_BREACHED') else None), 'supersession_proof': stop_eval.get('supersession_proof'), 'source_digest': stop_eval.get('source_digest'), 'validity_reason': ';'.join(obs_reasons) or 'NO_ACTIVE_STOP_EVENT'}}
    trade_identity = {'trade_id': trade.get('trade_id') or trade.get('id'), 'lot_id': trade.get('lot_id'), 'ticker': ticker, 'status': trade.get('status', 'OPEN'), 'quantity': trade.get('quantity'), 'entry_price': trade.get('entry_price'), 'entry_at': trade.get('entry_at')}
    canonical_input = {'trade_identity': trade_identity, 'quote_selection': qs, 'components': components, 'broker': asdict(broker_lifecycle), 'prior_action': prior_action, 'clearing_evidence': clearing_evidence}
    input_digest = sha_json(canonical_input)
    final_precedence = {'selected_advisory_action': current_action, 'selected_observed_state': observed_state, 'selected_broker_lifecycle_state': broker_lifecycle.state, 'precedence_reason': f'separate axes; advisory={current_action}; observed={observed_state}; broker={broker_lifecycle.state}', 'component_freshness': {'quote': qs['selected_stop_evaluation_price'].get('validity'), 'daily': daily_fresh, 'profit_protection': pp_fresh, 'broker': broker_lifecycle.state}}
    packet = {'schema_version': SCHEMA_VERSION, 'generated_at': iso(now), 'ticker': ticker, 'trade_identity': trade_identity, 'quote_selection': qs, 'axes': axes, 'retention': asdict(retention), 'clearing': {'clearance_status': 'CLEARED' if cleared_by else 'EXPIRED_TO_DATA_INCOMPLETE' if ledger_event_type == 'SOURCE_SUPERSEDED' else 'NOT_CLEARED', 'cleared_by': cleared_by}, 'components': components, 'final_precedence': final_precedence, 'ledger': {'latest_event_id': None, 'events_applied': [], 'idempotency_key': None}, 'authority': {'report_local_authority_allowed': False, 'broker_authority': 'NO', 'automatic_trade_closure': 'NO'}, 'digests': {'canonical_input_digest': input_digest, 'packet_digest': None}}
    packet['digests']['packet_digest'] = sha_json({k: v for k, v in packet.items() if k != 'ledger'})
    if ledger is not None:
        res = ledger.append_event(trade_identity=trade_identity, event_type=ledger_event_type, observed_state=observed_state, advisory_action=current_action, broker_lifecycle_state=broker_lifecycle.state, reason_codes=current_reasons, source_type='CANONICAL_CORE', source_timestamp=iso(now), source_digest=input_digest, prior_event_id=(prior_action or {}).get('ledger_event_id'), clearing_reason=(cleared_by or {}).get('reason_code'))
        packet['ledger'] = {'latest_event_id': res['event_id'], 'events_applied': [res['event_id']], 'idempotency_key': res['event_id'], 'status': res['status']}
    ok, errors = validate_packet_shape(packet)
    if not ok:
        raise ValueError('PACKET_SCHEMA_INVALID:' + ','.join(errors))
    return packet

class ActionLedger:

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        con = sqlite3.connect(self.path)
        con.execute('PRAGMA foreign_keys=ON')
        return con

    def _init(self):
        con = self._connect()
        try:
            con.execute('CREATE TABLE IF NOT EXISTS action_ledger_events(\n                event_id TEXT PRIMARY KEY,\n                schema_version TEXT NOT NULL,\n                trade_id TEXT,\n                ticker TEXT NOT NULL,\n                event_type TEXT NOT NULL,\n                action_axis TEXT NOT NULL,\n                observed_state TEXT NOT NULL,\n                advisory_action TEXT NOT NULL,\n                broker_lifecycle_state TEXT NOT NULL,\n                reason_codes_json TEXT NOT NULL,\n                source_type TEXT NOT NULL,\n                source_timestamp TEXT NOT NULL,\n                source_digest TEXT NOT NULL,\n                prior_event_id TEXT,\n                clearing_reason TEXT,\n                event_json TEXT NOT NULL,\n                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n            )')
            con.commit()
        finally:
            con.close()

    @staticmethod
    def event_identity(*, trade_identity: dict[str, Any], event_type: str, observed_state: str, advisory_action: str, broker_lifecycle_state: str, reason_codes: Iterable[str], source_type: str, source_timestamp: str, source_digest: str, prior_event_id: Any=None, clearing_reason: Any=None) -> str:
        obj = {'schema_version': LEDGER_SCHEMA_VERSION, 'trade_id': str(trade_identity.get('trade_id') or ''), 'ticker': str(trade_identity.get('ticker') or '').upper(), 'event_type': event_type, 'action_axis': 'ADVISORY', 'observed_state': observed_state, 'advisory_action': advisory_action, 'broker_lifecycle_state': broker_lifecycle_state, 'reason_codes': sorted(normalize_reason_codes(reason_codes)), 'source_type': source_type, 'source_timestamp': source_timestamp, 'source_digest': source_digest, 'prior_event_id': prior_event_id or '', 'clearing_reason': clearing_reason or ''}
        return hashlib.sha256(stable_json(obj).encode()).hexdigest()

    def append_event(self, **kwargs) -> dict[str, Any]:
        event_type = kwargs['event_type']
        if event_type not in LEDGER_EVENT_TYPES or event_type == 'IDEMPOTENT_NO_OP':
            raise ValueError('INVALID_LEDGER_EVENT_TYPE')
        event_id = self.event_identity(**kwargs)
        event = {'event_id': event_id, 'schema_version': LEDGER_SCHEMA_VERSION, **kwargs}
        con = self._connect()
        try:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT event_id FROM action_ledger_events WHERE event_id=?', (event_id,)).fetchone()
            if row:
                con.commit()
                return {'status': 'IDEMPOTENT_NO_OP', 'event_id': event_id}
            ti = kwargs['trade_identity']
            con.execute('INSERT INTO action_ledger_events(event_id,schema_version,trade_id,ticker,event_type,action_axis,observed_state,advisory_action,broker_lifecycle_state,reason_codes_json,source_type,source_timestamp,source_digest,prior_event_id,clearing_reason,event_json)\n                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (event_id, LEDGER_SCHEMA_VERSION, str(ti.get('trade_id') or ''), str(ti.get('ticker') or '').upper(), event_type, 'ADVISORY', kwargs['observed_state'], kwargs['advisory_action'], kwargs['broker_lifecycle_state'], stable_json(sorted(normalize_reason_codes(kwargs['reason_codes']))), kwargs['source_type'], kwargs['source_timestamp'], kwargs['source_digest'], kwargs.get('prior_event_id'), kwargs.get('clearing_reason'), stable_json(event)))
            con.commit()
            return {'status': 'INSERTED', 'event_id': event_id}
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def count(self) -> int:
        con = self._connect()
        try:
            return int(con.execute('SELECT COUNT(*) FROM action_ledger_events').fetchone()[0])
        finally:
            con.close()

    def simulate_partial_failure(self, first_kwargs: dict[str, Any], second_kwargs: dict[str, Any]) -> None:
        con = self._connect()
        try:
            con.execute('BEGIN IMMEDIATE')
            event_id = self.event_identity(**first_kwargs)
            ti = first_kwargs['trade_identity']
            con.execute('INSERT INTO action_ledger_events(event_id,schema_version,trade_id,ticker,event_type,action_axis,observed_state,advisory_action,broker_lifecycle_state,reason_codes_json,source_type,source_timestamp,source_digest,prior_event_id,clearing_reason,event_json)\n                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (event_id, LEDGER_SCHEMA_VERSION, str(ti.get('trade_id') or ''), str(ti.get('ticker') or '').upper(), first_kwargs['event_type'], 'ADVISORY', first_kwargs['observed_state'], first_kwargs['advisory_action'], first_kwargs['broker_lifecycle_state'], stable_json(sorted(normalize_reason_codes(first_kwargs['reason_codes']))), first_kwargs['source_type'], first_kwargs['source_timestamp'], first_kwargs['source_digest'], first_kwargs.get('prior_event_id'), first_kwargs.get('clearing_reason'), stable_json(first_kwargs)))
            raise RuntimeError('SIMULATED_PARTIAL_LEDGER_FAILURE')
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

def reconstruct_from_ledger(path: str | Path) -> dict[str, Any]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute('SELECT event_id,event_json FROM action_ledger_events ORDER BY event_id')]
        digest = sha_json(rows)
        return {'schema_version': LEDGER_SCHEMA_VERSION, 'event_count': len(rows), 'reconstruction_digest': digest, 'events': rows}
    finally:
        con.close()
