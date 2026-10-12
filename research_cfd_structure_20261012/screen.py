"""Offline bounded CFD screen. Cached prices only; no production imports."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from comparative_screen import load_history
from paper_cfd import size_position,simulate_stop_trade,net_usd
from price_structure_candidates import RULES,generate


def hourly(frame):
    rows=[]
    for start,g in frame.groupby(frame.ts//3600):
        ts=int(start)*3600
        if g.ts.tolist()!=list(range(ts,ts+3600,300)):continue
        rows.append(dict(ts=ts,Open=float(g.Open.iloc[0]),High=float(g.High.max()),Low=float(g.Low.min()),Close=float(g.Close.iloc[-1])))
    return rows


def replay(schedule,frames,cost,control=None):
    cash=Decimal('1000.00');peak=cash;dd=0;skips=Counter();journal=[]
    for intent in schedule:
        pair=intent['pair'];frame=frames[pair];ts=intent['ts'];end=intent['day']*86400+16*3600
        bars=frame[(frame.ts>=ts)&(frame.ts<end)].to_dict('records')
        if not bars or bars[0]['ts']!=ts or bars[-1]['ts']!=end-300 or any(bars[i]['ts']-bars[i-1]['ts']!=300 for i in range(1,len(bars))):
            skips['unknown_path']+=1;continue
        entry=bars[0]['Open'];side=intent['side'];distance=2*intent['atr'];multiple=1.5
        if intent['stop'] is not None:
            distance=side*(entry-intent['stop']);reward=side*(intent['target']-entry)
            if distance<=0 or reward<=0 or (reward-cost)/(distance+cost)<1.5:
                skips['invalid_entry_or_net_RR']+=1;continue
            multiple=reward/distance
        units=0 if cash<=0 else size_position(float(cash),entry,distance,cost,minimum=1000,step=1000,maximum=1e7)
        if not units:skips['below_minimum_size']+=1;continue
        if control is not None:side=control
        trade=simulate_stop_trade(bars,0,side,distance,multiple)
        if trade['status']!='closed':skips['unknown_path']+=1;continue
        points=Decimal(str(side))*(Decimal(str(trade['exit']))-Decimal(str(entry)))
        pnl=(Decimal(str(units))*(points-Decimal(str(cost)))).quantize(Decimal('.01'))
        cash+=pnl;peak=max(peak,cash);dd=max(dd,float((peak-cash)/peak))
        journal.append(dict(pair=pair,day=datetime.fromtimestamp(ts,timezone.utc).date().isoformat(),
            entry_ts=ts,exit_ts=trade['exit_ts'],side=side,entry=entry,stop=trade['stop'],target=trade['target'],
            exit=trade['exit'],units=units,net_usd=str(pnl),balance_usd=str(cash),
            net_R=(trade['gross_points']-cost)/(distance+cost),reason=trade['reason'],ambiguous=trade['ambiguous']))
    return dict(initial=1000,balance=str(cash),net=str(cash-1000),trades=len(journal),
                realized_cash_drawdown=dd,skips=dict(skips),journal=journal)


def ci(rows,axis,subtract=None):
    if len(axis)<10 or not rows:return None
    lookup={day:i for i,day in enumerate(axis)};sums=np.zeros(len(axis));count=np.zeros(len(axis))
    other={r['day']:r for r in subtract or []}
    for row in rows:
        if subtract is not None and row['day'] not in other:return None
        i=lookup[row['day']];sums[i]+=row['net_R']-(other[row['day']]['net_R'] if subtract is not None else 0);count[i]+=1
    rng=np.random.default_rng(20261012);starts=rng.integers(0,len(axis),(4000,(len(axis)+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%len(axis)).reshape(4000,-1)[:,:len(axis)]
    n=count[idx].sum(axis=1);samples=sums[idx].sum(axis=1)[n>0]/n[n>0]
    return np.quantile(samples,[.05/6,1-.05/6]).tolist()


def main():
    folder=Path(__file__).parent;frames={};hours={};hashes={}
    for pair in ('EURUSD','GBPUSD'):
        frames[pair],hashes[pair]=load_history(pair);hours[pair]=hourly(frames[pair])
        print(json.dumps(dict(pair=pair,m5=len(frames[pair]),h1=len(hours[pair]))),flush=True)
    report=dict(protocol_sha256=hashlib.sha256((folder/'PROTOCOL.md').read_bytes()).hexdigest(),
        sources_sha256=hashes,proven_edge=False,production_active=False,retrospective_reused_history=True,arms=[])
    for rule in RULES:
        intents=sorted([dict(item,pair=pair) for pair in frames for item in generate(hours[pair],rule)],key=lambda r:(r['ts'],r['pair']))
        days=set();schedule=[]
        for item in intents:
            if item['day'] not in days:schedule.append(item);days.add(item['day'])
        phases={label:[r for r in schedule if (r['ts']<1767225600)==(label=='early')] for label in ('early','late')}
        outputs={}
        for phase,selected in phases.items():
            axis=sorted({datetime.fromtimestamp(r['ts'],timezone.utc).date().isoformat() for r in selected})
            outputs[phase]={}
            for scenario,cost in [('base',.0002),('stress',.0004)]:
                row=dict(rule=rule,phase=phase,scenario=scenario,scheduled=len(selected),**replay(selected,frames,cost))
                buy=replay(selected,frames,cost,1);sell=replay(selected,frames,cost,-1)
                row['controls']={name:{k:v for k,v in result.items() if k!='journal'} for name,result in [('buy',buy),('sell',sell)]}
                row['net_R_ci']=ci(row['journal'],axis)
                row['excess_buy_ci']=ci(row['journal'],axis,buy['journal']);row['excess_sell_ci']=ci(row['journal'],axis,sell['journal'])
                row['yearly']={year:dict(trades=len(values),net=str(sum((Decimal(v['net_usd']) for v in values),Decimal('0')))) for year,values in sorted(group_years(row['journal']).items())}
                outputs[phase][scenario]=row
                report['arms'].append(row)
                print(json.dumps({k:v for k,v in row.items() if k not in ('journal','controls')}),flush=True)
        early=outputs['early']['stress'];late=outputs['late']['stress']
        passed=Decimal(early['net'])>0 and Decimal(late['net'])>0 and late['trades']>=100 and not late['skips'].get('unknown_path') and all(late.get(k) and late[k][0]>0 for k in ('net_R_ci','excess_buy_ci','excess_sell_ci'))
        report.setdefault('gates',{})[rule]=bool(passed)
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'],production_active=False)),flush=True)


def group_years(journal):
    result=defaultdict(list)
    for row in journal:result[row['day'][:4]].append(row)
    return result


if __name__=='__main__':main()
