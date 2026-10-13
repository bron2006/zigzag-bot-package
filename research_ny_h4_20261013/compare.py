"""Cached-only diagnostic. No credentials, config, database or network."""
from bisect import bisect_left
from collections import defaultdict,Counter
from datetime import datetime
from pathlib import Path
import hashlib
import json
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from comparative_screen import load_history
from ny_h4_reclaim import NY,bounds,detect
from paper_cfd import simulate_stop_trade


def repeated(bars):
    # Existing detector validates order, times and OHLC; same anchor contract.
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
        side=0;extreme=None;expected=end;sequence=0
        for b in group:
            if b['ts']<end:continue
            if b['ts']!=expected:break
            expected=b['ts']+300
            if not side:
                if b['Close']<low:side=1;extreme=b['Low']
                elif b['Close']>high:side=-1;extreme=b['High']
                continue
            extreme=min(extreme,b['Low']) if side==1 else max(extreme,b['High'])
            if (b['Close']>low if side==1 else b['Close']<high) and expected<midnight:
                sequence+=1
                out.append(dict(ts=expected,ny_date=day.isoformat(),side=side,stop=extreme,sequence=sequence))
                side=0;extreme=None
    return out


def replay(bars,intents,cost,nonoverlap=False):
    times=[b['ts'] for b in bars];results=[];blocked=0;skips=0
    for intent in intents:
        ts=intent['ts']
        if nonoverlap and ts<blocked:skips+=1;continue
        i=bisect_left(times,ts);j=bisect_left(times,ts+6*86400)
        path=bars[i:j]
        if not path or path[0]['ts']!=ts:
            result=dict(status='unknown',reason='missing_entry')
        else:
            distance=intent['side']*(path[0]['Open']-intent['stop'])
            if distance<=0 or path[0]['Open']+intent['side']*2*distance<=0:
                result=dict(status='skipped',reason='entry_gap_invalid_stop')
            else:
                result=simulate_stop_trade(path,0,intent['side'],distance,2)
                if result['status']=='closed' and result['reason']=='session_end':
                    result=dict(status='unknown',reason='unfinished_at_coverage_end')
                elif result['status']=='closed':
                    result['net_R']=(result['gross_points']-cost)/(distance+cost)
        if result['status']=='unknown':blocked=ts+6*86400
        elif result['status']=='closed':blocked=result['exit_ts']
        results.append(dict(intent=intent,**result))
    return results,skips


def summarize(rows):
    closed=[r for r in rows if r['status']=='closed'];v=[r['net_R'] for r in closed]
    gains=sum(x for x in v if x>0);loss=-sum(x for x in v if x<0)
    days=sorted({r['intent']['ny_date'] for r in rows});daily=defaultdict(list)
    for r in closed:daily[r['intent']['ny_date']].append(r['net_R'])
    ci=None
    if len(days)>=20 and v:
        sums=np.array([sum(daily[d]) for d in days]);counts=np.array([len(daily[d]) for d in days])
        rng=np.random.default_rng(20261013);starts=rng.integers(0,len(days),(6000,(len(days)+9)//10))
        idx=((starts[:,:,None]+np.arange(10))%len(days)).reshape(6000,-1)[:,:len(days)]
        n=counts[idx].sum(axis=1);samples=sums[idx].sum(axis=1)[n>0]/n[n>0]
        ci=np.quantile(samples,[.025/36,1-.025/36]).tolist()
    return dict(setups=len(rows),statuses=dict(Counter(r['status'] for r in rows)),closed=len(v),
                wins=sum(x>0 for x in v),mean_net_R=sum(v)/len(v) if v else None,
                profit_factor=gains/loss if loss else None,simultaneous_95_ci=ci)


def main():
    folder=Path(__file__).parent
    report=dict(protocol_sha256=hashlib.sha256((folder/'PROTOCOL.md').read_bytes()).hexdigest(),
                reused_history=True,real_orders=False,arms=[],gates={})
    for pair in ('EURUSD','GBPUSD','USDJPY'):
        frame,hashes=load_history(pair);bars=frame.to_dict('records')
        single=detect(bars)['intents'];multi=repeated(bars)
        first={r['ny_date']:r for r in multi if r['sequence']==1}
        assert all((r['ts'],r['side'],r['stop'])==(first[r['ny_date']]['ts'],first[r['ny_date']]['side'],first[r['ny_date']]['stop']) for r in single)
        assert len(first)==len(single)
        report.setdefault('source_hashes',{})[pair]=hashes
        print(json.dumps(dict(pair=pair,single=len(single),repeated=len(multi))),flush=True)
        for arm,intents,nonoverlap in [('first',single,False),('repeat_independent',multi,False),('repeat_nonoverlap',multi,True)]:
            checks=[]
            for scenario in ('base','stress'):
                cost=(.02 if pair=='USDJPY' else .0002)*(2 if scenario=='stress' else 1)
                rows,skips=replay(bars,intents,cost,nonoverlap)
                for phase in ('early','late'):
                    selected=[r for r in rows if (r['intent']['ts']<1767225600)==(phase=='early')]
                    row=dict(pair=pair,arm=arm,scenario=scenario,phase=phase,**summarize(selected))
                    row['overlap_or_quarantine_skips_full_period']=skips
                    report['arms'].append(row);print(json.dumps(row),flush=True)
                    if scenario=='stress':checks.append(row)
            report['gates'][pair+'/'+arm]=all(r['mean_net_R'] is not None and r['mean_net_R']>0 and r['simultaneous_95_ci'] and r['simultaneous_95_ci'][0]>0 and not r['statuses'].get('unknown') for r in checks) and checks[-1]['closed']>=100
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'])),flush=True)


if __name__=='__main__':main()
