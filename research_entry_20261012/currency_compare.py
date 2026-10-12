"""Offline synchronized FX basket screen. No credentials, network or bot imports."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from currency_strength import select
from entry_rules import choose_entry, settle
from validate_broker_probe import decode_bar
from transparent_compare import summary, lower_bound


def main():
    folder=ROOT/'research_new_methods_20261007'/'vwap_replay_m5'
    paths=sorted(p for p in folder.glob('*.json') if p.name!='fetch_status.json')
    histories,positions,ready={}, {}, []
    inputs={}
    union=set()
    for path in paths:
        inputs[path.stem]=hashlib.sha256(path.read_bytes()).hexdigest()
        raw=json.loads(path.read_text(encoding='utf-8'))
        bars=[dict(ts=b['start_minute']*60,**{k:v for k,v in b.items() if k!='start_minute'})
              for b in sorted((decode_bar(x) for x in raw['raw_trendbars']),key=lambda b:b['start_minute'])]
        lookup={b['ts']:i for i,b in enumerate(bars)}
        if len(lookup)!=len(bars): raise ValueError('duplicate_timestamps')
        if any(b['ts']%300 for b in bars): raise ValueError('unaligned_M5_timestamps')
        histories[path.stem],positions[path.stem]=bars,lookup
        ready.append({b['ts'] for i,b in enumerate(bars) if i>=14 and b['ts']-bars[i-14]['ts']==4200})
        union.update(lookup)
    synchronized=set.intersection(*ready)
    arms={p:[] for p in ('immediate','pullback_confirm','always_buy','always_sell')}
    last=-float('inf')
    selections=[]
    for ts in sorted(synchronized):
        if ts+300-last<1800: continue
        returns={p:math.log(bars[positions[p][ts]]['Close']/bars[positions[p][ts]-12]['Close'])
                 for p,bars in histories.items()}
        setup=select(returns)
        if setup is None: continue
        pair,direction=setup['pair'],setup['direction']
        bars=histories[pair]
        i=positions[pair][ts]
        tr=[max(bars[j]['High']-bars[j]['Low'],abs(bars[j]['High']-bars[j-1]['Close']),
                abs(bars[j]['Low']-bars[j-1]['Close'])) for j in range(i-13,i+1)]
        atr=sum(tr)/14
        if atr<=0: raise ValueError('invalid_atr')
        last=ts+300
        day=datetime.fromtimestamp(last,timezone.utc).date().isoformat()
        selections.append(dict(ts=last,pair=pair,direction=direction,residual_rms=setup['residual_rms']))
        for policy in arms:
            side=1 if policy=='always_buy' else -1 if policy=='always_sell' else direction
            entry_policy='immediate' if policy.startswith('always_') else policy
            result=settle(bars,choose_entry(bars,i,side,atr,entry_policy),side)
            result.update(day=day,pair=pair,signal_ts=last)
            arms[policy].append(result)
    report=dict(retrospective=True,executable=False,proven_edge=False,production_activated=False,
                pairs=len(paths),union_bars=len(union),synchronized_ready_bars=len(synchronized),
                inputs_sha256=inputs,selections=selections,
                protocol_sha256=hashlib.sha256(Path(__file__).with_name('CURRENCY_PROTOCOL.md').read_bytes()).hexdigest(),arms=[])
    for policy,results in arms.items():
        by_month=defaultdict(list)
        for r in results: by_month[r['day'][:7]].append(r)
        stats=summary(results)
        months={m:summary(r) for m,r in sorted(by_month.items())}
        lower=lower_bound(results,169)
        passed=(policy in ('immediate','pullback_confirm') and stats['decided']>=200
                and bool(months) and all(m['stress_pnl_pessimistic']>0 for m in months.values())
                and lower is not None and lower>0)
        row=dict(policy=policy,**stats,months=months,adjusted_pessimistic_stress_lower=lower,cheap_screen_pass=passed)
        report['arms'].append(row)
        print(json.dumps(row),flush=True)
    report['passed']=sum(r['cheap_screen_pass'] for r in report['arms'])
    Path(__file__).with_name('currency_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('pairs','union_bars','synchronized_ready_bars','passed','production_activated')}))


if __name__=='__main__': main()
