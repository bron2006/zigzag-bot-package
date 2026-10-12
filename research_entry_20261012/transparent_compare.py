"""All-cached-market fixed rule screen. No model, bot, config, DB or network."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from transparent_signal import generate, RULES
from entry_rules import choose_entry, settle
from validate_broker_probe import decode_bar


def summary(results):
    counts=Counter(r['status'] for r in results)
    wins,losses=counts['win'],counts['loss']
    unknown=counts['unknown']+counts['unresolved']
    return dict(intents=len(results),counts=dict(counts),decided=wins+losses,
                unknown=unknown,accuracy=wins/(wins+losses) if wins+losses else None,
                conditional_balance_80=1000+8*wins-10*losses,
                conditional_balance_70=1000+7*wins-10*losses,
                stress_pnl_pessimistic=.7*wins-losses-unknown)


def lower_bound(results,family_size):
    days=defaultdict(lambda:[0.,0.])
    for r in results:
        pnl=.7 if r['status']=='win' else -1 if r['status'] in ('loss','unknown','unresolved') else 0
        days[r['day']][0]+=pnl
        days[r['day']][1]+=1
    values=np.array(list(days.values()))
    if len(values)<2: return None
    rng=np.random.default_rng(20261012)
    sampled=values[rng.integers(0,len(values),size=(5000,len(values)))].sum(axis=1)
    return float(np.quantile(sampled[:,0]/sampled[:,1],.05/family_size))


def main():
    folder=ROOT/'research_new_methods_20261007'/'vwap_replay_m5'
    paths=sorted(p for p in folder.glob('*.json') if p.name!='fetch_status.json')
    policies=('immediate','pullback_confirm')
    extended='--extended' in sys.argv
    rules=RULES if extended else ('breakout',)
    report=dict(retrospective=True,proven_edge=False,production_activated=False,
                executable=False,protocol_sha256=hashlib.sha256(Path(__file__).with_name('TRANSPARENT_PROTOCOL.md').read_bytes()).hexdigest(),
                family_size=len(paths)*len(policies)*len(rules),arms=[])
    if extended:
        report['extended_protocol_sha256']=hashlib.sha256(Path(__file__).with_name('EXTENDED_PROTOCOL.md').read_bytes()).hexdigest()
    for path in paths:
        raw=json.loads(path.read_text(encoding='utf-8'))
        bars=[dict(ts=b.pop('start_minute')*60,**b) for b in
              sorted((decode_bar(b) for b in raw['raw_trendbars']),key=lambda b:b['start_minute'])]
        for rule in rules:
            intents=generate(bars,rule)
            arms={p:[] for p in policies}
            last=-float('inf')
            for i,intent in enumerate(intents):
                direction=intent['direction']
                if not direction or intent['ts']-last<1800: continue
                last=intent['ts']
                day=datetime.fromtimestamp(last,timezone.utc).date().isoformat()
                for policy in policies:
                    outcome=settle(bars,choose_entry(bars,i,direction,intent['atr'],policy),direction)
                    outcome['day']=day
                    arms[policy].append(outcome)
            for policy in policies:
                results=arms[policy]
                by_month=defaultdict(list)
                for r in results: by_month[r['day'][:7]].append(r)
                stats=summary(results)
                lower=lower_bound(results,report['family_size'])
                months={m:summary(r) for m,r in sorted(by_month.items())}
                eligible=(stats['decided']>=200 and stats['unknown']<=.05*stats['intents']
                          and bool(months) and all(m['stress_pnl_pessimistic']>0 for m in months.values())
                          and lower is not None and lower>0)
                row=dict(symbol=path.stem,rule=rule,policy=policy,**stats,months=months,
                         input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         adjusted_pessimistic_stress_lower=lower,cheap_screen_pass=eligible)
                report['arms'].append(row)
                print(json.dumps({k:v for k,v in row.items() if k not in ('months','input_sha256')}),flush=True)
    report['passed']=sum(r['cheap_screen_pass'] for r in report['arms'])
    Path(__file__).with_name('extended_result.json' if extended else 'transparent_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(arms=len(report['arms']),passed=report['passed'],production_activated=False)),flush=True)


if __name__=='__main__': main()
