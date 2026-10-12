"""Sequential finite USD paper accounts with SL/TP; no real-order path."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_nasdaq_pullback_20261010'))
from screen import load_history,session_timestamps,HOLIDAYS,EARLY
from transparent_signal import generate,RULES
from entry_rules import choose_entry
from paper_cfd import size_position,simulate_stop_trade,net_usd


def account(bars,intents,sessions,policy,cost,spec):
    lookup={b['ts']:i for i,b in enumerate(bars)}
    balance=Decimal('1000.00')
    peak=balance
    dd=0.
    reasons=Counter()
    years=defaultdict(lambda:dict(net=Decimal('0'),trades=0,wins=0,losses=0,ambiguous=0,unknown_sessions=0))
    journal=[]
    next_free=-float('inf')
    for day,times in sessions:
        year=years[str(day.year)]
        if not all(t in lookup for t in times):
            year['unknown_sessions']+=1
            continue
        for ts in times:
            if times[-1]+300-(ts+300)<=1800: break
            if ts+300<next_free: continue
            i=lookup[ts]
            intent=intents[i]
            if not intent['direction']: continue
            side,atr=intent['direction'],intent['atr']
            entry=choose_entry(bars,i,side,atr,policy)
            # A pending setup occupies time even when it later cancels; no
            # hindsight permission to accept another setup before cancellation.
            next_free=max(next_free,entry.get('decision_ts',ts+300))
            if entry['status']!='entered':
                reasons[entry.get('reason',entry['status'])]+=1
                continue
            if entry['ts'] not in times:
                reasons['entry_outside_session']+=1
                continue
            if balance<=0:
                reasons['capital_exhausted']+=1
                continue
            units=size_position(float(balance),entry['price'],atr,cost,
                                minimum=int(spec['minVolume'])/100,step=int(spec['stepVolume'])/100,
                                maximum=int(spec['maxVolume'])/100,quote_currency='USD')
            if not units:
                reasons['below_minimum_size']+=1
                continue
            # Position size fixed before inspecting any future stop/target path.
            remainder=bars[entry['index']:lookup[times[-1]]+1]
            trade=simulate_stop_trade(remainder,0,side,atr,1.5)
            if trade['status']!='closed':
                reasons['unknown_path']+=1
                next_free=times[-1]+300
                continue
            pnl=net_usd(units,trade['gross_points'],cost)
            balance+=pnl
            next_free=trade['exit_ts']
            peak=max(peak,balance)
            dd=max(dd,float((peak-balance)/peak))
            reasons[trade['reason']]+=1
            year['net']+=pnl
            year['trades']+=1
            year['wins']+=pnl>0
            year['losses']+=pnl<0
            year['ambiguous']+=trade['ambiguous']
            journal.append(dict(day=day.isoformat(),entry_ts=trade['entry_ts'],exit_ts=trade['exit_ts'],
                                direction=side,entry=trade['entry'],stop=trade['stop'],target=trade['target'],
                                exit=trade['exit'],units=units,net_usd=str(pnl),balance_usd=str(balance),reason=trade['reason']))
    return dict(initial_usd='1000.00',balance_usd=str(balance),net_usd=str(balance-1000),
                risk_fraction=.005,realized_balance_drawdown_pct=dd*100,
                reasons=dict(reasons),years={y:{k:str(v) if isinstance(v,Decimal) else v for k,v in row.items()}
                                           for y,row in sorted(years.items())},journal=journal)


def main():
    bars,hashes,_=load_history('M5')
    meta_path=ROOT/'research_nasdaq_pullback_20261010'/'cache'/'metadata.json'
    metadata=json.loads(meta_path.read_text(encoding='utf-8'))
    assert metadata['name']=='USTEC' and metadata['confirmed_demo']
    sessions=[]
    day=date(2024,1,1)
    while day<date(2026,10,8):
        if day.weekday()<5 and day.isoformat() not in HOLIDAYS|EARLY:
            sessions.append((day,session_timestamps(day)))
        day+=timedelta(days=1)
    report=dict(retrospective=True,proven_edge=False,executable=False,production_activated=False,
                ledger='USDquoted_CFD_conditional_SLTP_v1',inputs_sha256=hashes,
                metadata_sha256=hashlib.sha256(meta_path.read_bytes()).hexdigest(),
                protocol_sha256=hashlib.sha256(Path(__file__).with_name('CFD_PROTOCOL.md').read_bytes()).hexdigest(),arms=[])
    for rule in RULES:
        intents=generate(bars,rule)
        for policy in ('immediate','pullback_confirm'):
            for scenario,cost in [('base',2),('stress',5)]:
                result=dict(rule=rule,policy=policy,scenario=scenario,conditional_rt_points=cost,
                            **account(bars,intents,sessions,policy,cost,metadata['specification']))
                report['arms'].append(result)
                print(json.dumps({k:v for k,v in result.items() if k!='journal'}),flush=True)
    Path(__file__).with_name('cfd_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__': main()
