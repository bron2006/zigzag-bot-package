"""Offline source-inspired USTEC session test; never submits orders."""
from collections import Counter
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_nasdaq_pullback_20261010'))
from screen import load_history, session_timestamps, HOLIDAYS, EARLY, NY
from session_momentum import evaluate


def summarize(rows,arm):
    measured=[r for r in rows if r['status']=='measured']
    points=[(r['direction'] if arm=='predicted' else 1 if arm=='always_buy' else -1)*(r['exit']-r['entry']) for r in measured]
    wins=sum(p>0 for p in points)
    losses=sum(p<0 for p in points)
    return dict(scheduled=len(rows),statuses=dict(Counter(r['status'] for r in rows)),
                measured=len(points),wins=wins,losses=losses,refunds=len(points)-wins-losses,
                binary_accuracy=wins/(wins+losses) if wins+losses else None,
                binary_unit_pnl_80=.8*wins-losses,gross_points=sum(points),
                conditional_net_points_2=sum(points)-2*len(points),
                conditional_net_points_5=sum(points)-5*len(points))


def main():
    bars,hashes,_=load_history('M5')
    lookup={b['ts']:b for b in bars}
    rows=[]
    day=date(2024,1,1)
    while day<date(2026,10,8):
        if day.weekday()<5 and day.isoformat() not in HOLIDAYS|EARLY:
            previous=day-timedelta(days=1)
            while previous.weekday()>=5 or previous.isoformat() in HOLIDAYS:
                previous-=timedelta(days=1)
            close_hour=13 if previous.isoformat() in EARLY else 16
            previous_ts=int(datetime.combine(previous,time(close_hour-1,55),NY).timestamp())
            previous_close=lookup.get(previous_ts,{}).get('Close')
            row=evaluate(lookup,session_timestamps(day),previous_close)
            row.update(day=day.isoformat(),year=day.year)
            rows.append(row)
        day+=timedelta(days=1)
    report=dict(retrospective=True,executable=False,production_activated=False,proven_edge=False,
                inputs_sha256=hashes,
                protocol_sha256=hashlib.sha256(Path(__file__).with_name('SESSION_PROTOCOL.md').read_bytes()).hexdigest(),arms=[])
    for arm in ('predicted','always_buy','always_sell'):
        yearly={str(y):summarize([r for r in rows if r['year']==y],arm) for y in (2024,2025,2026)}
        result=dict(arm=arm,overall=summarize(rows,arm),yearly=yearly)
        report['arms'].append(result)
        print(json.dumps(result),flush=True)
    current=[r for r in rows if r['year']==2026 and r['status']=='measured']
    matrix=np.array([[r['direction']*(r['exit']-r['entry'])-5,
                      (r['direction']-1)*(r['exit']-r['entry']),
                      (r['direction']+1)*(r['exit']-r['entry'])] for r in current])
    rng=np.random.default_rng(20261012)
    n=len(matrix)
    blocks=rng.integers(0,n-4,size=(5000,(n+4)//5))
    indices=(blocks[:,:,None]+np.arange(5)).reshape(5000,-1)[:,:n]
    samples=matrix[indices].mean(axis=1)
    report['confirmation_lower_stress_and_excess']=list(map(float,np.quantile(samples,.05/172,axis=0)))
    predicted=report['arms'][0]
    report['cheap_screen_pass']=(n>=100 and
        all(s['conditional_net_points_5']>0 for s in predicted['yearly'].values()) and
        all(s['statuses'].get('unknown',0)==0 for s in predicted['yearly'].values()) and
        all(v>0 for v in report['confirmation_lower_stress_and_excess']))
    Path(__file__).with_name('session_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('confirmation_lower_stress_and_excess','cheap_screen_pass','production_activated')}))


if __name__=='__main__': main()
