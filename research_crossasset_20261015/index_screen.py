"""Fixed-clock USTEC test with causal protective stop, offline only."""
from collections import Counter
from datetime import date, datetime, time, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('nasdaq_cached_reader',HERE.parent/'research_nasdaq_pullback_20261010'/'screen.py')
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
NY=ZoneInfo('America/New_York')


def simulate(pre,path,side):
    if len(pre)!=15 or len(path)!=12 or any(b['ts']-a['ts']!=300 for a,b in zip(pre+path,(pre+path)[1:])):
        return dict(status='unknown')
    atr=sum(max(b['High']-b['Low'],abs(b['High']-a['Close']),abs(b['Low']-a['Close'])) for a,b in zip(pre,pre[1:]))/14
    if atr<=0:return dict(status='unknown')
    entry=path[0]['Open'];stop=entry-side*2*atr
    price,ts,reason,*_=reader.exit_trade(path,0,side,stop)
    return dict(status='closed',gross_points=side*(price-entry),reason=reason,
                risk_points=2*atr,unstopped_points=side*(path[-1]['Close']-entry))


def interval(values,days,n_days):
    if not values:return None
    sums=np.bincount(days,weights=values,minlength=n_days);counts=np.bincount(days,minlength=n_days)
    rng=np.random.default_rng(20261015);starts=rng.integers(0,n_days,(10000,(n_days+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%n_days).reshape(10000,-1)[:,:n_days]
    ns=counts[idx].sum(axis=1);means=sums[idx].sum(axis=1)[ns>0]/ns[ns>0]
    return np.quantile(means,[.025/64,1-.025/64]).tolist()


def main():
    bars,hashes,duplicates=reader.load_history('M5');by_ts={b['ts']:b for b in bars}
    arms={'main':(2,1),'short_control':(2,-1),'later_control':(3,1)}
    records={k:[] for k in arms};day=date(2024,1,1)
    while day<date(2026,10,8):
        if day.weekday()<5 and day.isoformat() not in reader.HOLIDAYS|reader.EARLY:
            for arm,(hour,side) in arms.items():
                start=int(datetime.combine(day,time(hour),NY).timestamp())
                prior=list(range(start-4500,start,300));path=list(range(start,start+3600,300))
                result=simulate([by_ts[t] for t in prior if t in by_ts],[by_ts[t] for t in path if t in by_ts],side)
                records[arm].append(dict(day=day.isoformat(),year=day.year,**result))
        day+=timedelta(days=1)
    result=dict(protocol_sha256=hashlib.sha256((HERE/'INDEX_PROTOCOL.md').read_bytes()).hexdigest(),
                hashes=hashes,duplicates=duplicates,rows=records,summaries=[])
    for arm,rows in records.items():
        for year in (2024,2025,2026):
            selected=[r for r in rows if r['year']==year];closed=[r for r in selected if r['status']=='closed']
            first=date(year,1,1);last=date(year+1,1,1) if year<2026 else date(2026,10,8)
            days=[(date.fromisoformat(r['day'])-first).days for r in closed]
            for scenario,cost in [('gross',0),('base',2),('stress',5)]:
                values=[r['gross_points']-cost for r in closed]
                summary=dict(arm=arm,year=year,scenario=scenario,scheduled=len(selected),closed=len(closed),
                    coverage=len(closed)/len(selected),statuses=dict(Counter(r['status'] for r in selected)),
                    mean_points=float(np.mean(values)) if values else None,wins=sum(v>0 for v in values),
                    sum_independent_points=sum(values),stops=sum(r['reason']!='session_close' for r in closed),
                    adjusted_ci_points=interval(values,days,(last-first).days))
                result['summaries'].append(summary);print(json.dumps(summary),flush=True)
    checks=[r for r in result['summaries'] if r['arm']=='main' and r['scenario']=='stress']
    result['gate']=bool(all(r['mean_points'] is not None and r['mean_points']>0 and r['coverage']>=.95 for r in checks)
                        and checks[-1]['closed']>=100 and checks[-1]['adjusted_ci_points'][0]>0)
    (HERE/'index_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(gate=result['gate'])))


if __name__=='__main__':main()
