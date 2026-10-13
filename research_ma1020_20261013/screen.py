"""Frozen MA+exchange volume interpretation; cached spot LONG observations."""
from bisect import bisect_left
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import gzip
import hashlib
import json
import math
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
START=1767225600;END=1791417600;SPLIT=1782864000


def load(asset,tf):
    folder=HERE/'cache' if tf=='M15' else ROOT/'research_new_methods_20261007'/'inverse_price_cache'
    name=asset+'USDT_complete.json' if tf=='M15' else asset+'_spot_complete.json'
    manifest=json.loads((folder/name).read_text(encoding='utf-8'))
    if not manifest['complete']:raise ValueError('Incomplete cache')
    rows=[];hashes={}
    for page in manifest['pages']:
        name=page['file'] if isinstance(page,dict) else page;file=folder/name
        digest=hashlib.sha256(file.read_bytes()).hexdigest();hashes[name]=digest
        if isinstance(page,dict) and digest!=page['sha256']:raise ValueError('Cache revision')
        with gzip.open(file,'rt',encoding='utf-8') as f:raw=json.load(f)
        for r in raw:
            ts=int(r[0])//1000
            if START<=ts<END:
                o,h,l,c,v=map(float,r[1:6])
                if not all(math.isfinite(x) for x in (o,h,l,c,v)) or not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError('Invalid exchange OHLCV')
                rows.append(dict(ts=ts,Open=o,High=h,Low=l,Close=c,Volume=v))
    rows.sort(key=lambda b:b['ts']);step=900 if tf=='M15' else 3600
    if [b['ts'] for b in rows]!=list(range(START,END,step)):raise ValueError('Missing/duplicate exchange candles')
    return rows,hashes


def detect(bars,step,ma='SMA',volume=True):
    if ma not in ('SMA','EMA'):raise ValueError('MA type')
    history=[];fast=slow=None;previous=None;out=[];prev_ts=None
    for b in bars:
        if prev_ts is None or b['ts']-prev_ts!=step:history=[];fast=slow=None;previous=None
        baseline=sum(r['Volume'] for r in history[-20:])/20 if len(history)>=20 else None
        c=b['Close']
        if ma=='EMA':
            fast=c if fast is None else fast+2/11*(c-fast)
            slow=c if slow is None else slow+2/21*(c-slow)
        history=(history+[b])[-40:]
        if ma=='SMA' and len(history)>=20:
            fast=sum(r['Close'] for r in history[-10:])/10;slow=sum(r['Close'] for r in history[-20:])/20
        if len(history)>=40 and previous and previous[0]<=previous[1] and fast>slow and c>max(fast,slow):
            if not volume or (baseline is not None and baseline>0 and b['Volume']>=1.5*baseline):
                out.append(dict(ts=b['ts']+step,stop=min(r['Low'] for r in history[-10:])-.01,
                    ny_date=datetime.fromtimestamp(b['ts'],timezone.utc).date().isoformat(),volume=b['Volume'],volume_baseline=baseline))
        previous=(fast,slow) if fast is not None else None;prev_ts=b['ts']
    return out


def simulate(intent,path,cost,step):
    if not path or path[0]['ts']!=intent['ts']:return dict(status='unknown',reason='missing_entry')
    entry=path[0]['Open'];stop=intent['stop'];distance=entry-stop
    if distance<=0:return dict(status='skipped',reason='open_through_stop')
    target=entry+2*distance;previous=None
    for b in path:
        if previous is not None and b['ts']-previous!=step:return dict(status='unknown',reason='path_gap')
        stopped=b['Low']<=stop;targeted=b['High']>=target
        if stopped or targeted:
            gap=b['Open']<=stop;exit_=b['Open'] if gap else stop if stopped else target
            return dict(status='closed',reason='stop_gap' if gap else 'stop' if stopped else 'target',
                net_R=(exit_-entry-cost)/(distance+cost),ambiguous=stopped and targeted,exit_ts=b['ts']+step)
        previous=b['ts']
    return dict(status='pending' if path[-1]['ts']+step>=END else 'unknown',reason='coverage_end')


def replay(bars,intents,step,cost_fraction):
    times=[b['ts'] for b in bars];rows=[];blocked=0;skips=0
    for intent in intents:
        if intent['ts']<blocked:skips+=1;continue
        i=bisect_left(times,intent['ts']);j=len(bars)
        path=bars[i:j];cost=(path[0]['Open'] if path else 0)*cost_fraction
        result=simulate(intent,path,cost,step);rows.append(dict(intent=intent,**result))
        if result['status']=='closed':blocked=result['exit_ts']
        elif result['status'] in ('pending','unknown'):break
    return rows,skips


def summarize(rows):
    closed=[r for r in rows if r['status']=='closed'];values=[r['net_R'] for r in closed]
    days=sorted({r['intent']['ny_date'] for r in rows});daily=defaultdict(list)
    for r in closed:daily[r['intent']['ny_date']].append(r['net_R'])
    ci=None
    if len(days)>=20 and values:
        sums=np.array([sum(daily[d]) for d in days]);counts=np.array([len(daily[d]) for d in days])
        rng=np.random.default_rng(20261013);starts=rng.integers(0,len(days),(6000,(len(days)+9)//10))
        idx=((starts[:,:,None]+np.arange(10))%len(days)).reshape(6000,-1)[:,:len(days)]
        n=counts[idx].sum(axis=1);v=sums[idx].sum(axis=1)[n>0]/n[n>0]
        ci=np.quantile(v,[.025/64,1-.025/64]).tolist()
    gain=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0)
    return dict(setups=len(rows),closed=len(values),statuses=dict(Counter(r['status'] for r in rows)),
        wins=sum(v>0 for v in values),net_R_sum=sum(values),mean_net_R=sum(values)/len(values) if values else None,
        profit_factor=gain/loss if loss else None,simultaneous_95_ci=ci)


def main():
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
        long_only_spot=True,exact_author_rules=False,real_orders=False,arms=[],gates={})
    for asset in ('BTC','ETH'):
        for tf,step in [('M15',900),('H1',3600)]:
            bars,hashes=load(asset,tf);report.setdefault('hashes',{})[asset+'/'+tf]=hashes
            for ma in ('SMA','EMA'):
                for volume in (True,False):
                    intents=detect(bars,step,ma,volume);checks=[]
                    for scenario,cost in [('base',.002),('stress',.003)]:
                        rows,skips=replay(bars,intents,step,cost)
                        for phase in ('early','late'):
                            selected=[r for r in rows if (r['intent']['ts']<SPLIT)==(phase=='early')]
                            row=dict(asset=asset,tf=tf,ma=ma,volume=volume,scenario=scenario,phase=phase,
                                overlap_skips_full_period=skips,candidates_full_period=len(intents),**summarize(selected))
                            report['arms'].append(row)
                            if scenario=='stress':checks.append(row)
                            print(json.dumps(row),flush=True)
                    report['gates'][asset+'/'+tf+'/'+ma+'/'+str(volume)]=all(r['mean_net_R'] is not None and r['mean_net_R']>0 and r['simultaneous_95_ci'] and r['simultaneous_95_ci'][0]>0 and not r['statuses'].get('unknown') and not r['statuses'].get('pending') for r in checks) and checks[-1]['closed']>=100
    # Controls are diagnostics; never promote a failing-volume replacement.
    for key in list(report['gates']):
        if key.endswith('/True'):
            a,tf,ma,_=key.split('/')
            means=[r['mean_net_R'] for r in report['arms'] if r['asset']==a and r['tf']==tf and r['ma']==ma and r['scenario']=='stress' and r['phase']=='late']
            report['gates'][key]=report['gates'][key] and all(x is not None for x in means) and means[0]>means[1]
    (HERE/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'])),flush=True)


if __name__=='__main__':main()
