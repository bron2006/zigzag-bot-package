"""Three predeclared exploratory alternatives, offline only."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
import json
import hashlib
from pathlib import Path
from compare import load_history,detect,NY,bounds,replay,summarize


def continuation(bars):
    detect(bars)
    groups=defaultdict(list)
    for b in bars:groups[datetime.fromtimestamp(b['ts'],NY).date()].append(b)
    out=[]
    for day,group in sorted(groups.items()):
        start,end,midnight=bounds(day)
        anchor=[b for b in group if start<=b['ts']<end]
        if [b['ts'] for b in anchor]!=list(range(start,end,300)):continue
        high=max(b['High'] for b in anchor);low=min(b['Low'] for b in anchor)
        if high<=low:continue
        expected=end
        for b in group:
            if b['ts']<end:continue
            if b['ts']!=expected:break
            expected=b['ts']+300
            side=1 if b['Close']>high else -1 if b['Close']<low else 0
            if side and expected<midnight:
                out.append(dict(ts=expected,ny_date=day.isoformat(),side=side,stop=b['Low'] if side==1 else b['High']))
                break
    return out


def regimes(bars):
    groups=defaultdict(list)
    for b in bars:groups[b['ts']//3600].append(b)
    fast=slow=None;previous=None;count=0;out=[]
    for hour,group in sorted(groups.items()):
        start=hour*3600
        if [b['ts'] for b in group]!=list(range(start,start+3600,300)):continue
        c=group[-1]['Close']
        if previous is None or start!=previous+3600:fast=slow=c;count=1
        else:fast+=2/21*(c-fast);slow+=2/51*(c-slow);count+=1
        if count>=50:out.append((start+3600,1 if fast>slow else -1 if fast<slow else 0))
        previous=start
    return out


def aligned(intents,trend):
    times=[t[0] for t in trend];out=[]
    for intent in intents:
        i=bisect_right(times,intent['ts'])-1
        if i>=0 and intent['ts']-times[i]<3600 and trend[i][1]==intent['side']:out.append(intent)
    return out


def main():
    folder=Path(__file__).parent
    report=dict(protocol_sha256=hashlib.sha256((folder/'ALTERNATIVES.md').read_bytes()).hexdigest(),reused_history=True,proven_edge=False,arms=[],gates={})
    for pair in ('EURUSD','GBPUSD','USDJPY'):
        frame,_=load_history(pair);bars=frame.to_dict('records');trend=regimes(bars);breaks=continuation(bars)
        arms=[('continue',breaks),('continue_H1',aligned(breaks,trend)),('reclaim_H1',aligned(detect(bars)['intents'],trend))]
        for arm,intents in arms:
            checks=[]
            for scenario in ('base','stress'):
                cost=(.02 if pair=='USDJPY' else .0002)*(2 if scenario=='stress' else 1)
                rows,_=replay(bars,intents,cost)
                for phase in ('early','late'):
                    selected=[r for r in rows if (r['intent']['ts']<1767225600)==(phase=='early')]
                    row=dict(pair=pair,arm=arm,scenario=scenario,phase=phase,**summarize(selected))
                    report['arms'].append(row);print(json.dumps(row),flush=True)
                    if scenario=='stress':checks.append(row)
            report['gates'][pair+'/'+arm]=all(r['mean_net_R'] is not None and r['mean_net_R']>0 and r['simultaneous_95_ci'] and r['simultaneous_95_ci'][0]>0 and not r['statuses'].get('unknown') for r in checks) and checks[-1]['closed']>=100
    (folder/'alternatives_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'])),flush=True)


if __name__=='__main__':main()
