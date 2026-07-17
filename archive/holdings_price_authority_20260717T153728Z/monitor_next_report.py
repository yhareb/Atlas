#!/usr/bin/env python3
import json,os,re,sqlite3,time,datetime
log='/Users/yasser/scripts/atlas_intraday.log'; start=os.path.getsize(log)
out='/tmp/atlas_holdings_price_authority_20260717T1138ET/next_report_evidence.json'
deadline=time.time()+900
while time.time()<deadline:
    with open(log,errors='replace') as f:
        f.seek(start); text=f.read()
    begins=[m.start() for m in re.finditer(r'\[intraday\] telegram report body begin',text)]
    ends=[m.end() for m in re.finditer(r'\[intraday\] telegram report body end',text)]
    if begins and ends and ends[-1]>begins[0]:
        body=text[begins[0]:ends[-1]]
        syna=re.search(r'1\. SYNA\n(?P<detail>.*?)(?:\n\n|\n━━━)',body,re.S)
        detail=syna.group('detail') if syna else ''
        auth=re.search(r'AUTHORITATIVE PRICE: ([^\n]+)',detail)
        current=re.search(r'Current price/session: ([^ ]+)',detail)
        header=re.search(r'^💰 .*$',body,re.M)
        result={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'complete_reports':len(begins),'body_begin_count':len(begins),'body_end_count':len(ends),'header':header.group(0) if header else None,'authoritative_price':auth.group(1) if auth else None,'current_detail_price':current.group(1) if current else None,'entry_current_fallback':('AUTHORITATIVE PRICE: $126.44' in detail),'broker_confirmed':('Broker confirmation: CONFIRMED' in detail),'BAC_actionable':bool(re.search(r'BAC .*pending entry/WAITING',body)),'traceback':('Traceback' in text),'overlap':('already running' in text.lower()),'success':('[intraday] telegram report success=True' in text),'detail':detail}
        result['consistent']=result['authoritative_price']==result['current_detail_price'] or result['authoritative_price']==result['current_detail_price']+'\n'
        open(out,'w').write(json.dumps(result,indent=2)); print(json.dumps(result)); raise SystemExit(0)
    time.sleep(5)
open(out,'w').write(json.dumps({'timeout':True,'start_offset':start})); print(json.dumps({'timeout':True})); raise SystemExit(2)
