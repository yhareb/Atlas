"""Typed, section-level canonical integration contracts.

Adapters replace only a classified holding section and preserve the enclosing
report's concrete return type and all non-holding members/bytes.
"""
from __future__ import annotations
from dataclasses import dataclass, is_dataclass, replace
from typing import Any, Mapping, Sequence
from atlas_holding_state_adapters_schema import SectionProjection
from atlas_holding_state_schema import thaw

START='[[ATLAS_HOLDINGS_START]]'
END='[[ATLAS_HOLDINGS_END]]'
UNAVAILABLE='CANONICAL HOLDING AUTHORITY UNAVAILABLE'

# V3 construction-site contracts are explicit. There is deliberately no heading
# classifier, natural-span inference, regex replacement, or whole-report surgery.
SITE_MARKERS={
    'PRE_MARKET_HOLDINGS':(START,END),
    'INTRADAY_HOLDINGS':(START,END),
    'EOD_POSTMARKET_HOLDINGS':(START,END),
    'CONVERSATION_HOLDINGS':(START,END),
    'BROKER_PENDING_VISIBILITY':(START,END),
    'DAILY_PP_HOLDING_SECTIONS':(START,END),
}

@dataclass(frozen=True)
class TextSectionContract:
    start_marker: str=START
    end_marker: str=END

@dataclass(frozen=True)
class LinesSectionContract:
    start_marker: str=START
    end_marker: str=END

@dataclass(frozen=True)
class MappingSectionContract:
    field: str='holding_state'

def render_section(unit:str,packet:Mapping[str,Any],receipt:Mapping[str,Any])->SectionProjection:
    state=receipt['usability']; reasons=tuple(sorted(receipt.get('reason_codes') or ()))
    ticker=packet.get('ticker') or packet.get('trade_id') or '?'
    if state=='BLOCKED': lines=(f"{UNAVAILABLE} — {', '.join(reasons)}",)
    elif state=='DATA_INCOMPLETE':
        unavailable=tuple(f"{role}: UNAVAILABLE — {', '.join(reasons)}" for role,ok in sorted((receipt.get('price_role_usability') or {}).items()) if not ok)
        lines=(f'{ticker} — DATA INCOMPLETE',)+unavailable
    else:
        axes=packet.get('axes') or {}; levels=packet.get('canonical_levels') or {}
        lines=(f'{ticker} — CANONICAL HOLDING STATE',
               f"Observed: {(axes.get('observed_market_risk_state') or {}).get('state')}",
               f"Advisory: {(axes.get('advisory_action') or {}).get('action')}",
               f"Broker: {(axes.get('broker_ledger_lifecycle') or {}).get('state')}",
               f"Stop: {levels.get('stop')} | Target: {levels.get('target')}")
    return SectionProjection(unit,lines,{'packet':thaw(packet),'receipt':thaw(receipt)},state,packet.get('packet_id'))

def _explicit_text_site(report:str,contract:TextSectionContract)->tuple[int,int]:
    if report.count(contract.start_marker)!=1 or report.count(contract.end_marker)!=1:
        raise ValueError('EXPLICIT_CONSTRUCTION_SITE_REQUIRED')
    start=report.index(contract.start_marker)+len(contract.start_marker)
    end=report.index(contract.end_marker,start)
    return start,end

def splice_text_section(report:str,projection:SectionProjection,contract:TextSectionContract=TextSectionContract())->str:
    start,end=_explicit_text_site(report,contract)
    return report[:start]+'\n'+'\n'.join(projection.lines)+'\n'+report[end:]

def splice_lines_section(report:Sequence[str],projection:SectionProjection,contract:LinesSectionContract=LinesSectionContract()):
    original_type=type(report); values=list(report)
    if values.count(contract.start_marker)!=1 or values.count(contract.end_marker)!=1:
        raise ValueError('EXPLICIT_CONSTRUCTION_SITE_REQUIRED')
    start=values.index(contract.start_marker)+1; end=values.index(contract.end_marker,start)
    result=values[:start]+list(projection.lines)+values[end:]
    return tuple(result) if original_type is tuple else result

def splice_mapping_section(report:Mapping[str,Any],projection:SectionProjection,contract:MappingSectionContract=MappingSectionContract()):
    if contract.field not in report: raise ValueError('EXPLICIT_CONSTRUCTION_SITE_REQUIRED')
    result=dict(report); result[contract.field]=projection.structured
    if type(report) is dict:return result
    try:return type(report)(result)
    except TypeError:return result

def splice_dataclass_section(report:Any,projection:SectionProjection,field:str='holding_state'):
    if not is_dataclass(report) or not hasattr(report,field):
        raise ValueError('EXPLICIT_CONSTRUCTION_SITE_REQUIRED')
    return replace(report,**{field:projection.structured})

def splice_route_result(report:Any,projection:SectionProjection):
    """Preserve the concrete RouteResult with dataclasses.replace/constructor."""
    if not is_dataclass(report) or type(report).__name__!='RouteResult':
        raise TypeError('ROUTE_RESULT_REQUIRED')
    rendered='\n'.join(projection.lines)
    fields=getattr(report,'__dataclass_fields__',{})
    updates={}
    if 'rendered_answer' in fields: updates['rendered_answer']=rendered
    if 'structured_answer' in fields: updates['structured_answer']=projection.structured
    if not updates: raise ValueError('ROUTE_RESULT_CONSTRUCTION_SITE_MISSING')
    return replace(report,**updates)

def integrate_text_report(report:str,projection:SectionProjection)->str:
    if not isinstance(report,str):raise TypeError('TEXT_REPORT_REQUIRED')
    return splice_text_section(report,projection)

def integrate_lines_report(report:Sequence[str],projection:SectionProjection):
    if isinstance(report,(str,bytes)) or not isinstance(report,(list,tuple)):raise TypeError('LINES_REPORT_REQUIRED')
    return splice_lines_section(report,projection)

def integrate_mapping_report(report:Mapping[str,Any],projection:SectionProjection):
    if not isinstance(report,Mapping):raise TypeError('MAPPING_REPORT_REQUIRED')
    return splice_mapping_section(report,projection)

# Backward-compatible marker-only name; generic return adaptation is intentionally absent.
splice_holding_section=splice_text_section

# Explicit consumer contracts used at each holding-bearing parent.
PRE_MARKET_TEXT=integrate_text_report
INTRADAY_TEXT=integrate_text_report
EOD_TEXT=integrate_text_report
CONVERSATION_MAPPING=integrate_mapping_report
BROKER_LINES=integrate_lines_report
DAILY_PP_TEXT=integrate_text_report
DAILY_PP_LINES=integrate_lines_report
DAILY_PP_MAPPING=integrate_mapping_report
BROKER_MAPPING=integrate_mapping_report
def DAILY_PP_STATUS(value,projection):return value
def CONVERSATION_TYPED(value,projection):
    if type(value).__name__=='RouteResult': return splice_route_result(value,projection)
    if isinstance(value,Mapping): return splice_mapping_section(value,projection)
    raise TypeError('CONVERSATION_CONCRETE_TYPE_REQUIRED')
def DAILY_PP_TYPED(value,projection):
    if isinstance(value,str):return integrate_text_report(value,projection)
    if isinstance(value,(list,tuple)):return integrate_lines_report(value,projection)
    if isinstance(value,Mapping):return integrate_mapping_report(value,projection)
    return value
def EOD_TYPED(value,projection):return integrate_text_report(value,projection)
def PRE_MARKET_TYPED(value,projection):return integrate_text_report(value,projection)
def INTRADAY_TYPED(value,projection):return integrate_text_report(value,projection)
def BROKER_TYPED(value,projection):return integrate_lines_report(value,projection)
AVAILABLE_ADAPTERS={k:v for k,v in globals().copy().items() if k.endswith('_TYPED') or k.endswith('_TEXT') or k.endswith('_LINES') or k.endswith('_MAPPING') or k.endswith('_STATUS')}

def adapter(name:str):
    try:return AVAILABLE_ADAPTERS[name]
    except KeyError:raise ValueError('UNKNOWN_TYPED_SECTION_ADAPTER:'+name)

# ---- V1 PLATFORM BASELINE COMPATIBILITY (additive; V2/V3 bindings win) ----
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Iterable
import hashlib, json, sqlite3, shutil, calendar
from atlas_holding_state_authority import parse_dt, iso, sha_json, stable_json, normalize_action, normalize_reason_codes, select_quotes, reconstruct_from_ledger
from atlas_holding_state_adapters_schema import ADAPTER_SCHEMA_VERSION, AdapterRecord, validate_adapter_record
ADAPTER_VERSION = 'phase3_adapters.v1'
DAILY_TTL_HOURS = 36
PP_TTL_HOURS = 36

def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _record(name: str, source_type: str, payload: dict[str, Any], *, source_path: str | None=None, source_timestamp: Any=None, freshness: str='FRESH', validity: str='VALID', rejection_reason: str | None=None) -> dict[str, Any]:
    ts = parse_dt(source_timestamp)
    rec = AdapterRecord(ADAPTER_SCHEMA_VERSION, name, source_type, source_path, iso(ts) if ts else str(source_timestamp) if source_timestamp else None, freshness, _digest({'adapter': name, 'payload': payload, 'source_timestamp': str(source_timestamp), 'version': ADAPTER_VERSION}), validity, rejection_reason, payload).to_dict()
    ok, errors = validate_adapter_record(rec)
    if not ok:
        raise ValueError('ADAPTER_RECORD_INVALID:' + ','.join(errors))
    return rec

def _connect_ro(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect('file:' + str(Path(db_path).resolve()) + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con

def adapt_db_open_positions(db_path: str | Path) -> dict[str, Any]:
    con = _connect_ro(db_path)
    try:
        rows = []
        for r in con.execute("SELECT id,ticker,status,quantity,entry_price,entry_at,stop_loss,target_price,broker_ref,manual_stop_lock,current_price,last_price,last_price_at,updated_at FROM trades WHERE status='OPEN' ORDER BY id"):
            d = dict(r)
            valid = bool(d.get('ticker') and d.get('id') is not None and (d.get('entry_price') is not None))
            rows.append({'trade_id': d.get('id'), 'lot_id': None, 'ticker': str(d.get('ticker') or '').upper(), 'status': d.get('status'), 'quantity': d.get('quantity'), 'entry_price': d.get('entry_price'), 'entry_at': d.get('entry_at'), 'canonical_stop': d.get('stop_loss'), 'canonical_target': d.get('target_price'), 'broker_ref_present': bool(d.get('broker_ref')), 'manual_stop_lock': bool(d.get('manual_stop_lock')), 'cache_price': d.get('current_price') or d.get('last_price'), 'cache_timestamp': d.get('last_price_at'), 'source_updated_at': d.get('updated_at'), 'validity': 'VALID' if valid else 'INVALID', 'rejection_reason': None if valid else 'MISSING_TRADE_ID_TICKER_OR_ENTRY'})
        payload = {'positions': rows, 'count': len(rows)}
        max_ts = max([x.get('source_updated_at') or '' for x in rows], default=None)
        return _record('db_open_positions', 'atlas.db.trades', payload, source_path=str(db_path), source_timestamp=max_ts, validity='VALID')
    finally:
        con.close()

def adapt_provider_quote_candidates(raw_quotes: list[dict[str, Any]], *, report_session: str, now: datetime, reference_prices: dict[str, float] | None=None, expected_adjusted: bool | None=True) -> dict[str, Any]:
    reference_prices = reference_prices or {}
    normalized = []
    rejected = []
    for q in raw_quotes or []:
        item = dict(q)
        ticker = str(item.get('ticker') or '').upper()
        reason = None
        try:
            price = float(item.get('price'))
        except Exception:
            price = None
        if not ticker:
            reason = 'TICKER_MISSING'
        elif price is None or price <= 0:
            reason = 'PRICE_INVALID'
        elif expected_adjusted is not None and item.get('adjusted') is not None and (bool(item.get('adjusted')) != bool(expected_adjusted)):
            reason = 'CORPORATE_ACTION_ADJUSTMENT_MISMATCH'
        elif item.get('split_factor') not in (None, '', 1, 1.0, '1', '1.0'):
            reason = 'CORPORATE_ACTION_SPLIT_FACTOR_UNNORMALIZED'
        else:
            ref = reference_prices.get(ticker)
            if ref and abs(price - ref) / max(price, ref) > 0.5:
                reason = 'SANITY_BAND_REJECTED'
        cand = {'ticker': ticker, 'price': price, 'timestamp': item.get('timestamp'), 'session': str(item.get('session') or report_session).upper(), 'source_class': str(item.get('source_class') or item.get('source') or 'PROVIDER_SNAPSHOT').upper(), 'provider': item.get('provider'), 'bid': item.get('bid'), 'ask': item.get('ask'), 'adjusted': item.get('adjusted'), 'split_factor': item.get('split_factor')}
        if reason:
            cand.update({'validity': 'REJECTED', 'rejection_reason': reason})
            rejected.append(cand)
        else:
            cand.update({'validity': 'VALID', 'rejection_reason': None})
            normalized.append(cand)
    selected_by_ticker = {}
    for ticker in sorted({x['ticker'] for x in normalized if x.get('ticker')}):
        selected_by_ticker[ticker] = select_quotes([x for x in normalized if x['ticker'] == ticker], report_session=report_session, now=now)
    payload = {'quotes': normalized, 'rejected': rejected, 'selected_by_ticker': selected_by_ticker, 'report_session': report_session}
    validity = 'VALID' if normalized else 'REJECTED'
    reason = None if normalized else 'NO_VALID_QUOTES'
    max_ts = max([str(x.get('timestamp') or '') for x in normalized], default=None)
    return _record('provider_quotes', 'provider_quote_candidates', payload, source_timestamp=max_ts, freshness='FRESH' if normalized else 'MISSING', validity=validity, rejection_reason=reason)

def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row.get('payload_json') or '{}')
    except Exception:
        return {'_payload_error': 'JSON_INVALID'}

def adapt_portfolio_event_journal(db_path: str | Path, open_positions: Iterable[dict[str, Any]] | None=None, *, now: datetime | None=None) -> dict[str, Any]:
    now = now or _now()
    open_by_trade = {int(p.get('trade_id')): p for p in open_positions or [] if p.get('trade_id') is not None}
    open_tickers = {str(p.get('ticker')).upper() for p in open_positions or []}
    con = _connect_ro(db_path)
    events = []
    try:
        for r in con.execute('SELECT * FROM portfolio_event_journal ORDER BY id'):
            row = dict(r)
            pay = _payload(row)
            et = str(row.get('event_type') or '').upper()
            trade_id = row.get('legacy_trades_id') or pay.get('trade_id')
            ticker = str(row.get('ticker') or pay.get('ticker') or '').upper()
            validity = 'VALID'
            reason = None
            state = 'EVENT_RECORDED'
            ts = row.get('effective_at') or row.get('occurred_at')
            if et in {'BROKER_SELL_SUBMITTED', 'BROKER_SELL_FILLED', 'BROKER_CANCELLED', 'CASH_CREDIT_POSTED', 'RECONCILIATION_EXCEPTION', 'MANUAL_CORRECTION', 'STOP_HIT_DETECTED', 'STOP_CHANGE'}:
                pass
            else:
                validity = 'REJECTED'
                reason = 'EVENT_TYPE_NOT_RELEVANT_TO_HOLDING_STATE'
            if trade_id and open_by_trade and (int(trade_id) not in open_by_trade) and (et in {'STOP_HIT_DETECTED', 'BROKER_SELL_SUBMITTED'}):
                validity = 'REJECTED'
                reason = 'WRONG_OR_CLOSED_TRADE_ID'
            if ticker and open_tickers and (ticker not in open_tickers) and (et in {'STOP_HIT_DETECTED', 'BROKER_SELL_SUBMITTED'}) and (reason is None):
                validity = 'REJECTED'
                reason = 'WRONG_TICKER_OR_NOT_OPEN'
            if et == 'STOP_HIT_DETECTED':
                state = 'STOP_EVENT'
            elif et == 'BROKER_SELL_SUBMITTED':
                state = 'BROKER_SELL_SUBMITTED'
            elif et == 'BROKER_SELL_FILLED':
                state = 'BROKER_SELL_FILLED'
            elif et == 'BROKER_CANCELLED':
                state = 'BROKER_CANCELLED'
            elif et == 'MANUAL_CORRECTION':
                state = 'MANUAL_CORRECTION'
            elif et == 'RECONCILIATION_EXCEPTION':
                state = 'RECONCILIATION_EXCEPTION'
            if row.get('supersedes_id') or row.get('linked_reversal_id'):
                state = 'SOURCE_SUPERSEDED'
                validity = 'REJECTED'
                reason = 'EVENT_SUPERSEDED_OR_REVERSED'
            events.append({'event_id': row.get('id'), 'event_type': et, 'ticker': ticker, 'trade_id': trade_id, 'lot_id': row.get('lot_id'), 'source_timestamp': ts, 'recorded_at': row.get('recorded_at'), 'source': row.get('source'), 'payload': pay, 'normalized_state': state, 'validity': validity, 'rejection_reason': reason, 'digest': _digest(row)})
        for e in events:
            if e['event_type'] == 'STOP_HIT_DETECTED' and e['validity'] == 'VALID':
                ets = parse_dt(e['source_timestamp'])
                for later in events:
                    if later is e:
                        continue
                    if later['event_type'] in {'MANUAL_CORRECTION', 'STOP_CHANGE'} and (later.get('trade_id') == e.get('trade_id') or later.get('ticker') == e.get('ticker')):
                        lts = parse_dt(later.get('source_timestamp'))
                        if ets and lts and (lts > ets):
                            e['validity'] = 'REJECTED'
                            e['rejection_reason'] = 'SUPERSEDED_BY_STOP_CHANGE_OR_MANUAL_CORRECTION'
                            e['normalized_state'] = 'SOURCE_SUPERSEDED'
        payload = {'events': events, 'count': len(events)}
        max_ts = max([str(e.get('source_timestamp') or '') for e in events], default=None)
        return _record('portfolio_event_journal', 'atlas.db.portfolio_event_journal', payload, source_path=str(db_path), source_timestamp=max_ts, validity='VALID')
    finally:
        con.close()

def adapt_daily_reunderwrite_packet(path: str | Path, *, now: datetime, expected_session: str | None=None) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _record('daily_reunderwrite_packet', 'holdings_reunderwrite_packet', {}, source_path=str(p), freshness='MISSING', validity='MISSING', rejection_reason='PACKET_MISSING')
    try:
        pkt = json.loads(p.read_text())
    except Exception:
        return _record('daily_reunderwrite_packet', 'holdings_reunderwrite_packet', {}, source_path=str(p), freshness='INVALID', validity='INVALID', rejection_reason='JSON_INVALID')
    created = parse_dt(pkt.get('created_at') or pkt.get('generated_at'))
    errors = []
    if pkt.get('packet_version') != 'holdings_reunderwrite.v1':
        errors.append('SCHEMA_INVALID')
    if not isinstance(pkt.get('positions'), list):
        errors.append('POSITIONS_MISSING')
    if expected_session and pkt.get('run_date') != expected_session:
        errors.append('SESSION_MISMATCH')
    if not (pkt.get('packet_digest') or pkt.get('input_digest')):
        errors.append('DIGEST_MISSING')
    stale = not created or (now.astimezone(timezone.utc) - created).total_seconds() > DAILY_TTL_HOURS * 3600
    if stale:
        errors.append('PACKET_STALE')
    positions = []
    for pos in pkt.get('positions') or []:
        positions.append({'ticker': str(pos.get('ticker') or '').upper(), 'trade_id': pos.get('trade_id'), 'action': normalize_action(pos.get('action')), 'reason_codes': normalize_reason_codes(pos.get('reason_codes') or ()), 'source_timestamp': pos.get('as_of') or pkt.get('created_at'), 'digest': _digest(pos), 'validity': 'VALID' if pos.get('ticker') else 'INVALID', 'rejection_reason': None if pos.get('ticker') else 'TICKER_MISSING'})
    payload = {'run_date': pkt.get('run_date'), 'packet_digest': pkt.get('packet_digest') or pkt.get('input_digest'), 'positions': positions, 'raw_count': len(pkt.get('positions') or [])}
    return _record('daily_reunderwrite_packet', 'holdings_reunderwrite_packet', payload, source_path=str(p), source_timestamp=pkt.get('created_at') or pkt.get('generated_at'), freshness='STALE' if stale else 'FRESH', validity='REJECTED' if errors else 'VALID', rejection_reason=';'.join(errors) if errors else None)

def adapt_profit_protection_packet(path: str | Path, *, now: datetime) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _record('profit_protection_packet', 'profit_protection_packet', {}, source_path=str(p), freshness='MISSING', validity='MISSING', rejection_reason='PACKET_MISSING')
    try:
        obj = json.loads(p.read_text())
    except Exception:
        return _record('profit_protection_packet', 'profit_protection_packet', {}, source_path=str(p), freshness='INVALID', validity='INVALID', rejection_reason='JSON_INVALID')
    captured = obj.get('captured_at') or obj.get('generated_at') or obj.get('created_at')
    cdt = parse_dt(captured)
    stale = not cdt or (now.astimezone(timezone.utc) - cdt).total_seconds() > PP_TTL_HOURS * 3600
    results = obj.get('results') or obj.get('positions') or obj.get('by_ticker') or []
    if isinstance(results, dict):
        iterable = results.values()
    else:
        iterable = results
    positions = []
    for r in iterable or []:
        if not isinstance(r, dict):
            continue
        positions.append({'ticker': str(r.get('ticker') or '').upper(), 'trade_id': r.get('trade_id'), 'action': normalize_action(r.get('action') or r.get('profit_protection_action') or r.get('recommended_action')), 'raw_action': r.get('action'), 'reason_codes': normalize_reason_codes(r.get('reason_codes') or [r.get('action')]), 'source_timestamp': r.get('provider_timestamp') or captured, 'digest': _digest(r), 'validity': 'VALID' if r.get('ticker') else 'INVALID', 'rejection_reason': None if r.get('ticker') else 'TICKER_MISSING'})
    errors = []
    if not positions:
        errors.append('NO_RESULTS')
    if stale:
        errors.append('PACKET_STALE')
    payload = {'captured_at': captured, 'positions': positions, 'count': len(positions), 'packet_digest': obj.get('packet_digest') or obj.get('snapshot_sha256') or _digest(obj)}
    return _record('profit_protection_packet', 'profit_protection_packet', payload, source_path=str(p), source_timestamp=captured, freshness='STALE' if stale else 'FRESH', validity='REJECTED' if errors else 'VALID', rejection_reason=';'.join(errors) if errors else None)

def adapt_prior_canonical_ledger(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _record('prior_canonical_ledger', 'holding_state_action_ledger', {}, source_path=str(p), freshness='MISSING', validity='MISSING', rejection_reason='LEDGER_MISSING')
    try:
        rec = reconstruct_from_ledger(p)
    except Exception as e:
        return _record('prior_canonical_ledger', 'holding_state_action_ledger', {}, source_path=str(p), freshness='INVALID', validity='INVALID', rejection_reason='LEDGER_RECONSTRUCTION_FAILED:' + type(e).__name__)
    return _record('prior_canonical_ledger', 'holding_state_action_ledger', rec, source_path=str(p), source_timestamp=None, validity='VALID')
NYSE_HOLIDAYS_2026 = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}

def is_nyse_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS_2026

def latest_completed_nyse_session(now: datetime) -> str:
    et = now.astimezone(timezone.utc) - timedelta(hours=4)
    d = et.date()
    if et.time() <= datetime(2000, 1, 1, 20, 0).time():
        d -= timedelta(days=1)
    while not is_nyse_trading_day(d):
        d -= timedelta(days=1)
    return d.isoformat()

def retention_expiry_completed_session(reason_codes: Iterable[str], since: datetime, sessions: int=2) -> str:
    d = (since.astimezone(timezone.utc) - timedelta(hours=4)).date()
    count = 0
    while count < sessions:
        d += timedelta(days=1)
        if is_nyse_trading_day(d):
            count += 1
    return iso(datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc))

def adapt_nyse_calendar(now: datetime) -> dict[str, Any]:
    payload = {'now': iso(now), 'latest_completed_session': latest_completed_nyse_session(now), 'is_today_trading_day': is_nyse_trading_day((now - timedelta(hours=4)).date()), 'calendar': 'NYSE_STATIC_2026_FIXTURE'}
    return _record('nyse_calendar', 'nyse_calendar_rules', payload, source_timestamp=iso(now), validity='VALID')
