"""Offline structural-stop screen, immutable old stats and no order path."""
from collections import Counter,defaultdict
from datetime import date,timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_nasdaq_pullback_20261010'))
from screen import load_history,session_timestamps,HOLIDAYS,EARLY
from session_reclaim import setup,entry_terms
from paper_cfd import size_position,simulate_stop_trade,net_usd


def replay(bars,cost,spec):
    lookup={b['ts']:i for i,b in enumerate(bars)}
    balance=Decimal('1000.00')
    peak=balance
    dd=0.
    years=defaultdict(lambda:dict(net=Decimal('0'),trades=0,wins=0,losses=0))
    reasons=Counter()
    journal=[]
    day=date(2024,1,1)
    while day<date(2026,10,8):
        current_day=day
        day+=timedelta(days=1)
        if current_day.weekday()>=5 or current_day.isoformat() in HOLIDAYS|EARLY: continue
        year=years[str(current_day.year)]
        times=session_timestamps(current_day)
        previous=current_day-timedelta(days=1)
        while previous.weekday()>=5 or previous.isoformat() in HOLIDAYS:
            previous-=timedelta(days=1)
        prevtimes=session_timestamps(previous)
        if previous.isoformat() in EARLY or (current_day-previous).days>5:
            reasons['previous_session_not_full']+=1
            continue
        if not all(t in lookup for t in times+prevtimes):
            reasons['unknown_session_coverage']+=1
            continue
        previous_bars=[bars[lookup[t]] for t in prevtimes]
        high=max(b['High'] for b in previous_bars)
        low=min(b['Low'] for b in previous_bars)
        intent=None
        for offset in range(2,65):
            i=lookup[times[offset]]
            if i<14 or bars[i]['ts']-bars[i-14]['ts']!=4200: continue
            atr=sum(max(bars[j]['High']-bars[j]['Low'],abs(bars[j]['High']-bars[j-1]['Close']),
                        abs(bars[j]['Low']-bars[j-1]['Close'])) for j in range(i-13,i+1))/14
            if atr<=0: continue
            intent=setup(bars[i],high,low,atr)
            if intent is not None: break
        if intent is None:
            reasons['no_setup']+=1
            continue
        entry_index=i+1
        price=bars[entry_index]['Open']
        terms=entry_terms(intent,price,cost)
        if terms is None:
            reasons['entry_gap_or_insufficient_net_reward']+=1
            continue
        if balance<=0:
            reasons['capital_exhausted']+=1
            continue
        units=size_position(float(balance),price,terms['risk'],cost,
                            minimum=int(spec['minVolume'])/100,step=int(spec['stepVolume'])/100,
                            maximum=int(spec['maxVolume'])/100,quote_currency='USD')
        if not units:
            reasons['below_minimum_size']+=1
            continue
        trade=simulate_stop_trade(bars[entry_index:lookup[times[-1]]+1],0,
                                  terms['direction'],terms['risk'],terms['target_multiple'])
        if trade['status']!='closed':
            reasons['unknown_trade_path']+=1
            continue
        pnl=net_usd(units,trade['gross_points'],cost)
        balance+=pnl
        peak=max(peak,balance)
        dd=max(dd,float((peak-balance)/peak))
        year['net']+=pnl
        year['trades']+=1
        year['wins']+=pnl>0
        year['losses']+=pnl<0
        reasons[trade['reason']]+=1
        journal.append(dict(day=current_day.isoformat(),entry_ts=trade['entry_ts'],exit_ts=trade['exit_ts'],
                            direction=trade['direction'],entry=trade['entry'],stop=trade['stop'],
                            target=trade['target'],exit=trade['exit'],units=units,net_usd=str(pnl),
                            balance_usd=str(balance),reason=trade['reason'],ambiguous=trade['ambiguous']))
    return dict(initial_usd='1000.00',balance_usd=str(balance),net_usd=str(balance-1000),
                realized_drawdown_pct=dd*100,reasons=dict(reasons),
                years={y:{k:str(v) if isinstance(v,Decimal) else v for k,v in row.items()} for y,row in years.items()},journal=journal)


def main():
    bars,hashes,_=load_history('M5')
    if any(b['ts']%300 for b in bars): raise ValueError('unaligned_M5')
    metadata_path=ROOT/'research_nasdaq_pullback_20261010'/'cache'/'metadata.json'
    meta=json.loads(metadata_path.read_text(encoding='utf-8'))
    assert meta['name']=='USTEC' and meta['confirmed_demo']
    report=dict(retrospective=True,proven_edge=False,production_activated=False,
                executable=False,inputs_sha256=hashes,
                metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                protocol_sha256=hashlib.sha256(Path(__file__).with_name('RECLAIM_PROTOCOL.md').read_bytes()).hexdigest(),arms=[])
    for scenario,cost in [('base',2),('stress',5)]:
        row=dict(scenario=scenario,conditional_rt_points=cost,**replay(bars,cost,meta['specification']))
        report['arms'].append(row)
        print(json.dumps({k:v for k,v in row.items() if k!='journal'}),flush=True)
    stress=report['arms'][1]
    report['cheap_screen_pass']=(stress['years']['2026']['trades']>=100 and
        all(Decimal(y['net'])>0 for y in stress['years'].values()) and
        not stress['reasons'].get('unknown_session_coverage',0))
    Path(__file__).with_name('reclaim_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(cheap_screen_pass=report['cheap_screen_pass'],production_activated=False)))


if __name__=='__main__': main()
