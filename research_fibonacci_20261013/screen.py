"""Causal confirmed-H1 swing Fibonacci hypothesis. Cached-only, no orders."""
from bisect import bisect_left
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research_ny_h4_20261013'))
from compare import load_history,summarize
from paper_cfd import simulate_stop_trade

ZONES={'fibo_50_618':(.5,.618),'control_shallow':(.382,.5),'control_deep':(.618,.736)}


def validate(bars):
    previous=None
    for b in bars:
        if not isinstance(b['ts'],(int,float)) or not math.isfinite(b['ts']) or b['ts']%300 or (previous is not None and b['ts']<=previous):raise ValueError('invalid_bar_time')
        o,h,l,c=[b[k] for k in ('Open','High','Low','Close')]
        if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:raise ValueError('invalid_OHLC')
        previous=b['ts']


def anchors(bars):
    validate(bars)
    groups=defaultdict(list)
    for b in bars:groups[b['ts']//3600].append(b)
    history=[];highs=[];lows=[];previous=None;old_key=None;known=None;events=[]
    for hour,group in sorted(groups.items()):
        start=hour*3600
        if [b['ts'] for b in group]!=list(range(start,start+3600,300)):continue
        if previous is None or start!=previous+3600:
            history=[];highs=[];lows=[];old_key=None
        history.append(dict(ts=start,High=max(b['High'] for b in group),Low=min(b['Low'] for b in group)))
        history=history[-5:];previous=start;available=start+3600
        if len(history)==5:
            p=history[2];neighbors=history[:2]+history[3:]
            if all(p['High']>n['High'] for n in neighbors):highs.append((p['ts'],p['High']));highs=highs[-8:]
            if all(p['Low']<n['Low'] for n in neighbors):lows.append((p['ts'],p['Low']));lows=lows[-8:]
        anchor=None
        if len(highs)>=2 and len(lows)>=2:
            side=1 if highs[-1][1]>highs[-2][1] and lows[-1][1]>lows[-2][1] else -1 if highs[-1][1]<highs[-2][1] and lows[-1][1]<lows[-2][1] else 0
            terminal=highs[-1] if side==1 else lows[-1] if side==-1 else None
            origins=[p for p in (lows if side==1 else highs) if terminal and p[0]<terminal[0]]
            if origins:
                origin=origins[-1];key=(side,origin[0],terminal[0])
                if side*(terminal[1]-origin[1])>0:
                    if key!=old_key:known=available
                    old_key=key
                    anchor=dict(key=key,side=side,origin=origin[1],target=terminal[1],known=known)
        if anchor is None:old_key=None
        events.append((available,anchor))
    return events


def detect(bars,zone='fibo_50_618',pip=.0001):
    if zone not in ZONES:raise ValueError('unknown_zone')
    events=anchors(bars);index=0;anchor=None;last_event=None;key=None;touched=False;used=set();out=[];previous=None
    shallow,deep=ZONES[zone]
    for b in bars:
        while index<len(events) and events[index][0]<=b['ts']:
            last_event,anchor=events[index];index+=1
        if previous is None or b['ts']-previous['ts']!=300:touched=False
        if anchor is None or last_event is None or b['ts']-last_event>=3600:
            touched=False;key=None;previous=b;continue
        if key!=anchor['key']:key=anchor['key'];touched=False
        if key in used or b['ts']<anchor['known']:previous=b;continue
        side=anchor['side'];target=anchor['target'];distance=side*(target-anchor['origin'])
        near=target-side*shallow*distance;far=target-side*deep*distance
        stop=far-side*pip;lo=min(near,far);hi=max(near,far)
        if (b['Low']<=stop if side==1 else b['High']>=stop):
            used.add(key);touched=False;previous=b;continue
        touched=touched or (b['Low']<=hi and b['High']>=lo)
        confirmed=previous is not None and b['ts']-previous['ts']==300 and (b['Close']>b['Open'] and b['Close']>previous['High'] if side==1 else b['Close']<b['Open'] and b['Close']<previous['Low'])
        if touched and confirmed and side*(target-b['Close'])>0:
            out.append(dict(ts=b['ts']+300,ny_date=datetime.fromtimestamp(b['ts'],timezone.utc).date().isoformat(),
                side=side,stop=stop,target=target,origin=anchor['origin'],anchor_known=anchor['known'],anchor_key=key,zone=zone))
            used.add(key);touched=False
        previous=b
    return out


def replay(bars,intents,cost):
    times=[b['ts'] for b in bars];out=[]
    for intent in intents:
        i=bisect_left(times,intent['ts']);j=bisect_left(times,intent['ts']+6*86400);path=bars[i:j]
        if not path or path[0]['ts']!=intent['ts']:result=dict(status='unknown',reason='missing_entry')
        else:
            entry=path[0]['Open'];distance=intent['side']*(entry-intent['stop']);reward=intent['side']*(intent['target']-entry)
            if distance<=0 or reward<=0:result=dict(status='skipped',reason='entry_gap_invalid_geometry')
            else:
                result=simulate_stop_trade(path,0,intent['side'],distance,reward/distance)
                if result['status']=='closed' and result['reason']=='session_end':result=dict(status='unknown',reason='unfinished_at_coverage_end')
                elif result['status']=='closed':result['net_R']=(result['gross_points']-cost)/(distance+cost)
        out.append(dict(intent=intent,**result))
    return out


def main():
    folder=Path(__file__).parent
    report=dict(protocol_sha256=hashlib.sha256((folder/'PROTOCOL.md').read_bytes()).hexdigest(),reused_history=True,proven_edge=False,arms=[],gates={})
    for pair in ('EURUSD','GBPUSD','USDJPY'):
        frame,hashes=load_history(pair);bars=frame.to_dict('records');pip=.01 if pair=='USDJPY' else .0001
        report.setdefault('source_hashes',{})[pair]=hashes
        for zone in ZONES:
            intents=detect(bars,zone,pip);checks=[]
            for scenario in ('base','stress'):
                cost=pip*(2 if scenario=='base' else 4);rows=replay(bars,intents,cost)
                for phase in ('early','late'):
                    selected=[r for r in rows if (r['intent']['ts']<1767225600)==(phase=='early')]
                    row=dict(pair=pair,zone=zone,scenario=scenario,phase=phase,**summarize(selected));report['arms'].append(row)
                    print(json.dumps(row),flush=True)
                    if scenario=='stress':checks.append(row)
            report['gates'][pair+'/'+zone]=all(r['mean_net_R'] is not None and r['mean_net_R']>0 and r['simultaneous_95_ci'] and r['simultaneous_95_ci'][0]>0 and not r['statuses'].get('unknown') for r in checks) and checks[-1]['closed']>=100
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'])),flush=True)


if __name__=='__main__':main()
