"""Fixed relative ranking, with actual funding and collateral stress."""
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
from .screen import FOLDER,SYMBOLS,START,END,validate_raw
from local_trend_bot.strategy import DAY


def label(ts):
    return datetime.fromtimestamp(ts/1000,timezone.utc).strftime('%Y-%m')


def ranking(prices,month):
    year,number=map(int,month.split('-'))
    ordinal=year*12+number-1
    date=lambda n:f'{n//12:04d}-{n%12+1:02d}'
    asof=date(ordinal-2)
    previous=date(ordinal-14)
    returns={s:prices[s][asof]/prices[s][previous]-1 for s in SYMBOLS}
    direction=1 if returns['BTCUSDT']>returns['ETHUSDT'] else -1 if returns['BTCUSDT']<returns['ETHUSDT'] else 0
    return direction,asof


def leg(bars,marks,rates,direction,notional,fee):
    if direction not in (-1,1) or notional<=0 or not 0<=fee<1:
        raise ValueError('Invalid leg parameters')
    start,end=bars[0][0],bars[-1][0]+DAY-1
    entry=float(bars[0][1])
    qty=notional/entry
    selected=[r for r in rates if start<int(r['fundingTime'])<=end]
    flows=defaultdict(list)
    for r in selected:
        flows[int(r['fundingTime'])//DAY*DAY].append(-direction*qty*float(r['markPrice'])*float(r['fundingRate']))
    cash=notional-notional*fee
    credit=0.
    violations=[]
    minimum=float('inf')
    curve=[]
    for bar,mark in zip(bars,marks,strict=True):
        if bar[0]!=mark[0]:raise ValueError('Unaligned mark')
        today=flows[bar[0]]
        extreme=float(mark[3 if direction==1 else 2])
        worst=cash+credit+sum(v for v in today if v<0)+direction*qty*(extreme-entry)
        ratio=worst/(qty*extreme)
        minimum=min(minimum,ratio)
        if ratio<.10:violations.append(bar[0])
        credit+=sum(today)
        curve.append(cash+credit+direction*qty*(float(mark[4])-entry))
    gross=direction*qty*(float(bars[-1][4])-entry)
    costs=notional*fee+qty*float(bars[-1][4])*fee
    end_cash=notional+gross+credit-costs
    curve[-1]=end_cash
    return dict(end_cash=end_cash,price_cash=gross,funding_cash=credit,cost_cash=costs,
                min_margin_ratio=minimum,violation_days=violations),curve


def paired_lower(excess):
    rng=random.Random(20261008)
    values=[]
    n=len(excess)
    for _ in range(10000):
        sample=[]
        while len(sample)<n:
            start=rng.randrange(n)
            sample.extend(excess[(start+j)%n] for j in range(3))
        values.append(sum(sample[:n])/n)
    values.sort()
    return values[250]


def run():
    raw={s:json.loads((FOLDER/(s+'_raw.json')).read_text()) for s in SYMBOLS}
    prices={}
    for s in SYMBOLS:
        validate_raw(raw[s])
        spot=json.loads((FOLDER.parent/'research_new_methods_20261007'/'public_daily'/(s+'_1d.json')).read_text())['rows']
        prices[s]={label(r[0]):float(r[4]) for r in spot}
    indices=defaultdict(list)
    for i,r in enumerate(raw['BTCUSDT']['future']):indices[label(r[0])].append(i)
    report=dict(proven_edge=False,protocol_sha256=hashlib.sha256((FOLDER/'RELATIVE_PROTOCOL.md').read_bytes()).hexdigest(),
                raw_hashes={s:hashlib.sha256((FOLDER/(s+'_raw.json')).read_bytes()).hexdigest() for s in SYMBOLS},scenarios={})
    for scenario,fee in [('base',.001),('stress',.002)]:
        blocks={}
        for block in ('early','late'):
            models={}
            for model in ('rank','opposite','always_btc'):
                nav=1000.
                months=[]
                curve=[]
                for month,ix in indices.items():
                    if (month<'2025')!=(block=='early'):continue
                    direction,asof=ranking(prices,month)
                    if model=='opposite':direction=-direction
                    if model=='always_btc':direction=1
                    if not direction:
                        months.append(dict(month=month,asof=asof,direction=0,net_return=0,end_nav=nav,legs=[]))
                        curve.extend([nav]*len(ix));continue
                    legs=[]
                    daily=[]
                    for s,d in [('BTCUSDT',direction),('ETHUSDT',-direction)]:
                        bars=[raw[s]['future'][i] for i in ix]
                        marks=[raw[s]['mark'][i] for i in ix]
                        result,values=leg(bars,marks,raw[s]['rates'],d,nav*.5,fee)
                        result['symbol']=s
                        legs.append(result);daily.append(values)
                    end_nav=sum(r['end_cash'] for r in legs)
                    if end_nav<=0:raise ValueError('Potential insolvency')
                    months.append(dict(month=month,asof=asof,direction=direction,net_return=end_nav/nav-1,end_nav=end_nav,legs=legs))
                    nav=end_nav
                    curve.extend(a+b for a,b in zip(*daily))
                peak=1000.
                dd=0.
                for value in curve:peak=max(peak,value);dd=min(dd,value/peak-1)
                violations=sum(len(leg['violation_days']) for m in months for leg in m['legs'])
                models[model]=dict(potential_end_nav=nav,potential_return=nav/1000-1,violation_days=violations,
                                   modeled_end_nav=nav if not violations else None,daily_close_drawdown=dd,months=months)
            excess=[math.log1p(a['net_return'])-math.log1p(b['net_return']) for a,b in zip(models['rank']['months'],models['always_btc']['months'])]
            lower=paired_lower(excess)
            blocks[block]=dict(models=models,lower_mean_log_excess_vs_always_btc=lower,
                               gate_pass=models['rank']['potential_return']>0 and models['rank']['violation_days']==0
                               and models['always_btc']['violation_days']==0 and lower>0)
        report['scenarios'][scenario]=blocks
    output=FOLDER/'relative_results_v1.json'
    if output.exists():raise ValueError('Refusing to overwrite results')
    output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    for scenario,blocks in report['scenarios'].items():
        print(scenario,'late gate',blocks['late']['gate_pass'],'lower excess',blocks['late']['lower_mean_log_excess_vs_always_btc'])
        for model,result in blocks['late']['models'].items():print(model,{k:v for k,v in result.items() if k!='months'})


if __name__=='__main__':run()
