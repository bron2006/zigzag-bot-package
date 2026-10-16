"""Bounded read-only quote/fee proxy sampler. No account/order/DB endpoints."""
import base64
import json
import math
from pathlib import Path
import shutil
import subprocess
import numpy as np

HERE=Path(__file__).resolve().parent


def estimate(spec,quote,now,units=1000.):
    if spec.get('commissionType')!='USD_PER_MILLION_USD' or spec.get('minCommissionAsset')!='USD':
        raise ValueError('Unsupported commission basis')
    bid,ask,bt,at=[float(quote[k]) for k in ('bid','ask','bid_ts','ask_ts')]
    if not all(math.isfinite(x) for x in (bid,ask,bt,at,now,units)) or not 0<bid<=ask or units<=0:
        raise ValueError('Invalid quote/units')
    if not all(0<=now-t<=5 for t in (bt,at)) or abs(bt-at)>1:
        raise ValueError('Stale or asynchronous quote sides')
    rate=float(spec['preciseTradingCommissionRate'])/1e8
    minimum=float(spec['preciseMinCommission'])/1e8
    if min(rate,minimum)<0:raise ValueError('Negative commission unsupported')
    pip=10.**(-int(spec['pipPosition']));mid=(bid+ask)/2
    fee_per_side=max(rate*units*mid/1e6,minimum)
    return dict(spread_pips=(ask-bid)/pip,commission_roundtrip_pips=2*fee_per_side/units/pip,
        roundtrip_proxy_pips=((ask-bid)+2*fee_per_side/units)/pip,units=units,
        cost_complete=False,includes_slippage=False,historical=False)


REMOTE="""
import config,requests,json,time
samples=[];session=requests.Session()
try:
 for i in range(8):
  p=session.get('http://127.0.0.1:8080/api/live_price',params={'pairs':'EURUSD','format':'paper','admin_token':config.get_admin_access_token()},timeout=(3,6)).json()
  samples.append({'ts':time.time(),'quote':p.get('quotes',{}).get('EURUSD')})
  if i<7:time.sleep(2)
 print(json.dumps({'samples':samples}))
except Exception as e:print(json.dumps({'error_type':type(e).__name__,'completed':len(samples)}))
"""


def main():
    metadata=json.loads((HERE.parent/'research_schedule_audit_20261014'/'metadata.json').read_text('utf-8'))
    spec=next(s for s in metadata['symbols'] if s['name']=='EURUSD')['specification']
    binary=shutil.which('fly')
    if not binary:raise RuntimeError('Fly unavailable; no credential fallback')
    encoded=base64.b64encode(REMOTE.encode()).decode()
    command='python -c "exec(__import__(\'base64\').b64decode(\''+encoded+'\'))"'
    result=subprocess.run([binary,'ssh','console','--app','zigzag-bot-package','--command',command],
        capture_output=True,text=True,timeout=60)
    # Never print command, raw stderr, URLs or configuration. Only structured sanitized market data.
    lines=[s for s in result.stdout.splitlines() if s.startswith('{')]
    if result.returncode or not lines:raise RuntimeError('Read-only sample unavailable')
    payload=json.loads(lines[-1])
    if 'error_type' in payload:raise RuntimeError('Sampler failed: '+payload['error_type'])
    accepted=[];rejected=0
    for sample in payload['samples']:
        try:
            if not sample['quote']:raise ValueError('No fresh sides')
            accepted.append(dict(sample=sample,estimate=estimate(spec,sample['quote'],sample['ts'])))
        except (KeyError,ValueError,TypeError):rejected+=1
    proxy=[r['estimate']['roundtrip_proxy_pips'] for r in accepted]
    report=dict(tariff_snapshot_utc=metadata['fetched_utc'],accepted=len(accepted),rejected=rejected,
        samples=accepted,cost_complete=False,historical=False,orders=False,
        proxy_range_pips=[min(proxy),max(proxy)] if proxy else None,
        proxy_median_pips=float(np.median(proxy)) if proxy else None)
    (HERE/'current_cost_sample.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'}))


if __name__=='__main__':main()
