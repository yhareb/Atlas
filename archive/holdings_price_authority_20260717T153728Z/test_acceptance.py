#!/usr/bin/env python3
import copy, datetime as dt, json, os, sqlite3, sys
STAGE=os.path.dirname(__file__); DB=os.path.join(STAGE,'atlas.db')
sys.path.insert(0,STAGE)
import atlas_report_authority as ra
import atlas_intraday_holdings_freshness as hf

ROW={"id":18,"ticker":"SYNA","status":"OPEN","quantity":7.90888959,"entry_price":126.44,"stop_loss":113.35,"target_price":156.61}
NOW=dt.datetime(2026,7,17,14,17,tzinfo=dt.timezone.utc)
# Freeze advisory inputs: report/state authority tests only.
hf.load_holdings_packet=lambda now,session:{"status":"STALE","freshness":"STALE","source":"fixture","positions":{}}
hf.latest_profit_snapshot=lambda:None
hf._snapshot_bars_by_ticker=lambda snapshot:({},None,None)
hf._load_profit_actions=lambda snapshot,db_path:{}

def packet_for(pa, summary=None):
 r=dict(ROW); r.update(current_price=pa.get('display_price'),price_authority=pa)
 return hf.build_packet(summary=summary or {},positions=[r],db_path=DB,report_ts=NOW)

# (a) authoritative current-session provider price: same object feeds detail/valuation/header inputs.
pa=ra.resolve_price_authority('SYNA',126.44,provider_price=115.30,provider_source='fixture',provider_timestamp='2026-07-17T14:17:00Z')
p=packet_for(pa); h=p['holdings'][0]
assert h['current_price']==h['valuation_price']==h['authoritative_price']['price']==115.30
assert round(h['pnl_pct'],6)==round((115.30-126.44)/126.44*100,6)
assert h['stop_status']=='ABOVE STOP' and h['broker_status']=='CONFIRMED'
assert 'Current gain/loss: −8.8% (−$88)' in '\n'.join(hf.render_holding_details(p))
# deterministic repeat
assert packet_for(pa)['holdings'][0]['authoritative_price']==h['authoritative_price']

# (b) provider INVALIDEVENT/missing: entry never enters current/P&L/valuation/stop.
missing=ra.resolve_price_authority('SYNA',126.44,provider_price=None,cached_price=126.44,cached_timestamp='2026-07-17T14:17:00Z')
p2=packet_for(missing); m=p2['holdings'][0]; rendered='\n'.join(hf.render_packet(p2))
assert missing['display_price'] is None
assert m['current_price'] is None and m['valuation_price'] is None and m['pnl_pct'] is None and m['pnl_usd'] is None
assert m['stop_status']=='UNKNOWN — NO ACTIONABLE PRICE' and m['final_action']=='DATA INCOMPLETE'
assert 'AUTHORITATIVE PRICE: N/A' in rendered and 'Current gain/loss: N/A (N/A)' in rendered
assert 'AUTHORITATIVE PRICE: $126.44' not in rendered

# Exact incident path: raw SELL stop row had no event timestamp, so lifecycle is INVALID_EVENT;
# it must still render N/A rather than entry.
raw={"ticker":"SYNA","action":"SELL","last":112.92,"stop":113.35,"reason":"Persisted stop hit; last 112.92 <= stop 113.35"}
p3=packet_for(missing,{"exit_results":[raw]}); x=p3['holdings'][0]
assert x['stop_event_lifecycle_state']=='INVALID_EVENT'
assert x['stop_event_lifecycle_reason']=='event timestamp invalid or missing'
assert x['current_price'] is None and x['pnl_pct'] is None

# (c) canonical broker evidence and generic pre-sale pending reconciliation.
assert ra.broker_confirmation_for_trade(DB,18)['event_id']==78
con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
before={r['ticker']:dict(r) for r in con.execute("select id,ticker,status,armed_at,expired_at from pending_pullbacks where ticker in ('PENG','ABNB','BAC')")}
# Generic rule: only actionable pending rows armed before latest confirmed sell.
stale=list(con.execute("""select p.id,p.ticker from pending_pullbacks p join
 (select ticker,max(effective_at) sold_at from portfolio_event_journal where event_type='BROKER_SELL_FILLED' group by ticker) s
 on s.ticker=p.ticker where p.status in ('WAITING','ARMED','PENDING') and datetime(p.armed_at)<datetime(s.sold_at)"""))
assert stale==[]
assert before['ABNB']['status']=='FILLED' and before['BAC']['status']=='WAITING'
# BAC was armed 11 minutes after its confirmed sell and is intentionally eligible.
assert before['BAC']['armed_at'] > con.execute("select max(effective_at) from portfolio_event_journal where ticker='BAC' and event_type='BROKER_SELL_FILLED'").fetchone()[0]
# Generic fixture proves old expires while future remains.
con.executescript("create temp table pp(id integer,ticker text,status text,armed_at text); create temp table ev(ticker text,event_type text,effective_at text);")
con.executemany('insert into pp values(?,?,?,?)',[(1,'XYZ','WAITING','2026-07-17 10:00:00'),(2,'XYZ','WAITING','2026-07-17 12:00:00')])
con.execute("insert into ev values('XYZ','BROKER_SELL_FILLED','2026-07-17 11:00:00')")
ids=[r[0] for r in con.execute("select p.id from pp p join (select ticker,max(effective_at) sold_at from ev where event_type='BROKER_SELL_FILLED' group by ticker)s on s.ticker=p.ticker where p.status in ('WAITING','ARMED','PENDING') and datetime(p.armed_at)<datetime(s.sold_at)")]
assert ids==[1]
con.close()
print(json.dumps({'tests':'PASS','valid_price':115.30,'missing_price':'N/A','invalid_event_reason':x['stop_event_lifecycle_reason'],'broker_event_id':78,'production_stale_ids':[],'BAC':'post-sale eligible'},sort_keys=True))
