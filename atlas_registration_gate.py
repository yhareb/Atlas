"""ORDER #38 deterministic broker registration gate (staging release unit)."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib, json

REQUIRED=("broker","broker_ref","side","ticker","quantity_text","price_text","fees_text","currency","execution_at","source_sha256","parser_version")
DIRECT=("broker","side","ticker","currency","execution_at")

@dataclass(frozen=True)
class BrokerParseV2:
    source_sha256:str; source_path:str; artifact_dir:str; parser_version:str
    broker:str; side:str; broker_ref:str; execution_at:str; currency:str; ticker:str
    quantity_text:str; price_text:str; fees_text:str
    parse_confidence:float; field_confidence:dict; raw_field_provenance:dict
    trade_id:int|None=None; lot_id:int|None=None; stage:str|None=None; instruction_digest:str|None=None
    entry_plan:dict|None=None; display:dict|None=None
    def canonical(self):
        d=asdict(self); d["broker"]=self.broker.upper(); d["side"]=self.side.upper(); d["ticker"]=self.ticker.upper(); d["currency"]=self.currency.upper()
        for k in ("quantity_text","price_text","fees_text"): d[k]=canonical_decimal(d[k])
        return d

def canonical_decimal(v):
    d=Decimal(str(v));
    if not d.is_finite(): raise InvalidOperation
    return format(d.normalize(),'f') if d else '0'

def packet_digest(packet):
    d=packet.canonical() if isinstance(packet,BrokerParseV2) else packet
    return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def deterministic_gate(packet:BrokerParseV2, evidence:dict, *, duplicate=None, open_context=None, wio_retired=False):
    """Pure fail-closed gate. Provider/ticker/quote/OHLC evidence is injected and sealed."""
    p=packet.canonical(); failures=[]
    for k in REQUIRED:
        if p.get(k) in (None,''): failures.append(f"REG_GATE_REQUIRED_FIELDS:{k}")
    if len(str(p.get('source_sha256',''))) != 64: failures.append('REG_GATE_REQUIRED_FIELDS:source_sha256')
    try:
        ts=datetime.fromisoformat(p['execution_at'].replace('Z','+00:00'))
        if ts.tzinfo is None: raise ValueError
    except Exception: failures.append('REG_GATE_REQUIRED_FIELDS:execution_at')
    broker=p.get('broker')
    if broker!='ETORO':
        allowed=(broker=='WIO_LEGACY' and p.get('ticker')=='SYNA' and not wio_retired and evidence.get('wio_open_syna') is True)
        if not allowed: failures.append('REG_GATE_BROKER_UNSUPPORTED')
    if p.get('currency')!='USD': failures.append('REG_GATE_CURRENCY_UNSUPPORTED')
    for k in REQUIRED:
        if packet.field_confidence.get(k) is None: failures.append(f'REG_GATE_CONFIDENCE_MISSING:{k}')
        elif Decimal(str(packet.field_confidence[k])) < Decimal('.95'): failures.append(f'REG_GATE_CONFIDENCE_LOW:{k}')
        if not packet.raw_field_provenance.get(k): failures.append(f'REG_GATE_PROVENANCE_MISSING:{k}')
    for k in DIRECT:
        prov=packet.raw_field_provenance.get(k) or {}
        if not isinstance(prov,dict) or not prov.get('region'): failures.append(f'REG_GATE_VISUAL_PROVENANCE:{k}')
    if Decimal(str(packet.parse_confidence)) < Decimal('.95'): failures.append('REG_GATE_PARSE_CONFIDENCE')
    try:
        if Decimal(str(packet.parse_confidence)) != min(Decimal(str(packet.field_confidence[k])) for k in REQUIRED):
            failures.append('REG_GATE_PARSE_CONFIDENCE_NOT_MINIMUM')
    except Exception: failures.append('REG_GATE_PARSE_CONFIDENCE_NOT_MINIMUM')
    if evidence.get('conflicting_fields'): failures.append('REG_GATE_CONFLICTING_OCCURRENCES')
    try:
        qty,price,fees=Decimal(p['quantity_text']),Decimal(p['price_text']),Decimal(p['fees_text'])
        if qty<=0 or price<=0 or fees<0: failures.append('REG_GATE_DECIMAL_NONPOSITIVE')
        if max(0,-qty.as_tuple().exponent)>8: failures.append('REG_GATE_QUANTITY_SCALE')
        if max(0,-price.as_tuple().exponent)>6: failures.append('REG_GATE_PRICE_SCALE')
        if max(0,-fees.as_tuple().exponent)>2: failures.append('REG_GATE_FEES_SCALE')
    except Exception: failures.append('REG_GATE_DECIMAL_INVALID'); qty=price=fees=Decimal(0)
    if evidence.get('ticker_active') is not True or evidence.get('corporate_action_ok') is not True: failures.append('REG_GATE_TICKER_EVIDENCE')
    mode=evidence.get('price_mode')
    if mode=='LIVE':
        try:
            q=Decimal(str(evidence['selected_quote']));
            if q<=0 or abs(price-q)/q>Decimal('.10'): failures.append('REG_GATE_PRICE_LIVE_10PCT')
        except Exception: failures.append('REG_GATE_PRICE_EVIDENCE')
    elif mode=='HISTORICAL':
        try:
            lo,hi=Decimal(str(evidence['adjusted_low'])),Decimal(str(evidence['adjusted_high']))
            if evidence.get('ohlc_authoritative') is not True or price<lo*Decimal('.98') or price>hi*Decimal('1.02'): failures.append('REG_GATE_PRICE_HISTORICAL_2PCT')
        except Exception: failures.append('REG_GATE_PRICE_EVIDENCE')
    else: failures.append('REG_GATE_PRICE_EVIDENCE')
    if evidence.get('older_than_one_nyse_session'): failures.append('REG_GATE_EXECUTION_TOO_OLD')
    if duplicate:
        failures.append('IDEMPOTENT_ALREADY_REGISTERED' if duplicate.get('identical') else 'REG_GATE_DUPLICATE_CONFLICT')
    ctx=open_context or {}
    if p.get('side')=='BUY':
        ep=packet.entry_plan or {}
        if not ep.get('unique') or any(ep.get(x) in (None,'') for x in ('stop_loss','target_price','entry_atr14')): failures.append('REG_GATE_ENTRY_PLAN')
    elif p.get('side')=='SELL':
        if ctx.get('exact_trade_count')!=1 or ctx.get('exact_lot_count')!=1: failures.append('REG_GATE_LOT_AMBIGUOUS')
        try:
            if qty>Decimal(str(ctx['open_quantity'])): failures.append('REG_GATE_OVERFILL')
        except Exception: failures.append('REG_GATE_LOT_AMBIGUOUS')
        # Every SELL, including a full/runner close, must be bound to exactly
        # one persisted projection/instruction.  Quantity equality alone is
        # not authority to liquidate an OPEN lot.
        matches=ctx.get('instruction_matches') or []
        if (len(matches)!=1 or Decimal(str(matches[0].get('quantity','0'))) != qty
                or matches[0].get('digest')!=packet.instruction_digest
                or matches[0].get('stage')!=packet.stage):
            failures.append('REG_GATE_STAGE_INSTRUCTION')
        if qty==Decimal(str(ctx.get('open_quantity','0'))) and packet.stage not in ('FULL','RUNNER'):
            failures.append('REG_GATE_STAGE_INSTRUCTION')
    else: failures.append('REG_GATE_REQUIRED_FIELDS:side')
    status='IDEMPOTENT_ALREADY_REGISTERED' if failures==['IDEMPOTENT_ALREADY_REGISTERED'] else ('PASS' if not failures else 'FAIL')
    return {'schema':'RegistrationGateReceiptV1','status':status,'failure_codes':sorted(set(failures)),'packet_digest':packet_digest(packet),'market_evidence':evidence}

def duplicate_projection(conn, packet):
    row=conn.execute("SELECT ticker,quantity_text,price_text,fees_text,currency,execution_at FROM broker_registrations WHERE source_sha256=? AND broker=? AND broker_ref=? AND side=?",(packet.source_sha256,packet.broker.upper(),packet.broker_ref,packet.side.upper())).fetchone()
    if not row:return None
    want=(packet.ticker.upper(),canonical_decimal(packet.quantity_text),canonical_decimal(packet.price_text),canonical_decimal(packet.fees_text),packet.currency.upper(),packet.execution_at)
    got=(row[0],canonical_decimal(row[1]),canonical_decimal(row[2]),canonical_decimal(row[3]),row[4],row[5])
    return {'identical':got==want,'committed':got,'incoming':want}
__all__=['BrokerParseV2','deterministic_gate','duplicate_projection','canonical_decimal','packet_digest']
