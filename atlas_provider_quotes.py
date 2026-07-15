"""Deterministic provider candidate normalization; no live provider calls."""
from __future__ import annotations
from atlas_holding_state_schema import digest
def normalize_candidates(rows):
 out=[]
 for row in rows or []:
  r=dict(row);r['accepted']=bool(r.get('accepted'));out.append(r)
 return sorted(out,key=lambda x:(str(x.get('provider')),str(x.get('observed_at')),str(x.get('value'))))
def candidates_digest(rows):return digest(normalize_candidates(rows))

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from datetime import datetime, timezone
from typing import Any
import hashlib, json, math
from atlas_holding_state_authority import parse_dt, select_quotes
from atlas_nyse_calendar import classify_session
SCHEMA_VERSION = 'atlas_provider_quotes.v2'
PROVIDER_PRIORITY = ('MASSIVE_LAST_TRADE', 'MASSIVE_SNAPSHOT', 'MASSIVE_MINUTE_CLOSE', 'EODHD_REALTIME', 'EODHD_DAILY_CLOSE')
SOURCE_PRIORITY = {'MASSIVE_LAST_TRADE': ('MASSIVE', 'PROVIDER_TRADE', 0), 'MASSIVE_SNAPSHOT': ('MASSIVE', 'PROVIDER_SNAPSHOT', 1), 'MASSIVE_MINUTE_CLOSE': ('MASSIVE', 'PROVIDER_MINUTE_CLOSE', 2), 'EODHD_REALTIME': ('EODHD', 'PROVIDER_SNAPSHOT', 3), 'EODHD_DAILY_CLOSE': ('EODHD', 'COMPLETED_DAILY_CLOSE', 4)}
TTL = {'REGULAR': 300, 'PRE_MARKET': 900, 'AFTER_MARKET': 900, 'CLOSED': 57600}

def stable_digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) and v > 0 else None
    except Exception:
        return None

def _iso_from_epoch(value):
    if value in (None, ''):
        return None
    try:
        v = float(value)
        if v > 1e+17:
            v /= 1000000000.0
        elif v > 100000000000000.0:
            v /= 1000000.0
        elif v > 100000000000.0:
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
    except Exception:
        return None

def parse_massive_last_trade(ticker: str, raw: dict[str, Any]) -> dict[str, Any]:
    r = (raw or {}).get('results') or (raw or {}).get('last') or raw or {}
    return {'ticker': ticker, 'provider': 'MASSIVE', 'provider_route': 'MASSIVE_LAST_TRADE', 'source_class': 'PROVIDER_TRADE', 'price': r.get('p') or r.get('price'), 'timestamp': _iso_from_epoch(r.get('t') or r.get('timestamp')), 'bid': None, 'ask': None, 'adjusted': True, 'raw_provenance_digest': stable_digest(raw)}

def parse_massive_snapshot(ticker: str, raw: dict[str, Any]) -> dict[str, Any]:
    t = (raw or {}).get('ticker') or raw or {}
    lt = t.get('lastTrade') or {}
    lq = t.get('lastQuote') or {}
    day = t.get('day') or {}
    minute = t.get('min') or {}
    return {'ticker': ticker, 'provider': 'MASSIVE', 'provider_route': 'MASSIVE_SNAPSHOT', 'source_class': 'PROVIDER_SNAPSHOT', 'price': lt.get('p') or minute.get('c') or day.get('c'), 'timestamp': _iso_from_epoch(lt.get('t') or minute.get('t') or t.get('updated')), 'bid': lq.get('p') or lq.get('bp'), 'ask': lq.get('P') or lq.get('ap'), 'adjusted': True, 'raw_provenance_digest': stable_digest(raw)}

def parse_massive_minute(ticker: str, raw: dict[str, Any]) -> dict[str, Any]:
    rows = (raw or {}).get('results') or []
    r = rows[-1] if rows else {}
    return {'ticker': ticker, 'provider': 'MASSIVE', 'provider_route': 'MASSIVE_MINUTE_CLOSE', 'source_class': 'PROVIDER_MINUTE_CLOSE', 'price': r.get('c'), 'timestamp': _iso_from_epoch(r.get('t')), 'bid': None, 'ask': None, 'adjusted': True, 'raw_provenance_digest': stable_digest(raw)}

def parse_eodhd(ticker: str, raw: Any, *, daily=False) -> dict[str, Any]:
    r = (raw[-1] if isinstance(raw, list) and raw else raw) or {}
    raw_ts = r.get('timestamp') if r.get('timestamp') not in (None, '') else r.get('datetime') if r.get('datetime') not in (None, '') else r.get('date')
    ts = _iso_from_epoch(raw_ts) if isinstance(raw_ts, (int, float)) else raw_ts
    raw_price_field = 'adjusted_close' if r.get('adjusted_close') is not None else 'close' if r.get('close') is not None else 'price'
    raw_price = r.get(raw_price_field)
    route = 'EODHD_DAILY_CLOSE' if daily else 'EODHD_REALTIME'
    source_session = classify_session(parse_dt(ts))['session'] if parse_dt(ts) else None
    return {'ticker': ticker, 'provider': 'EODHD', 'provider_route': route, 'source_class': 'COMPLETED_DAILY_CLOSE' if daily else 'PROVIDER_SNAPSHOT', 'price': raw_price, 'timestamp': ts, 'source_session': source_session, 'raw_timestamp_field': raw_ts, 'raw_price_field_name': raw_price_field, 'raw_price_field': raw_price, 'bid': r.get('bid'), 'ask': r.get('ask'), 'adjusted': True if r.get('adjusted_close') is not None else r.get('adjusted'), 'raw_provenance_digest': stable_digest(raw)}

def normalize(candidates: list[dict[str, Any]], *, now: datetime, reference_prices: dict[str, float] | None=None, corporate_actions: dict[str, dict[str, Any]] | None=None) -> dict[str, Any]:
    reference_prices = reference_prices or {}
    corporate_actions = corporate_actions or {}
    now = now.astimezone(timezone.utc)
    session = classify_session(now)['session']
    valid = []
    rejected = []
    for raw in candidates or []:
        q = dict(raw)
        ticker = str(q.get('ticker') or '').upper()
        route = str(q.get('provider_route') or '').upper()
        reason = None
        price = _num(q.get('price'))
        ts = parse_dt(q.get('timestamp'))
        if not ticker:
            reason = 'TICKER_MISSING'
        elif route not in SOURCE_PRIORITY:
            reason = 'PROVIDER_ROUTE_UNSUPPORTED'
        elif price is None:
            reason = 'PRICE_INVALID'
        elif not ts:
            reason = 'TIMESTAMP_MISSING_OR_MALFORMED'
        elif (ts - now).total_seconds() > 30:
            reason = 'FUTURE_TIMESTAMP_REJECTED'
        elif route == 'EODHD_DAILY_CLOSE' and session != 'CLOSED':
            reason = 'DAILY_CLOSE_LIVE_SESSION_MISMATCH'
        elif route != 'EODHD_DAILY_CLOSE' and q.get('source_session') and (q.get('source_session') != session):
            reason = 'WRONG_SESSION'
        elif (now - ts).total_seconds() > TTL.get(session, 300) and q.get('source_class') != 'COMPLETED_DAILY_CLOSE':
            reason = 'STALE_QUOTE'
        elif q.get('bid') not in (None, '') and q.get('ask') not in (None, '') and (_num(q.get('bid')) is None or _num(q.get('ask')) is None):
            reason = 'BID_ASK_MALFORMED'
        elif q.get('bid') not in (None, '') and q.get('ask') not in (None, '') and (float(q['bid']) > float(q['ask'])):
            reason = 'CROSSED_QUOTE_REJECTED'
        ca = corporate_actions.get(ticker) or {}
        if not reason and ca:
            if ca.get('requires_adjusted') and q.get('adjusted') is not True:
                reason = 'CORPORATE_ACTION_ADJUSTMENT_MISMATCH'
            elif ca.get('split_factor') not in (None, 1, 1.0) and q.get('split_factor') not in (ca.get('split_factor'),):
                reason = 'CORPORATE_ACTION_SPLIT_FACTOR_MISMATCH'
        ref = _num(reference_prices.get(ticker))
        if not reason and ref and (abs(price - ref) / max(price, ref) > 0.5) and (not ca.get('verified_reference_reset')):
            reason = 'SANITY_BAND_REJECTED'
        provider, source_class, priority = SOURCE_PRIORITY.get(route, (q.get('provider'), q.get('source_class'), 99))
        out = {'ticker': ticker, 'provider': provider, 'provider_route': route, 'provider_priority': priority, 'source_class': source_class, 'price': price, 'timestamp': ts.isoformat().replace('+00:00', 'Z') if ts else q.get('timestamp'), 'session': session, 'adjusted': q.get('adjusted'), 'bid': q.get('bid'), 'ask': q.get('ask'), 'raw_timestamp_field': q.get('raw_timestamp_field'), 'raw_price_field_name': q.get('raw_price_field_name'), 'raw_price_field': q.get('raw_price_field'), 'source_session': q.get('source_session'), 'raw_provenance_digest': q.get('raw_provenance_digest') or stable_digest(raw), 'validity': 'REJECTED' if reason else 'VALID', 'rejection_reason': reason}
        (rejected if reason else valid).append(out)
    by = {}
    for q in valid:
        by.setdefault(q['ticker'], []).append(q)
    selected = {}
    for ticker, arr in by.items():
        arr.sort(key=lambda x: (x['provider_priority'], -parse_dt(x['timestamp']).timestamp()))
        top = arr[0]
        peers = [x for x in arr if abs((parse_dt(x['timestamp']) - parse_dt(top['timestamp'])).total_seconds()) <= 60]
        conflict = [x for x in peers if abs(x['price'] - top['price']) / max(x['price'], top['price']) > 0.005]
        if conflict:
            for x in [top] + conflict:
                x['validity'] = 'REJECTED'
                x['rejection_reason'] = 'SAME_SESSION_PROVIDER_DISAGREEMENT'
                rejected.append(x)
            valid = [x for x in valid if x not in [top] + conflict]
            selected[ticker] = {'validity': 'REJECTED', 'rejection_reason': 'SAME_SESSION_PROVIDER_DISAGREEMENT', 'selected': None}
        else:
            selected[ticker] = {'validity': 'VALID', 'rejection_reason': None, 'selected': top}
    role_selection = {}
    for ticker, arr in by.items():
        eligible = [q for q in valid if q['ticker'] == ticker]
        role_selection[ticker] = select_quotes(eligible, report_session=session, now=now) if eligible else None
    payload = {'schema_version': SCHEMA_VERSION, 'provider_priority': list(PROVIDER_PRIORITY), 'session': session, 'quotes': valid, 'rejected': rejected, 'selected_by_ticker': selected, 'role_selection': role_selection}
    return {'adapter_schema_version': SCHEMA_VERSION, 'source_timestamp': now.isoformat().replace('+00:00', 'Z'), 'freshness': 'FRESH' if valid else 'MISSING', 'validity': 'VALID' if valid else 'REJECTED', 'rejection_reason': None if valid else 'NO_VALID_PROVIDER_QUOTES', 'digest': stable_digest(payload), 'payload': payload}
__all__ = ['PROVIDER_PRIORITY', 'parse_massive_last_trade', 'parse_massive_snapshot', 'parse_massive_minute', 'parse_eodhd', 'normalize', 'stable_digest']

# Complete additive V1+V2/V3 public surface.
__all__ = sorted(n for n in globals() if not n.startswith("_"))
