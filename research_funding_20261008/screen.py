"""Historical perpetual funding-carry screen; public data, never orders."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import urlopen
from local_trend_bot.strategy import DAY,validate

FOLDER=Path(__file__).resolve().parent
SYMBOLS=('BTCUSDT','ETHUSDT')
START=1704067200000
END=1790812800000  # 2026-10-01 UTC


def public(route,**params):
    if route not in ('fundingRate','klines','markPriceKlines'):
        raise ValueError('Only public data allowed')
    with urlopen('https://fapi.binance.com/fapi/v1/'+route+'?'+urlencode(params),timeout=12) as response:
        result=json.load(response)
    if not isinstance(result,list):raise ValueError('Invalid public response')
    return result


def fetch(symbol):
    path=FOLDER/(symbol+'_raw.json')
    if path.exists():raise ValueError('Refusing to overwrite raw cache')
    rates=[]
    cursor=START
    while cursor<END:
        batch=public('fundingRate',symbol=symbol,startTime=cursor,endTime=END-1,limit=1000)
        if not batch:break
        rates.extend(batch)
        next_cursor=int(batch[-1]['fundingTime'])+1
        if next_cursor<=cursor:raise ValueError('Non-advancing funding cursor')
        cursor=next_cursor
    future=public('klines',symbol=symbol,interval='1d',startTime=START,endTime=END-1,limit=1500)
    mark=public('markPriceKlines',symbol=symbol,interval='1d',startTime=START,endTime=END-1,limit=1500)
    record=dict(symbol=symbol,endpoint='https://fapi.binance.com',fetched_utc=datetime.now(timezone.utc).isoformat(),
                start_ms=START,end_exclusive_ms=END,rates=rates,future=future,mark=mark)
    validate_raw(record)
    path.write_text(json.dumps(record,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(symbol=symbol,rates=len(rates),days=len(future),cached=str(path))),flush=True)


def validate_raw(raw):
    expected=list(range(START,END,DAY))
    for name in ('future','mark'):
        validate(raw[name])
        if [r[0] for r in raw[name]]!=expected:raise ValueError('Missing daily prices')
    times=[]
    for r in raw['rates']:
        t=int(r['fundingTime'])
        rate=float(r['fundingRate'])
        mark=float(r['markPrice'])
        if not START<=t<END or not math.isfinite(rate) or not math.isfinite(mark) or mark<=0:
            raise ValueError('Missing/invalid funding price or rate')
        if r.get('symbol')!=raw['symbol']:raise ValueError('Wrong funding symbol')
        times.append(t)
    if not times or times!=sorted(set(times)):raise ValueError('Missing/duplicate funding timestamps')
    if times[0]-START>12*3600000 or END-times[-1]>12*3600000:
        raise ValueError('Incomplete funding bounds')
    if any(b-a>12*3600000 for a,b in zip(times,times[1:])):
        raise ValueError('Funding gap over12h; no synthetic payments inserted')


def month_simulation(spot,future,mark,rates,nav,spot_fee,future_fee):
    if not spot or len(spot)!=len(future) or len(spot)!=len(mark):raise ValueError('Unaligned month')
    if [r[0] for r in spot]!=[r[0] for r in future] or [r[0] for r in spot]!=[r[0] for r in mark]:
        raise ValueError('Unaligned prices')
    qty=nav*.5/float(spot[0][1])
    entry_perp=float(future[0][1])
    entry_cost=qty*(float(spot[0][1])*spot_fee+entry_perp*future_fee)
    collateral=nav*.5-entry_cost
    start=spot[0][0]
    finish=spot[-1][0]+DAY-1
    eligible=[r for r in rates if start<int(r['fundingTime'])<=finish]
    paid_before=0.
    min_ratio=float('inf')
    violations=[]
    daily_nav=[]
    for s,f,m in zip(spot,future,mark):
        day=s[0]
        today=[qty*float(r['markPrice'])*float(r['fundingRate']) for r in eligible if day<=int(r['fundingTime'])<day+DAY]
        high=float(m[2])
        worst_margin=collateral+paid_before+sum(v for v in today if v<0)+qty*(entry_perp-high)
        ratio=worst_margin/(qty*high)
        min_ratio=min(min_ratio,ratio)
        if ratio<.10:violations.append(day)
        paid_before+=sum(today)
        daily_nav.append(collateral+paid_before+qty*(entry_perp-float(m[4]))+qty*float(s[4]))
    funding=sum(qty*float(r['markPrice'])*float(r['fundingRate']) for r in eligible)
    basis=qty*(float(spot[-1][4])-float(spot[0][1])+entry_perp-float(future[-1][4]))
    exit_cost=qty*(float(spot[-1][4])*spot_fee+float(future[-1][4])*future_fee)
    cost=entry_cost+exit_cost
    end_nav=nav+funding+basis-cost
    if end_nav<=0:raise ValueError('Potential insolvency')
    daily_nav[-1]=end_nav
    return dict(start_nav=nav,end_nav=end_nav,net_return=end_nav/nav-1,funding_cash=funding,basis_cash=basis,
                costs_cash=cost,min_margin_stress_ratio=min_ratio,margin_violations=violations,
                funding_events=len(eligible),negative_funding_events=sum(float(r['fundingRate'])<0 for r in eligible)),daily_nav


def lower_ci(returns):
    values=[math.log1p(v) for v in returns]
    rng=random.Random(20261008)
    n=len(values)
    samples=[]
    for _ in range(10000):
        selected=[]
        while len(selected)<n:
            start=rng.randrange(n)
            selected.extend(values[(start+j)%n] for j in range(3))
        samples.append(sum(selected[:n])/n)
    samples.sort()
    return samples[250]


def analyze_symbol(symbol):
    path=FOLDER/(symbol+'_raw.json')
    raw=json.loads(path.read_text())
    validate_raw(raw)
    spot_path=FOLDER.parent/'research_new_methods_20261007'/'public_daily'/(symbol+'_1d.json')
    spot=[r for r in json.loads(spot_path.read_text())['rows'] if START<=r[0]<END]
    validate(spot)
    if [r[0] for r in spot]!=[r[0] for r in raw['future']]:raise ValueError('Spot cache missing dates')
    groups=defaultdict(list)
    for i,r in enumerate(spot):groups[datetime.fromtimestamp(r[0]/1000,timezone.utc).strftime('%Y-%m')].append(i)
    scenarios={}
    for label,multiplier in [('base',1),('stress',2)]:
        blocks={}
        for block,first in [('early','2024'),('late','2025')]:
            nav=1000.
            months=[]
            curve=[]
            for month,indices in groups.items():
                if (month<'2025')!=(block=='early'):continue
                selected=lambda rows:[rows[i] for i in indices]
                result,daily=month_simulation(selected(spot),selected(raw['future']),selected(raw['mark']),raw['rates'],nav,.0015*multiplier,.001*multiplier)
                result['month']=month
                months.append(result)
                nav=result['end_nav']
                curve.extend(daily)
            peak=1000.
            dd=0.
            for value in curve:
                peak=max(peak,value);dd=min(dd,value/peak-1)
            violations=sum(len(r['margin_violations']) for r in months)
            lower=lower_ci([m['net_return'] for m in months])
            blocks[block]=dict(potential_end_nav=nav,potential_return=nav/1000-1,
                              realizable_under_stress_model=not violations,
                              modeled_end_nav=nav if not violations else None,
                              daily_close_drawdown=dd,min_margin_stress_ratio=min(r['min_margin_stress_ratio'] for r in months),
                              violation_days=violations,lower_mean_monthly_log_return=lower,months=months,
                              gate_pass=(nav>1000 and not violations and lower>0))
        scenarios[label]=blocks
    return dict(symbol=symbol,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                spot_sha256=hashlib.sha256(spot_path.read_bytes()).hexdigest(),scenarios=scenarios)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['fetch','worker','analyze'])
    parser.add_argument('--symbol',choices=SYMBOLS)
    args=parser.parse_args()
    if args.mode=='worker':fetch(args.symbol)
    elif args.mode=='fetch':
        for symbol in SYMBOLS:
            if (FOLDER/(symbol+'_raw.json')).exists():continue
            subprocess.run([sys.executable,'-m','research_funding_20261008.screen','worker','--symbol',symbol],timeout=60,check=True)
    else:
        output=FOLDER/'results_v1.json'
        if output.exists():raise ValueError('Refusing to overwrite results')
        records=[analyze_symbol(s) for s in SYMBOLS]
        report=dict(proven_account_profit=False,gate_pass=all(r['scenarios']['stress']['late']['gate_pass'] for r in records),
                    protocol_sha256=hashlib.sha256((FOLDER/'PROTOCOL.md').read_bytes()).hexdigest(),results=records)
        output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        for r in records:
            for label,data in r['scenarios'].items():
                summary={k:v for k,v in data['late'].items() if k!='months'}
                print(r['symbol'],label,json.dumps(summary))
        print('BOTH_ASSETS_GATE:',report['gate_pass'])


if __name__=='__main__':main()
