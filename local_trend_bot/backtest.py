"""Offline fixed-rule screen; never imports the existing bot or credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from .strategy import SYMBOLS,RULES,execution_positions,validate


def timestamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)


def simulate(rows,positions,fee):
    cash,units=1.,0.
    curve=[]
    changes=0
    for row,desired in zip(rows,positions,strict=True):
        opening,close=float(row[1]),float(row[4])
        if desired and not units:
            units,cash=cash*(1-fee)/opening,0.
            changes+=1
        elif not desired and units:
            cash,units=units*opening*(1-fee),0.
            changes+=1
        curve.append(cash+units*close)
    if units:
        curve[-1]*=1-fee
        changes+=1
    return curve,changes


def stats(curve):
    peak=1.
    dd=0.
    for value in curve:
        peak=max(peak,value)
        dd=min(dd,value/peak-1)
    return dict(total_return=curve[-1]-1,max_drawdown=dd)


def paired_lower(curve,control,repeats=1000):
    previous,previous_control=1.,1.
    excess=[]
    for value,baseline in zip(curve,control,strict=True):
        excess.append(math.log(value/previous)-math.log(baseline/previous_control))
        previous,previous_control=value,baseline
    rng=random.Random(20261008)
    samples=[]
    n=len(excess)
    for _ in range(repeats):
        total=0.
        count=0
        while count<n:
            start=rng.randrange(n)
            size=min(30,n-count)
            total+=sum(excess[(start+j)%n] for j in range(size))
            count+=size
        samples.append(total/n)
    samples.sort()
    return samples[int(.0125*repeats)]


def screen(directory,repeats=1000):
    report=dict(version='local-trend-v1',retrospective=True,proven_edge=False,rules={})
    for rule in RULES:
        records=[]
        for symbol in SYMBOLS:
            path=Path(directory)/f'{symbol}_1d.json'
            rows=json.loads(path.read_text(encoding='utf-8'))['rows']
            validate(rows)
            if rows[0][0]!=timestamp('2019-01-01') or rows[-1][0]!=timestamp('2026-09-30'):
                raise ValueError('History does not match fixed protocol range')
            positions=execution_positions(rows,rule)
            blocks={}
            for name,start,end in [('early','2020-01-01','2024-01-01'),('late','2024-01-01','2026-10-01')]:
                selected=[(r,p) for r,p in zip(rows,positions) if timestamp(start)<=r[0]<timestamp(end)]
                bars,pos=map(list,zip(*selected))
                models={}
                for label,fee in [('base',.001),('stress',.003)]:
                    curve,changes=simulate(bars,pos,fee)
                    hold,_=simulate(bars,[1]*len(bars),fee)
                    exposure=sum(pos)/len(pos)
                    matched=[1-exposure+exposure*v for v in hold]
                    models[label]=dict(**stats(curve),changes=changes,exposure=exposure,
                                       buy_hold=stats(hold),matched_hold=stats(matched))
                    if name=='late' and label=='stress':
                        models[label]['adjusted_lower_mean_daily_log_excess']=paired_lower(curve,matched,repeats)
                blocks[name]=models
            late=blocks['late']['stress']
            passed=(late['total_return']>0 and late['max_drawdown']>=-.25
                    and late['adjusted_lower_mean_daily_log_excess']>0)
            records.append(dict(symbol=symbol,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                blocks=blocks,gate_pass=passed))
        report['rules'][rule]=dict(assets=records,gate_pass=all(r['gate_pass'] for r in records))
    report['protocol_sha256']=hashlib.sha256(Path(__file__).with_name('PROTOCOL.md').read_bytes()).hexdigest()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache',type=Path,default=Path(__file__).resolve().parents[1]/'research_new_methods_20261007'/'public_daily')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise SystemExit('Refusing to overwrite an existing research result')
    result=screen(args.cache)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    for rule,data in result['rules'].items():
        print(rule,'GATE:',data['gate_pass'])
        for asset in data['assets']:
            s=asset['blocks']['late']['stress']
            print(asset['symbol'],json.dumps(s))
