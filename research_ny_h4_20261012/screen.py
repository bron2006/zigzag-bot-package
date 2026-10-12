"""Single frozen rule on cached broker history. No network, orders or account."""
from bisect import bisect_left
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from comparative_screen import load_history
from ny_h4_reclaim import detect
from forward_structure_research import outcome


def main():
    folder=Path(__file__).parent
    report=dict(protocol_sha256=hashlib.sha256((folder/'PROTOCOL.md').read_bytes()).hexdigest(),
                reused_history=True,proven_edge=False,account_simulation=False,arms=[])
    for pair in ('EURUSD','GBPUSD'):
        frame,hashes=load_history(pair)
        bars=frame.to_dict('records');times=frame.ts.tolist();pattern=detect(bars)
        print(json.dumps(dict(pair=pair,bars=len(bars),setups=len(pattern['intents']),
                              range_states=dict(Counter(s['status'] for s in pattern['states'])))),flush=True)
        report.setdefault('source_hashes',{})[pair]=hashes
        for scenario in ('base','stress'):
            results=[]
            for intent in pattern['intents']:
                i=bisect_left(times,intent['ts']);j=bisect_left(times,intent['ts']+6*86400)
                result=outcome(intent,bars[i:j],times[-1]+300,scenario)
                if result['status']=='pending':
                    result=dict(result,status='unknown',reason='coverage_limit_or_end_of_history')
                results.append(dict(intent=intent,**result))
            for phase in ('early','late'):
                selected=[r for r in results if (r['intent']['ts']<1767225600)==(phase=='early')]
                closed=[r for r in selected if r['status']=='closed'];values=[r['net_R'] for r in closed]
                daily=defaultdict(list)
                for r in closed:daily[r['intent']['ny_date']].append(r['net_R'])
                ci=None
                if len(daily)>=20:
                    days=sorted(daily);sums=np.array([sum(daily[d]) for d in days]);counts=np.array([len(daily[d]) for d in days])
                    rng=np.random.default_rng(20261012)
                    starts=rng.integers(0,len(days),(4000,(len(days)+9)//10))
                    idx=((starts[:,:,None]+np.arange(10))%len(days)).reshape(4000,-1)[:,:len(days)]
                    ci=np.quantile(sums[idx].sum(axis=1)/counts[idx].sum(axis=1),[.025,.975]).tolist()
                gains=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0)
                row=dict(pair=pair,scenario=scenario,phase=phase,setups=len(selected),
                    statuses=dict(Counter(r['status'] for r in selected)),closed=len(closed),
                    wins=sum(v>0 for v in values),net_R_sum=sum(values),
                    mean_net_R=sum(values)/len(values) if values else None,
                    closed_only_day_block_95_ci=ci,profit_factor=gains/loss if loss else None,
                    unknown_results_not_included_in_returns=True,
                    swaps_not_modeled=True,overlapping_observations_not_funded_account=True)
                report['arms'].append(row);print(json.dumps(row),flush=True)
            report.setdefault('observations',{})[pair+'_'+scenario]=results
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
