"""Offline fixed weekday FX drift. No production initialization or network."""
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent; ROOT=HERE.parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
h=module('calendar_h',ROOT/'research_walkforward_20261015/higher_timeframes.py')
ledger=module('calendar_l',ROOT/'research_walkforward_20261015/higher_audit.py');wf=h.wf
stable=module('calendar_stable',ROOT/'research_dispatch_20261016/price_replay.py')
LONDON=ZoneInfo('Europe/London')

def slot(day):
    decision=int(datetime.combine(day,time(8),LONDON).timestamp())
    return decision,decision+300

def days(begin,end):
    d=begin
    while d<end:
        if d.weekday()<5:yield d
        d+=timedelta(days=1)

def fit_directions(by_ts):
    samples={i:[] for i in range(5)}
    for day in days(datetime(2024,1,1).date(),datetime(2025,1,1).date()):
        _,entry=slot(day);path=[by_ts.get(t) for t in range(entry,entry+14400,300)]
        if all(b is not None for b in path):samples[day.weekday()].append(path[-1]['Close']/path[0]['Open']-1)
    return {str(k):dict(n=len(v),mean_return=float(np.mean(v)) if v else None,
        side=int(np.sign(np.mean(v))) if len(v)>=30 else 0) for k,v in samples.items()}

def prior_atr(bars,decision):
    history=[b for b in bars if b['ts']+3600<=decision][-15:]
    if len(history)<15 or decision-(history[-1]['ts']+3600)>7200:return None
    if any(b['ts']-a['ts']>7*86400 for a,b in zip(history,history[1:])):return None
    return sum(max(b['High']-b['Low'],abs(b['High']-a['Close']),abs(b['Low']-a['Close']))
               for a,b in zip(history,history[1:]))/14

def intents_for(by_ts,bars,fit,end):
    intents=[];skips=Counter()
    for day in days(datetime(2025,1,1).date(),datetime.fromtimestamp(end,timezone.utc).date()):
        decision,entry=slot(day);side=fit[str(day.weekday())]['side']
        if not side:skips['untrained_weekday']+=1;continue
        atr=prior_atr(bars,decision)
        if atr is None or atr<=0:skips['missing_atr']+=1;continue
        last=by_ts.get(decision-300)
        if last is None:skips['missing_decision_bar']+=1;continue
        intents.append(dict(decision_ts=decision,entry_ts=entry,side=side,stop_distance=1.5*atr,
            signal_close=last['Close'],month=day.strftime('%Y-%m')))
    return intents,dict(skips)

def replay(intents,by_ts,volume,cost):
    rows=[];skips=Counter();blocked=-1
    for intent in intents:
        if intent['entry_ts']<blocked:skips['position_open']+=1;continue
        distance=intent['stop_distance'];first=by_ts.get(intent['entry_ts'])
        if not ledger.math.size_position(1000,intent['signal_close'],distance,.0004,
                minimum=volume['minVolume'],step=volume['stepVolume'],maximum=volume['maxVolume']):
            skips['decision_minimum_size']+=1;continue
        if first is not None and not ledger.math.size_position(1000,first['Open'],distance,.0004,
                minimum=volume['minVolume'],step=volume['stepVolume'],maximum=volume['maxVolume']):
            skips['entry_minimum_size']+=1;continue
        outcome=stable.simulate(by_ts,intent['entry_ts'],14400,intent['side'],distance,cost)
        row={**intent,**outcome}
        if row['status']=='closed':
            blocked=row['exit_ts']
            for key,side in [('buy',1),('sell',-1),('opposite',-intent['side'])]:
                c=stable.simulate(by_ts,intent['entry_ts'],14400,side,distance,cost)
                row['excess_'+key]=row['net_R']-c['net_R'] if c['status']=='closed' else None
        rows.append(row)
        if row['status']=='unknown':break
    return rows,dict(skips)

def block_ci(rows,key,year,end):
    """Only observed prefix: never pad post-unknown halted days as zero trades."""
    begin=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp())
    end=min(end,int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()))
    n=(end-begin)//86400
    if n<10:return None
    daily=np.zeros(n)
    for r in rows:
        if begin<=r['decision_ts']<begin+n*86400 and r['status']=='closed':
            daily[(r['decision_ts']-begin)//86400]+=r[key]
    rng=np.random.default_rng(20261015);starts=rng.integers(0,n,(10000,(n+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%n).reshape(10000,-1)[:,:n]
    return np.quantile(daily[idx].mean(axis=1),[.025/64,1-.025/64]).tolist()

def main():
    metadata=json.loads((ROOT/'research_schedule_audit_20261014/metadata.json').read_text('utf-8'))
    originals={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
        original_hashes=originals,metadata_fetched=metadata['fetched_utc'],pairs={})
    for symbol in ('EURUSD','GBPUSD'):
        raw,hashes,duplicates=wf.load(symbol);by_ts={int(b['ts']):b for b in raw.to_dict('records')}
        bars,partial=h.aggregate(raw,3600);fit=fit_directions(by_ts)
        intents,skip=intents_for(by_ts,bars.to_dict('records'),fit,wf.END)
        s=next(x for x in metadata['symbols'] if x['name']==symbol)['specification']
        volume={k:float(s[k])/100 for k in ('minVolume','stepVolume','maxVolume')}
        pair=dict(input_hashes=hashes,duplicates=duplicates,fit=fit,intents=len(intents),
            skips=skip,partial_h1=partial,volume=volume,scenarios={})
        checks=[]
        for scenario,cost in [('base',.0002),('stress',.0004)]:
            rows,skips=replay(intents,by_ts,volume,cost);summaries=[]
            cutoff=min([r['decision_ts']//86400*86400 for r in rows if r['status']=='unknown']+[wf.END])
            for year in (2025,2026):
                yr=[r for r in rows if r['month'].startswith(str(year))]
                complete=[r for r in yr if r['status']=='closed' and all(r.get('excess_'+k) is not None for k in ('buy','sell','opposite'))]
                summary=dict(year=year,**h.summary(yr),ci_observation_cutoff_utc=cutoff,daily_R_ci=block_ci(yr,'net_R',year,cutoff),
                    control_censored=sum(r['status']=='closed' for r in yr)-len(complete),
                    excess_ci={k:block_ci(complete,'excess_'+k,year,cutoff) for k in ('buy','sell','opposite')})
                summaries.append(summary)
                if scenario=='stress':checks.append(summary)
            prefix=ledger.ledger([dict(r,scenario=scenario) for r in rows if r['status']=='closed'],volume['minVolume'],volume['stepVolume'],volume['maxVolume'])
            projection=prefix if all(r['status']=='closed' for r in rows) else dict(status='unknown_paths',known_prefix=prefix,not_full_period_balance=True)
            pair['scenarios'][scenario]=dict(rows=rows,skips=skips,summaries=summaries,projection=projection)
            console_projection=projection.get('known_prefix',projection)
            print(json.dumps(dict(symbol=symbol,scenario=scenario,summaries=summaries,
                projection_status=projection.get('status','complete'),
                projection={k:v for k,v in console_projection.items() if k!='trades'})),flush=True)
        cash=pair['scenarios']['stress']['projection'].get('year_end_balances',{})
        pair['gate']=bool(all(x['closed']>=50 and x['unknown']==0 and x['control_censored']==0 and x['sum_R']>0 for x in checks)
            and checks[-1]['daily_R_ci'][0]>0 and all(v[0]>0 for v in checks[-1]['excess_ci'].values())
            and cash.get('2025',0)>1000 and cash.get('2026',0)>cash.get('2025',1000))
        report['pairs'][symbol]=pair
    for name,digest in originals.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    report['gate']=all(p['gate'] for p in report['pairs'].values())
    (HERE/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print('FINISHED gate='+str(report['gate']),flush=True)

if __name__=='__main__':main()
