#!/usr/bin/env python3
import os,time,re,json,datetime
p='/Users/yasser/scripts/atlas_intraday.log'; off=os.path.getsize(p); out='/tmp/atlas_holdings_price_authority_20260717T1138ET/brokerfix_report_evidence.json'
for _ in range(180):
 with open(p,errors='replace') as f:f.seek(off);s=f.read()
 if '[intraday] telegram report body end' in s:
  body=s.split('[intraday] telegram report body begin',1)[-1].split('[intraday] telegram report body end',1)[0]
  d=re.search(r'1\. SYNA\n(.*?)(?:\n\n|\n━━━)',body,re.S); d=d.group(1) if d else ''
  q=lambda pat:(re.search(pat,d).group(1) if re.search(pat,d) else None)
  r={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'price':q(r'AUTHORITATIVE PRICE: ([^\n]+)'),'detail_price':q(r'Current price/session: ([^ ]+)'),'broker':q(r'Broker confirmation: ([^\n]+)'),'entry_fallback':'AUTHORITATIVE PRICE: $126.44' in d,'begin':s.count('telegram report body begin'),'end':s.count('telegram report body end'),'traceback':'Traceback' in s,'overlap':'already running' in s.lower(),'success':'telegram report success=True' in s,'detail':d}
  open(out,'w').write(json.dumps(r,indent=2));print(json.dumps(r));raise SystemExit(0)
 time.sleep(5)
raise SystemExit(2)
