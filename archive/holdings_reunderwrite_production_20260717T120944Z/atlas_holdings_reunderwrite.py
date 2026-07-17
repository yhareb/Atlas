#!/usr/bin/env python3
"""Daily Holdings Re-Underwriting v1.

Deterministic, advisory-only OPEN-holding re-underwriting. Does not modify
atlas.db, broker state, Profit Protection, raw TFE scores, entry logic, stops,
targets, sizing, or cash. Writes only to its dedicated sidecar when explicitly
asked to persist.
"""
from __future__ import annotations

import argparse, dataclasses, datetime as dt, hashlib, json, math, os, sqlite3, statistics
from pathlib import Path
from typing import Any

POLICY_VERSION = "daily_holdings_reunderwrite_v1.0.0"
ACTIONS = ("HOLD", "HOLD TIGHT", "TRIM REVIEW", "EXIT REVIEW", "SELL NOW", "DATA INCOMPLETE")
DIMENSIONS = ("trend","momentum","volume_institutional_support","relative_strength","catalyst","sector","regime","risk_reward","profit_retention","event_risk")
DEFAULT_DB = "/Users/yasser/scripts/atlas.db"
DEFAULT_SIDECAR = "/Users/yasser/Library/Application Support/Atlas/holdings_reunderwrite/holdings_reunderwrite.sqlite"
DEFAULT_PACKET = "/Users/yasser/atlas_inbox/holdings_reunderwrite_packet_v1.json"

SIDE_SCHEMA = """
CREATE TABLE IF NOT EXISTS underwriting_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL,
  created_at TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  packet_json TEXT NOT NULL,
  UNIQUE(run_date, input_digest)
);
CREATE TABLE IF NOT EXISTS underwriting_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  trade_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,
  prior_action TEXT,
  action_changed INTEGER NOT NULL,
  reason_codes_json TEXT NOT NULL,
  entry_baseline_json TEXT NOT NULL,
  current_metrics_json TEXT NOT NULL,
  thesis_comparison_json TEXT NOT NULL,
  source_timestamps_json TEXT NOT NULL,
  policy_digest TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  UNIQUE(run_id, trade_id),
  FOREIGN KEY(run_id) REFERENCES underwriting_runs(id)
);
"""

# ---- indicators ---------------------------------------------------------
def _f(x, default=None):
    try:
        if x in (None, ""): return default
        v=float(x)
        if math.isnan(v): return default
        return v
    except Exception: return default

def ema(values, period):
    vals=[_f(v) for v in values if _f(v) is not None]
    if not vals: return None
    k=2/(period+1); out=vals[0]
    for v in vals[1:]: out = v*k + out*(1-k)
    return out

def sma(values, period):
    vals=[_f(v) for v in values if _f(v) is not None]
    if len(vals)<period: return None
    return sum(vals[-period:])/period

def rsi(values, period=14):
    vals=[_f(v) for v in values if _f(v) is not None]
    if len(vals)<period+1: return None
    gains=[]; losses=[]
    for a,b in zip(vals[-period-1:-1], vals[-period:]):
        d=b-a; gains.append(max(d,0)); losses.append(abs(min(d,0)))
    avg_gain=sum(gains)/period; avg_loss=sum(losses)/period
    if avg_loss==0: return 100.0
    rs=avg_gain/avg_loss
    return 100 - 100/(1+rs)

def macd(values):
    vals=[_f(v) for v in values if _f(v) is not None]
    if len(vals)<26: return None
    return (ema(vals,12) or 0) - (ema(vals,26) or 0)

def atr14(bars):
    if len(bars)<15: return None
    trs=[]
    prev=_f(bars[0].get('close'))
    for b in bars[1:]:
        h=_f(b.get('high')); l=_f(b.get('low')); c=_f(b.get('close'))
        if None in (h,l,prev): continue
        trs.append(max(h-l, abs(h-prev), abs(l-prev)))
        prev=c if c is not None else prev
    return sum(trs[-14:])/14 if len(trs)>=14 else None

def _pct(a,b):
    a=_f(a); b=_f(b)
    if a is None or b in (None,0): return None
    return (a-b)/b*100

def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, separators=(',',':')).encode()).hexdigest()

# ---- data loaders -------------------------------------------------------
def connect_ro(db_path=DEFAULT_DB):
    conn=sqlite3.connect('file:'+str(Path(db_path).resolve())+'?mode=ro&immutable=1', uri=True)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn

def load_open_trades(db_path=DEFAULT_DB):
    conn=connect_ro(db_path)
    try: return [dict(r) for r in conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY ticker,id").fetchall()]
    finally: conn.close()

def latest_signal(conn, ticker, as_of=None):
    if as_of:
        row=conn.execute("SELECT * FROM signals WHERE ticker=? AND timestamp<=? ORDER BY timestamp DESC,id DESC LIMIT 1",(ticker,as_of)).fetchone()
    else:
        row=conn.execute("SELECT * FROM signals WHERE ticker=? ORDER BY timestamp DESC,id DESC LIMIT 1",(ticker,)).fetchone()
    return dict(row) if row else None

def load_entry_baseline(trade, conn=None):
    own=False
    if conn is None: conn=connect_ro(); own=True
    try:
        ticker=str(trade.get('ticker','')).upper()
        sig=latest_signal(conn, ticker, trade.get('entry_at')) or latest_signal(conn,ticker)
        entry=_f(trade.get('entry_price'))
        stop=_f(trade.get('stop_loss'))
        target=_f(trade.get('target_price'))
        risk=(entry-stop) if entry is not None and stop is not None else None
        risk_pct=(risk/entry*100) if entry and risk is not None else trade.get('risk_pct')
        notes=str(trade.get('notes') or '')
        return {
            'trade_id': trade.get('id'), 'ticker': ticker, 'entry_date': trade.get('entry_at'), 'entry_price': entry,
            'original_stop': stop, 'original_target': target, 'original_risk_dollars_per_share': risk, 'original_risk_pct': risk_pct,
            'original_tfe_signal': (sig or {}).get('signal'), 'original_tfe_score': (sig or {}).get('score'),
            'original_pillars': (sig or {}).get('score'), 'original_trend': (sig or {}).get('trend_stack'),
            'original_momentum': (sig or {}).get('relative_strength'), 'original_catalyst': (sig or {}).get('catalyst') or notes[:240],
            'original_catalyst_timestamp': (sig or {}).get('timestamp'), 'original_sector_regime': None,
            'original_earnings_fda_proximity': (sig or {}).get('warnings'),
            'evidence_completeness': 'PARTIAL' if not sig else 'AVAILABLE',
            'missing_entry_evidence': [] if sig else ['entry_signal_row_missing_at_or_before_entry']
        }
    finally:
        if own: conn.close()

def metrics_from_bars(trade, bars, spy_bars=None, sector_bars=None):
    closes=[_f(b.get('close')) for b in bars if _f(b.get('close')) is not None]
    highs=[_f(b.get('high')) for b in bars if _f(b.get('high')) is not None]
    lows=[_f(b.get('low')) for b in bars if _f(b.get('low')) is not None]
    vols=[_f(b.get('volume')) for b in bars if _f(b.get('volume')) is not None]
    cur=closes[-1] if closes else _f(trade.get('current_price')) or _f(trade.get('last_price')) or _f(trade.get('entry_price'))
    entry=_f(trade.get('entry_price'))
    peak=max(highs or closes or [cur])
    trough=min(lows or closes or [cur])
    peak_gain=_pct(peak, entry)
    cur_gain=_pct(cur, entry)
    giveback=((peak_gain-cur_gain)/peak_gain*100) if peak_gain and peak_gain>0 and cur_gain is not None else 0.0
    one_day=_pct(closes[-1], closes[-2]) if len(closes)>=2 else None
    largest_adverse=None
    if len(closes)>=2:
        changes=[_pct(b,a) for a,b in zip(closes[:-1],closes[1:])]
        vals=[v for v in changes if v is not None]
        largest_adverse=min(vals) if vals else None
    spy_rs=None; sector_rs=None
    if spy_bars:
        s=[_f(b.get('close')) for b in spy_bars if _f(b.get('close')) is not None]
        if len(s)>=2 and len(closes)>=2: spy_rs=_pct(closes[-1]/closes[0], s[-1]/s[0])
    if sector_bars:
        s=[_f(b.get('close')) for b in sector_bars if _f(b.get('close')) is not None]
        if len(s)>=2 and len(closes)>=2: sector_rs=_pct(closes[-1]/closes[0], s[-1]/s[0])
    avg_vol=sma(vols,20)
    rvol=(vols[-1]/avg_vol) if vols and avg_vol else None
    return {
        'completed_session_close': cur, 'intraday_high': highs[-1] if highs else cur, 'intraday_low': lows[-1] if lows else cur,
        'atr14': atr14(bars), 'ema10': ema(closes,10), 'ema21': ema(closes,21), 'ema50': ema(closes,50),
        'sma50': sma(closes,50), 'sma200': sma(closes,200), 'avg10week': sma(closes,50), 'avg40week': sma(closes,200),
        'macd': macd(closes), 'rsi': rsi(closes), 'rvol': rvol,
        'volume_trend': 'RISING' if len(vols)>=20 and (vols[-1] > (avg_vol or 0)) else 'INCOMPLETE' if not vols else 'NORMAL',
        'confirmed_swing_high': peak, 'confirmed_swing_low': trough, 'relative_strength_spy': spy_rs, 'relative_strength_sector': sector_rs,
        'distance_from_peak_pct': _pct(cur, peak), 'mfe_pct': peak_gain, 'mae_pct': _pct(trough, entry), 'giveback_pct': giveback,
        'current_gain_pct': cur_gain, 'one_day_move_pct': one_day, 'largest_adverse_day_pct': largest_adverse,
        'gap_pct': None, 'abnormal_one_day_move': bool(one_day is not None and one_day <= -8),
        'liquidity_spread_risk': 'INCOMPLETE'
    }

def fallback_metrics_from_trade(trade):
    cur=_f(trade.get('current_price')) or _f(trade.get('last_price')) or _f(trade.get('entry_price'))
    entry=_f(trade.get('entry_price'))
    target=_f(trade.get('target_price'))
    peak=max([v for v in [cur,target,entry] if v is not None] or [0])
    m=metrics_from_bars(trade, [{'close':cur,'high':peak,'low':min(cur,entry or cur),'volume':None}])
    m['data_source']='trade_cache_only'
    return m

# ---- policy -------------------------------------------------------------
def classify_dimensions(entry, metrics, ctx):
    dims={d:'INCOMPLETE' for d in DIMENSIONS}
    close=metrics.get('completed_session_close'); ema21=metrics.get('ema21'); ema50=metrics.get('ema50'); avg10=metrics.get('avg10week')
    rsi_v=metrics.get('rsi'); macd_v=metrics.get('macd'); rvol=metrics.get('rvol')
    spy_rs=metrics.get('relative_strength_spy'); sector_rs=metrics.get('relative_strength_sector')
    give=metrics.get('giveback_pct') or 0; cur_gain=metrics.get('current_gain_pct') or 0; mfe=metrics.get('mfe_pct') or 0
    if close and ema21 and ema50:
        dims['trend']='IMPROVED' if close>ema21>ema50 else 'INTACT' if close>ema50 else 'WEAKENED' if close>ema21 else 'BROKEN'
    if rsi_v is not None or macd_v is not None:
        dims['momentum']='BROKEN' if (rsi_v is not None and rsi_v<35 and (macd_v or 0)<0) else 'WEAKENED' if (rsi_v is not None and rsi_v<45) else 'IMPROVED' if (rsi_v is not None and rsi_v>60 and (macd_v or 0)>0) else 'INTACT'
    if rvol is not None:
        dims['volume_institutional_support']='BROKEN' if metrics.get('one_day_move_pct',0) is not None and metrics.get('one_day_move_pct')<=-6 and rvol>=1.5 else 'WEAKENED' if rvol>=1.5 and (metrics.get('one_day_move_pct') or 0)<0 else 'INTACT'
    if spy_rs is not None or sector_rs is not None:
        worst=min([x for x in [spy_rs,sector_rs] if x is not None])
        dims['relative_strength']='BROKEN' if worst<=-10 else 'WEAKENED' if worst<=-4 else 'IMPROVED' if worst>=4 else 'INTACT'
    catalyst=str(ctx.get('catalyst_state') or '').upper()
    dims['catalyst']='BROKEN' if catalyst in {'FAILED','INVALIDATED','NEGATIVE'} else 'WEAKENED' if catalyst in {'EXPIRED','STALE','RISK'} else 'IMPROVED' if catalyst in {'IMPROVED','POSITIVE'} else 'INTACT' if catalyst else 'INCOMPLETE'
    dims['sector']='BROKEN' if ctx.get('sector_breakdown') else 'WEAKENED' if ctx.get('sector_weak') else 'INTACT' if ctx.get('sector_known') else 'INCOMPLETE'
    dims['regime']='BROKEN' if str(ctx.get('perme_regime') or '').upper()=='RISK_OFF' else 'WEAKENED' if str(ctx.get('perme_regime') or '').upper()=='CAUTION' else 'INTACT' if ctx.get('perme_regime') else 'INCOMPLETE'
    rr=current_reward_risk(entry, metrics)
    dims['risk_reward']='BROKEN' if rr is not None and rr<0.5 else 'WEAKENED' if rr is not None and rr<1.0 else 'INTACT' if rr is not None else 'INCOMPLETE'
    dims['profit_retention']='BROKEN' if mfe>=15 and give>=65 else 'WEAKENED' if mfe>=15 and give>=35 else 'INTACT' if mfe>0 else 'INCOMPLETE'
    dims['event_risk']='BROKEN' if ctx.get('event_risk_hard') else 'WEAKENED' if ctx.get('event_risk') else 'INTACT' if ctx.get('event_checked') else 'INCOMPLETE'
    return dims

def current_reward_risk(entry, metrics):
    close=_f(metrics.get('completed_session_close')); stop=_f(entry.get('original_stop')); target=_f(entry.get('original_target'))
    if close is None or stop is None or target is None or close<=stop: return 0.0 if close is not None and stop is not None and close<=stop else None
    return max(target-close,0)/(close-stop) if (close-stop)>0 else None

def completeness(entry, metrics, ctx, dims):
    fields=['completed_session_close','atr14','ema21','ema50','avg10week','rsi','macd','rvol','relative_strength_spy','relative_strength_sector']
    have=sum(1 for f in fields if metrics.get(f) is not None)
    dim_have=sum(1 for v in dims.values() if v!='INCOMPLETE')
    entry_ok=0 if entry.get('missing_entry_evidence') else 2
    ext=sum(1 for k in ['perme_regime','quiver_posture','catalyst_state'] if ctx.get(k))
    return round((have+dim_have+entry_ok+ext)/(len(fields)+len(dims)+2+3),3)

def evaluate_holding(trade, bars=None, spy_bars=None, sector_bars=None, context=None, prior_action=None, as_of=None, macro_context_v1=None):
    context=context or {}
    if macro_context_v1 is not None:
        context=dict(context); context.update(macro_context_v1)
    conn=context.get('_conn')
    entry=load_entry_baseline(trade, conn)
    metrics=metrics_from_bars(trade, bars or [], spy_bars, sector_bars) if bars else fallback_metrics_from_trade(trade)
    dims=classify_dimensions(entry, metrics, context)
    comp=completeness(entry, metrics, context, dims)
    reasons=[]; decisive=[]; contradict=[]
    close=_f(metrics.get('completed_session_close')); stop=_f(trade.get('stop_loss')) or _f(entry.get('original_stop'))
    pp_stop=_f(context.get('profit_protection_stop'))
    risk_floor=max([x for x in [stop,pp_stop,_f(context.get('mandatory_risk_floor'))] if x is not None], default=stop)
    broken=sum(1 for v in dims.values() if v=='BROKEN'); weakened=sum(1 for v in dims.values() if v=='WEAKENED')
    non_rr_weakened=sum(1 for k,v in dims.items() if k!='risk_reward' and v=='WEAKENED')
    action='HOLD'
    core_missing = []
    if metrics.get('completed_session_close') is None: core_missing.append('completed_session_close')
    if entry.get('entry_price') is None: core_missing.append('entry_price')
    if (entry.get('original_stop') is None and trade.get('stop_loss') is None): core_missing.append('canonical_stop')
    if entry.get('original_target') is None: core_missing.append('target')
    if metrics.get('atr14') is None: core_missing.append('atr14')
    if dims.get('trend') == 'INCOMPLETE': core_missing.append('trend_state')
    if dims.get('volume_institutional_support') == 'INCOMPLETE': core_missing.append('volume_state')
    if metrics.get('mfe_pct') is None or metrics.get('giveback_pct') is None: core_missing.append('peak_giveback')
    if core_missing:
        action='DATA INCOMPLETE'; reasons.append('CORE_DATA_INCOMPLETE'); decisive.append('Missing core data: '+', '.join(core_missing))
    if action!='DATA INCOMPLETE':
        if close is not None and risk_floor is not None and close < risk_floor:
            action='SELL NOW'; reasons.append('MANDATORY_RISK_FLOOR_BREACH'); decisive.append(f'close {close:.2f} below risk floor {risk_floor:.2f}')
        elif context.get('canonical_stop_breach') or context.get('profit_protection_stop_breach'):
            action='SELL NOW'; reasons.append('VERIFIED_STOP_BREACH'); decisive.append('Verified stop breach')
        elif context.get('catastrophic_gap') or context.get('liquidity_failure'):
            action='SELL NOW'; reasons.append('CATASTROPHIC_GAP_OR_LIQUIDITY_FAILURE'); decisive.append('Catastrophic gap/liquidity failure')
        elif dims.get('catalyst')=='BROKEN' and context.get('catalyst_confirmed'):
            action='SELL NOW'; reasons.append('THESIS_BREAKING_CATALYST_CONFIRMED'); decisive.append('Confirmed thesis-breaking catalyst')
        elif dims.get('trend')=='BROKEN' and dims.get('volume_institutional_support')=='BROKEN':
            action='SELL NOW'; reasons.append('MAJOR_TREND_BREAKDOWN_WITH_VOLUME'); decisive.append('Trend breakdown confirmed by high-volume selling')
        elif broken >= 3:
            action='SELL NOW'; reasons.append('MULTIPLE_INDEPENDENT_BROKEN_DIMENSIONS'); decisive.append(f'{broken} dimensions BROKEN')
        else:
            mfe=metrics.get('mfe_pct') or 0; give=metrics.get('giveback_pct') or 0; rr=current_reward_risk(entry, metrics)
            # Explicit advisory precedence: strongest valid condition wins; later soft rules cannot downgrade it.
            if broken >= 2 and (weakened >= 1 or str(context.get('quiver_posture') or '').upper() in {'CAUTION','MIXED'} or str(context.get('perme_ticker_risk') or '').upper() in {'CAUTION','RISK'}):
                action='EXIT REVIEW'; reasons.append('TWO_BROKEN_PLUS_CONFIRMATION'); decisive.append(f'{broken} BROKEN dimensions plus confirming weakness/risk')
            elif mfe>=14.5 and give>=65:
                action='EXIT REVIEW'; reasons.append('SEVERE_PEAK_PROFIT_GIVEBACK'); decisive.append(f'giveback {give:.1f}% from {mfe:.1f}% peak gain')
            elif broken >= 2:
                action='TRIM REVIEW'; reasons.append('TWO_BROKEN_DIMENSIONS_UNCONFIRMED'); decisive.append(f'{broken} BROKEN dimensions without additional confirmation')
            elif mfe>=20 and give>=35:
                action='TRIM REVIEW'; reasons.append('PROFIT_ZONE_GIVEBACK'); decisive.append(f'profit-zone giveback {give:.1f}%')
            elif broken >= 1 or weakened>=2 or (dims.get('relative_strength')=='WEAKENED' and dims.get('trend') in {'WEAKENED','BROKEN'}):
                action='HOLD TIGHT'; reasons.append('BROKEN_OR_MULTI_WEAKENED_DIMENSIONS'); decisive.append(f'{broken} broken / {weakened} weakened dimensions')
            elif rr is not None and rr<1.0 and (non_rr_weakened>=2 or mfe>=15):
                action='TRIM REVIEW'; reasons.append('POOR_REMAINING_REWARD_RISK'); decisive.append(f'reward/risk {rr:.2f}')
            elif str(context.get('quiver_posture') or '').upper() in {'CAUTION','MIXED'} or str(context.get('perme_ticker_risk') or '').upper() in {'CAUTION','RISK'}:
                action='HOLD TIGHT'; reasons.append('EXTERNAL_REVIEW_FLAG'); decisive.append('Perme/Quiver caution requires closer monitoring')
            elif weakened>=1:
                action='HOLD TIGHT'; reasons.append('EARLY_SOFT_DETERIORATION'); decisive.append('At least one dimension weakened')
            else:
                reasons.append('THESIS_INTACT')
    # Contradicting evidence
    for d,v in dims.items():
        if v in {'IMPROVED','INTACT'}: contradict.append(f'{d}:{v}')
    if not reasons: reasons=['NO_DECISIVE_CHANGE']
    conf='HIGH' if comp>=0.80 else 'MEDIUM' if comp>=0.55 else 'LOW'
    safe_context = {k:v for k,v in context.items() if not str(k).startswith('_')}
    snap={
        'trade_id':trade.get('id'),'ticker':str(trade.get('ticker')).upper(),'as_of':as_of or dt.datetime.utcnow().isoformat()+'Z',
        'entry_baseline':entry,'current_metrics':metrics,'current_thesis':safe_context,'thesis_comparison':dims,
        'action':action,'reason_codes':reasons,'decisive_evidence':decisive,'contradicting_evidence':contradict[:8],
        'confidence':conf,'data_completeness':comp,'recheck_condition':recheck_condition(action,dims,metrics,trade),
        'prior_action':prior_action,'action_changed': bool(prior_action and prior_action!=action),
        'policy_version':POLICY_VERSION,'broker_authority':'NO','automatic_trade_closure':'NO'
    }
    snap['input_digest']=_digest({'trade':trade,'bars':bars,'spy':spy_bars,'sector':sector_bars,'context':context,'policy':POLICY_VERSION})
    return snap

def recheck_condition(action,dims,metrics,trade):
    if action=='SELL NOW': return 'Professor review immediately; advisory only, no automatic broker order.'
    if action=='EXIT REVIEW': return 'Recheck next completed session or immediately if price weakens below current risk floor.'
    if action=='TRIM REVIEW': return 'Recheck after next close; consider trim if giveback/RS deterioration persists.'
    if action=='HOLD TIGHT': return 'Recheck next completed session; escalate on EMA21/50-day loss, RS deterioration, or catalyst risk.'
    if action=='DATA INCOMPLETE': return 'Re-run after completed-session market data and external packets refresh.'
    return 'Recheck after next completed NYSE session.'

def render_position(snapshot):
    e=snapshot['entry_baseline']; m=snapshot['current_metrics']; t=snapshot['current_thesis']; ticker=snapshot['ticker']
    hm=snapshot.get('human_metrics') or {}
    entry_summary=f"Entry {e.get('entry_date')} @ {e.get('entry_price')}; original {e.get('original_tfe_signal')} score {e.get('original_tfe_score')}; catalyst: {str(e.get('original_catalyst') or 'missing')[:120]}"
    curr_summary=f"Close {m.get('completed_session_close')}; gain {fmt(hm.get('current_gain_pct', m.get('current_gain_pct')))}; peak {fmt(hm.get('peak_gain_pct', m.get('mfe_pct')))}; profit surrendered {fmt(hm.get('profit_surrendered_pct'))}; dimensions: {dimension_summary(snapshot['thesis_comparison'])}"
    what_changed=', '.join(snapshot['reason_codes'])
    return f"""{ticker}

ACTION
{snapshot['action']}

ENTRY THESIS
{entry_summary}

CURRENT THESIS
{curr_summary}

WHAT CHANGED SINCE ENTRY
{what_changed}

WHAT CHANGED SINCE YESTERDAY
{('Action changed from ' + str(snapshot.get('prior_action')) + ' to ' + snapshot['action']) if snapshot.get('action_changed') else 'No prior-day action change recorded in packet.'}

TECHNICAL STATE
Trend={snapshot['thesis_comparison'].get('trend')} Momentum={snapshot['thesis_comparison'].get('momentum')} Volume={snapshot['thesis_comparison'].get('volume_institutional_support')} RS={snapshot['thesis_comparison'].get('relative_strength')}

CATALYST / NEWS
{snapshot['thesis_comparison'].get('catalyst')} — {str(t.get('catalyst_state') or 'No fresh catalyst evidence available')}

PERME CONTEXT
{t.get('perme_display') or t.get('perme_regime') or 'PACKET_UNAVAILABLE'}

QUIVER CONTEXT
{t.get('quiver_display') or t.get('quiver_posture') or 'PACKET_UNAVAILABLE'}

SECTOR / MARKET REGIME
Sector={snapshot['thesis_comparison'].get('sector')} Regime={snapshot['thesis_comparison'].get('regime')}

PEAK GAIN
{fmt(hm.get('peak_gain_pct', m.get('mfe_pct')))}
CURRENT GAIN
{fmt(hm.get('current_gain_pct', m.get('current_gain_pct')))}
PROFIT RETAINED
{fmt(hm.get('profit_retained_pct'))}
PROFIT SURRENDERED
{fmt(hm.get('profit_surrendered_pct'))}
LOSS BELOW ENTRY
{fmt(hm.get('loss_below_entry_pct'))}
{hm.get('overrun_label') or ''}

CURRENT STOP
{trade_stop(snapshot)}
CURRENT TARGET
{e.get('original_target')}

RECOMMENDED ACTION
{snapshot['action']}

WHY NOW
{'; '.join(snapshot['decisive_evidence']) or 'No decisive deterioration.'}

RECHECK CONDITION
{snapshot['recheck_condition']}

DATA FRESHNESS
Completeness={snapshot['data_completeness']} Confidence={snapshot['confidence']}
"""

def fmt(x): return 'N/A' if x is None else f"{float(x):.1f}%"
def trade_stop(s): return s['entry_baseline'].get('original_stop')
def dimension_summary(d):
    counts={k:sum(1 for v in d.values() if v==k) for k in ['IMPROVED','INTACT','WEAKENED','BROKEN','INCOMPLETE']}
    return ', '.join(f'{k}={v}' for k,v in counts.items())

def render_daily_report(snapshots):
    groups={a:[] for a in ACTIONS}
    for s in snapshots: groups[s['action']].append(s)
    lines=['# DAILY HOLDINGS RE-UNDERWRITING','']
    for idx, action in enumerate(['SELL NOW','EXIT REVIEW','TRIM REVIEW','HOLD TIGHT','HOLD','DATA INCOMPLETE'], start=1):
        lines += [f'## {idx}. {action}']
        if groups[action]:
            for s in groups[action]:
                lines.append(f"- {s['ticker']}: {', '.join(s['reason_codes'])}; recheck: {s['recheck_condition']}")
        else:
            lines.append('- none')
        lines.append('')
    return '\n'.join(lines).rstrip()+'\n'

def packet_from_snapshots(snapshots, run_date=None):
    run_date=run_date or dt.date.today().isoformat()
    payload={'packet_version':'holdings_reunderwrite.v1','policy_version':POLICY_VERSION,'run_date':run_date,
             'created_at':dt.datetime.utcnow().replace(microsecond=0).isoformat()+'Z','positions':snapshots,
             'authority':{'broker_authority':'NO','automatic_trade_closure':'NO','trading_authority':'ADVISORY_ONLY'}}
    payload['input_digest']=_digest(snapshots)
    payload['policy_digest']=_digest({'policy':POLICY_VERSION,'actions':ACTIONS,'dimensions':DIMENSIONS})
    return payload

def open_sidecar(path=DEFAULT_SIDECAR):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(str(p)); conn.executescript(SIDE_SCHEMA); return conn

def persist_packet(packet, sidecar=DEFAULT_SIDECAR):
    conn=open_sidecar(sidecar)
    try:
        conn.execute('INSERT OR IGNORE INTO underwriting_runs(run_date,created_at,policy_version,input_digest,packet_json) VALUES(?,?,?,?,?)', (packet['run_date'],packet['created_at'],packet['policy_version'],packet['input_digest'],json.dumps(packet,sort_keys=True,default=str)))
        run_id=conn.execute('SELECT id FROM underwriting_runs WHERE run_date=? AND input_digest=?',(packet['run_date'],packet['input_digest'])).fetchone()[0]
        for s in packet['positions']:
            conn.execute('INSERT OR IGNORE INTO underwriting_snapshots(run_id,trade_id,ticker,action,prior_action,action_changed,reason_codes_json,entry_baseline_json,current_metrics_json,thesis_comparison_json,source_timestamps_json,policy_digest,snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (run_id,s['trade_id'],s['ticker'],s['action'],s.get('prior_action'),1 if s.get('action_changed') else 0,json.dumps(s['reason_codes']),json.dumps(s['entry_baseline'],sort_keys=True,default=str),json.dumps(s['current_metrics'],sort_keys=True,default=str),json.dumps(s['thesis_comparison'],sort_keys=True,default=str),json.dumps({'as_of':s.get('as_of')},sort_keys=True),packet['policy_digest'],json.dumps(s,sort_keys=True,default=str)))
        conn.commit(); return run_id
    finally: conn.close()

def build_current(db_path=DEFAULT_DB, sidecar=None, persist=False):
    conn=connect_ro(db_path); trades=[]
    try:
        trades=[dict(r) for r in conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY ticker,id").fetchall()]
        snaps=[]
        for tr in trades:
            ctx={'_conn':conn,'perme_regime':None,'quiver_posture':None,'event_checked':False,'sector_known':False,'catalyst_state':None}
            snaps.append(evaluate_holding(tr, context=ctx))
    finally: conn.close()
    pkt=packet_from_snapshots(snaps)
    if persist: persist_packet(pkt, sidecar or DEFAULT_SIDECAR)
    return pkt

def write_outputs(packet, out_dir):
    p=Path(out_dir); p.mkdir(parents=True, exist_ok=True)
    packet_path=p/'holdings_reunderwrite_packet_v1.json'; report_path=p/'DAILY_HOLDINGS_REUNDERWRITING.md'
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True, default=str)+'\n')
    report_path.write_text(render_daily_report(packet['positions'])+'\n\n'+'\n---\n'.join(render_position(s) for s in packet['positions']))
    return {'packet':str(packet_path),'report':str(report_path)}

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default=DEFAULT_DB); ap.add_argument('--sidecar',default=DEFAULT_SIDECAR); ap.add_argument('--out',default='/tmp/holdings_reunderwrite_out'); ap.add_argument('--persist',action='store_true')
    args=ap.parse_args(argv)
    pkt=build_current(args.db,args.sidecar,args.persist); print(json.dumps(write_outputs(pkt,args.out),sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
