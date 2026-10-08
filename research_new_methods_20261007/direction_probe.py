"""Offline paired direction diagnosis of the EXISTING bot's cached signals."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import gzip
import hashlib
import heapq
import itertools
import json
import math
from pathlib import Path
import random

FOLDER=Path(__file__).resolve().parent


def replay_pair(order,streams,fee,slippage=0):
    start=(order['signal_ts']+1)*1000
    end=int(datetime.fromisoformat(order['day']+'T16:00:00+00:00').timestamp()*1000)
    risk=order['limit']-order['stop']
    if not math.isfinite(risk) or risk<=0:raise ValueError('Invalid fixed risk')
    if not streams['BID'] or not streams['ASK']:return dict(status='unknown',reason='missing_quotes')
    quotes={}
    entries=None
    outcomes={}
    last=start
    # Streams sorted independently; merge without reordering equal-time quotes.
    ticks=heapq.merge(*([(r['timestamp_ms'],side,r['price']) for r in streams[side]] for side in ('BID','ASK')))
    for ts,group in itertools.groupby(ticks,key=lambda t:t[0]):
        grouped=list(group)
        if ts>=end:break
        if ts>=start and ts-max(last,start)>120000:
            return dict(status='unknown',reason='quote_gap')
        last=max(last,ts)
        prices=defaultdict(list)
        for _,side,price in grouped:
            if not math.isfinite(price) or price<=0:raise ValueError('Invalid quote')
            prices[side].append(price)
        for side,values in prices.items():
            quotes[side]=(min(values) if side=='BID' else max(values),ts)
        if ts<start:continue
        if entries is None:
            if 'ASK' not in prices or quotes['ASK'][0]>order['limit']:continue
            if 'BID' not in quotes or ts-quotes['BID'][1]>15000 or quotes['BID'][0]>quotes['ASK'][0]:
                return dict(status='unknown',reason='invalid_quote_at_common_entry')
            entries={'long':quotes['ASK'][0],'short':quotes['BID'][0]}
            fill=ts
        for name,direction,side in [('long',1,'BID'),('short',-1,'ASK')]:
            if name in outcomes:continue
            if side not in prices and ts!=fill:continue
            if side not in quotes or ts-quotes[side][1]>15000:continue
            value=quotes[side][0]
            entry=entries[name]
            signed=direction*(value-entry)
            reason=None
            if signed<=-risk:reason='STOP'
            elif signed>=risk:
                reason='TARGET'
                value=entry+direction*risk
            if reason:
                outcomes[name]=dict(r=(direction*(value-entry)-fee-slippage)/risk,outcome=reason,entry=entry,exit=value,fill_ms=fill,exit_ms=ts)
        if len(outcomes)==2:return dict(status='paired',**outcomes)
    if entries is None:
        if any(side not in quotes or end-quotes[side][1]>15000 for side in ('ASK','BID')):
            return dict(status='unknown',reason='stale_unfilled_end')
        return dict(status='unfilled')
    for name,direction,side in [('long',1,'BID'),('short',-1,'ASK')]:
        if name in outcomes:continue
        if side not in quotes or end-quotes[side][1]>15000:
            return dict(status='unknown',reason='stale_exit_side',known_arms=outcomes)
        value=quotes[side][0]
        outcomes[name]=dict(r=(direction*(value-entries[name])-fee-slippage)/risk,outcome='SESSION_END',entry=entries[name],exit=value,fill_ms=fill,exit_ms=end)
    return dict(status='paired',**outcomes)


def atr_before(raw,day,signal):
    start=int(datetime.fromisoformat(day+'T08:00:00+00:00').timestamp())
    past=[]
    for b in raw['raw_trendbars']:
        ts=int(b['utcTimestampInMinutes'])*60
        if start<=ts and ts+300<=signal:
            low=int(b['low'])/100000
            past.append((ts,low+int(b.get('deltaHigh',0))/100000,low,low+int(b.get('deltaClose',0))/100000))
    past.sort()
    if len(past)<15:raise ValueError('ATR history too short')
    if any(b[0]-a[0]!=300 for a,b in zip(past,past[1:])):raise ValueError('ATR history gap')
    true=[max(row[1]-row[2],abs(row[1]-past[i-1][3]),abs(row[2]-past[i-1][3])) for i,row in enumerate(past) if i]
    return sum(true[-14:])/14


def summary(records):
    result=dict(statuses=dict(Counter(r['status'] for r in records)))
    paired=[r for r in records if r['status']=='paired']
    result['paired']=len(paired)
    if not paired:return result
    days=defaultdict(list)
    for r in paired:days[r['day']].append(r)
    names=sorted(days)
    rng=random.Random(20261009)
    draws={'long':[],'short':[],'difference':[]}
    totals={day:(len(items),sum(r['long']['r'] for r in items),sum(r['short']['r'] for r in items)) for day,items in days.items()}
    for _ in range(10000):
        sample=[totals[rng.choice(names)] for _ in names]
        count=sum(r[0] for r in sample)
        a,b=sum(r[1] for r in sample)/count,sum(r[2] for r in sample)/count
        draws['long'].append(a);draws['short'].append(b);draws['difference'].append(b-a)
    for side in ('long','short'):
        values=[r[side]['r'] for r in paired]
        gains=sum(max(v,0) for v in values)
        losses=-sum(min(v,0) for v in values)
        bounds=sorted(draws[side])
        result[side]=dict(mean_r=sum(values)/len(values),pf=gains/losses if losses else None,
                          total_r=sum(values),mean_r_95ci=[bounds[250],bounds[9750]],
                          outcomes=dict(Counter(r[side]['outcome'] for r in paired)))
    bounds=sorted(draws['difference'])
    result['paired_short_minus_long_95ci']=[bounds[250],bounds[9750]]
    return result


def run():
    output=FOLDER/'direction_probe_v1.json'
    if output.exists():raise ValueError('Refusing to overwrite prior result')
    orders=[r for r in json.loads((FOLDER/'vwap_replay_results.json').read_text())['records'] if r['units']=='literal' and r['stress']==1]
    raw={}
    records=[]
    hashes={}
    for index,order in enumerate(orders):
        symbol=order['symbol']
        if symbol not in raw:raw[symbol]=json.loads((FOLDER/'vwap_replay_m5'/(symbol+'.json')).read_text())
        path=FOLDER/'vwap_replay_ticks'/f"{order['day']}_{symbol}.json.gz"
        with gzip.open(path,'rt',encoding='utf-8') as stream:data=json.load(stream)
        if not data['complete_pages'] or data['start_ms']!=order['signal_ts']*1000-60000:
            raise ValueError('Cache does not match fixed protocol')
        for rows in data['streams'].values():
            times=[r['timestamp_ms'] for r in rows]
            if times!=sorted(times):raise ValueError('Unordered tick stream')
        hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        atr=atr_before(raw[symbol],order['day'],order['signal_ts'])
        for stress in (1,2):
            result=replay_pair(order,data['streams'],.02*atr*stress,.02*atr if stress==2 else 0)
            records.append(dict(day=order['day'],symbol=symbol,stress=stress,**result))
        if (index+1)%50==0:print('Processed',index+1,'/',len(orders),flush=True)
    scenarios={}
    for stress in (1,2):
        selected=[r for r in records if r['stress']==stress]
        scenarios[str(stress)]={name:summary(items) for name,items in [('all',selected),('early',[r for r in selected if r['day']<'2026-09-14']),('late',[r for r in selected if r['day']>='2026-09-14'])]}
    late=scenarios['2']['late']
    passed=bool(late.get('paired') and late['short']['pf'] is not None and late['short']['pf']>1 and late['short']['mean_r_95ci'][0]>0 and late['paired_short_minus_long_95ci'][0]>0)
    report=dict(gate_pass=passed,retrospective_not_new_oos=True,live_strategy_changed=False,scenarios=scenarios,
                records=records,quote_hashes=hashes,protocol_sha256=hashlib.sha256((FOLDER/'VWAP_DIRECTION_PROTOCOL.md').read_bytes()).hexdigest())
    output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gate_pass=passed,scenarios=scenarios),indent=2))


if __name__=='__main__':run()
