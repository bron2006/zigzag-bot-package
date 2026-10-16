"""Offline crypto weekend screen, all prices Decimal, no app initialization."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D, ROUND_HALF_EVEN
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
START=1704067200;END=1791417600;HOUR=3600;WEEK=7*86400
Q=D('.000000000001')
def price(value):
    x=D(str(value))
    if not x.is_finite():raise ValueError('Nonfinite price')
    return x.quantize(Q,rounding=ROUND_HALF_EVEN)

def load(asset):
    folder=ROOT/'research_new_methods_20261007/inverse_price_cache'
    manifest_path=folder/f'{asset}_spot_complete.json'
    manifest=json.loads(manifest_path.read_text('utf-8'))
    if not manifest['complete']:raise ValueError('Incomplete manifest')
    bt={};hashes={manifest_path.name:hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    for page in manifest['pages']:
        name=page['file'] if isinstance(page,dict) else page;path=folder/name
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        if isinstance(page,dict) and hashes[name]!=page['sha256']:raise ValueError('Input changed')
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for r in json.load(stream):
                ts=int(r[0])//1000
                if not START<=ts<END:continue
                if ts%3600 or ts in bt:raise ValueError('Duplicate or offgrid hour')
                o,h,l,c=[price(v) for v in r[1:5]]
                if not 0<l<=min(o,c)<=max(o,c)<=h:raise ValueError('Invalid OHLC')
                bt[ts]=dict(Open=o,High=h,Low=l,Close=c)
    return bt,hashes,dict(bars=len(bt),missing_hours=(END-START)//HOUR-len(bt),
        first_ts=min(bt),last_ts=max(bt),legacy_acquisition_hashes=all(isinstance(p,dict) for p in manifest['pages']))

def atr_at(bt,decision):
    times=list(range(decision-15*HOUR,decision,HOUR))
    if any(t not in bt for t in times):return None
    tr=[]
    for a,b in zip(times,times[1:]):
        p,c=bt[a],bt[b];tr.append(max(c['High']-c['Low'],abs(c['High']-p['Close']),abs(c['Low']-p['Close'])))
    return price(sum(tr)/D(14))

def simulate(bt,entry,side,distance,end=END):
    if side not in (-1,1) or distance<=0:raise ValueError('Invalid terms')
    if entry>=end:return dict(status='pending',reason='entry_outside_cache',entry_ts=entry)
    if entry not in bt:return dict(status='unknown',reason='missing_entry',entry_ts=entry)
    op=bt[entry]['Open'];stop=op-D(side)*price(distance)
    if stop<=0:raise ValueError('Nonpositive stop')
    result=dict(entry_ts=entry,entry=float(op),stop=float(stop),distance=float(distance),side=side)
    for ts in range(entry,entry+48*HOUR,HOUR):
        if ts>=end:return dict(**result,status='pending',reason='unfinished_path')
        b=bt.get(ts)
        if b is None:return dict(**result,status='unknown',reason='path_gap',missing_ts=ts)
        gap=D(side)*(b['Open']-stop)<=0
        hit=b['Low']<=stop if side==1 else b['High']>=stop
        if gap or hit:
            out=b['Open'] if gap else stop;exit_ts=ts if gap else ts+HOUR
            gross=D(side)*(out-op)/op
            return dict(**result,status='closed',reason='gap_stop' if gap else 'stop',
                exit=float(out),exit_ts=exit_ts,charged_hours=(exit_ts-entry)//HOUR,gross=float(gross))
    target=entry+48*HOUR
    if target>=end:return dict(**result,status='pending',reason='missing_deadline_after_cache')
    if target not in bt:return dict(**result,status='unknown',reason='missing_deadline',missing_ts=target)
    out=bt[target]['Open']
    return dict(**result,status='closed',reason='deadline',exit=float(out),exit_ts=target,
        charged_hours=48,gross=float(D(side)*(out-op)/op))

def costed(outcome,case):
    if outcome['status']!='closed':return dict(outcome)
    fee={'gross':0.,'base':.002,'stress':.003}[case]
    carry=.2*outcome['charged_hours']/(365*24) if case!='gross' and outcome['side']==1 else 0.
    return dict(**outcome,friction=fee,financing=carry,net=outcome['gross']-fee-carry)

def observations(bt,end=END):
    rows=[];week=START;halted=False
    while week<end:
        friday=week+4*86400+20*HOUR;tuesday=week+86400+20*HOUR
        record=dict(week=week,year=datetime.fromtimestamp(friday,timezone.utc).year,arms={})
        for name,entry,side in [('weekend',friday,1),('weekday',tuesday,1),('short',friday,-1)]:
            if name=='weekend' and halted:
                out=dict(status='halted',reason='earlier_unknown',entry_ts=entry)
            elif entry>=end:out=dict(status='pending',reason='entry_outside_cache',entry_ts=entry)
            else:
                distance=atr_at(bt,entry-HOUR)
                out=dict(status='feature_unknown',reason='missing_past_atr',entry_ts=entry) if distance is None else simulate(bt,entry,side,2*distance,end)
                out.update(decision_ts=entry-HOUR,atr_first_ts=entry-16*HOUR,atr_last_ts=entry-2*HOUR,
                    atr=float(distance) if distance is not None else None)
            record['arms'][name]=out
        if record['arms']['weekend']['status']=='unknown':halted=True
        rows.append(record);week+=WEEK
    return rows

def block_ci(rows,values):
    # Calendar weeks include known nofeature as no observations, NOT zero returns.
    if not len(rows) or not values:return None
    n=len(rows);sums=np.array([values.get(r['week'],0.) for r in rows]);counts=np.array([r['week'] in values for r in rows])
    rng=np.random.default_rng(20261016);starts=rng.integers(0,n,(10000,(n+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%n).reshape(10000,-1)[:,:n]
    cnt=counts[idx].sum(axis=1);means=sums[idx].sum(axis=1)[cnt>0]/cnt[cnt>0]
    return (np.quantile(means,[.025/16,1-.025/16])*10000).tolist()

def summarize(rows,case,year):
    selected=[r for r in rows if r['year']==year];known=[];paired={'weekday':{},'short':{}}
    statuses={};censored={'weekday':0,'short':0}
    # Truncate CI support at unknown/halted candidate, no fake laterflat weeks.
    support=[]
    for r in selected:
        o=costed(r['arms']['weekend'],case);statuses[o['status']]=statuses.get(o['status'],0)+1
        if o['status'] in ('unknown','halted'):continue
        support.append(r)
        if o['status']!='closed':continue
        known.append((r,o))
        for name in paired:
            c=costed(r['arms'][name],case)
            if c['status']=='closed':paired[name][r['week']]=o['net']-c['net']
            else:censored[name]+=1
    values={r['week']:o['net'] for r,o in known};v=np.array(list(values.values()))
    gain=v[v>0].sum();loss=-v[v<0].sum()
    return dict(year=year,status_counts=statuses,known=len(v),mean_bp=float(v.mean()*10000) if len(v) else None,
        sum_independent_bp=float(v.sum()*10000),win_fraction=float((v>0).mean()) if len(v) else None,
        profit_factor=float(gain/loss) if loss else None,max_loss_bp=float(v.min()*10000) if len(v) else None,
        adjusted_ci_bp=block_ci(support,values),paired_censored=censored,
        paired_known={k:len(v) for k,v in paired.items()},
        paired_excess_ci_bp={k:block_ci(support,v) for k,v in paired.items()})

def main():
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),observations_only=True,
        venue_schedule_not_modeled=True,historical_bid_ask_unknown=True,
        financing_sensitivity_not_actual_friday_3x_swap=True,assets={})
    for asset in ('BTC','ETH'):
        bt,hashes,coverage=load(asset);rows=observations(bt);cases={}
        for case in ('gross','base','stress'):
            cases[case]=[summarize(rows,case,year) for year in (2024,2025,2026)]
            print(json.dumps(dict(asset=asset,case=case,summaries=cases[case])),flush=True)
        late=cases['stress'][-1]
        gate=bool(all(s['mean_bp'] is not None and s['mean_bp']>0 and not s['status_counts'].get('unknown',0) for case in ('gross','stress') for s in cases[case])
            and all(s['known']>=30 for s in cases['stress'][1:]) and late['adjusted_ci_bp'][0]>0
            and all(v is not None and v[0]>0 for v in late['paired_excess_ci_bp'].values()))
        report['assets'][asset]=dict(input_hashes=hashes,coverage=coverage,rows=rows,cases=cases,gate=gate)
    report['gate']=all(a['gate'] for a in report['assets'].values())
    (HERE/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print('FINISHED gate='+str(report['gate']),flush=True)

if __name__=='__main__':main()
