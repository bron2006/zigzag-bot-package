"""Causal multi-asset cash/risk overlays on frozen research trades, no orders."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_FLOOR
import json
import hashlib
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
POLICIES = ('baseline', 'shared', 'drawdown', 'conservative')


def replay(rows, volumes, policy, cost):
    if policy not in POLICIES:
        raise ValueError('unknown policy')
    balance = peak = D('1000')
    active, trades, events = [], [], []
    skips = Counter()
    drawdown = max_reserved = D(0)
    half_size_entries = 0

    def settle(ts):
        nonlocal balance, peak, drawdown
        due = sorted([p for p in active if p['exit_ts'] <= ts],
                     key=lambda p: (p['exit_ts'], p['symbol']))
        for p in due:
            balance += p['pnl']
            peak = max(peak, balance)
            drawdown = max(drawdown, (peak - balance) / peak)
            events.append(dict(ts=p['exit_ts'], pnl=float(p['pnl']), balance=float(balance)))
            active.remove(p)

    for row in sorted(rows, key=lambda r: (r['entry_ts'], r['symbol'])):
        if row['status'] != 'closed':
            raise ValueError('unknown trade forbids cash simulation')
        settle(row['entry_ts'])
        if balance <= 0:
            skips['nonpositive_balance'] += 1
            continue
        fraction = D('.005')
        if policy == 'conservative' or (policy == 'drawdown' and (peak-balance)/peak >= D('.02')):
            fraction = D('.0025')
            half_size_entries += 1
        reserved = sum((p['risk'] for p in active), D(0))
        budget = balance * fraction
        if policy != 'baseline':
            budget = min(budget, max(D(0), balance*D('.005')-reserved))
        entry, distance, fee = [D(str(v)) for v in (row['entry'], row['stop_distance'], cost)]
        terms = volumes[row['symbol']]
        minimum, step, maximum = [D(str(terms[k])) for k in ('minVolume','stepVolume','maxVolume')]
        notional = sum((p['notional'] for p in active), D(0))
        raw = min(budget/(distance+fee), max(D(0),balance*5-notional)/entry, maximum)
        units = (raw/step).to_integral_value(rounding=ROUND_FLOOR)*step
        if units < minimum:
            skips['risk_or_notional_below_minimum'] += 1
            continue
        risk = units*(distance+fee)
        pnl = units*(D(row['side'])*(D(str(row['exit']))-entry)-fee)
        # Outcome is used only after units have been determined; it is not
        # accessible to later decisions until this position's exit is settled.
        position = dict(symbol=row['symbol'], exit_ts=row['exit_ts'], risk=risk,
                        notional=units*entry, pnl=pnl)
        active.append(position)
        max_reserved = max(max_reserved,(reserved+risk)/balance)
        trades.append(dict(symbol=row['symbol'], entry_ts=row['entry_ts'],
                           units=float(units), risk=float(risk), pnl=float(pnl),
                           exit_ts=row['exit_ts']))
    settle(float('inf'))
    year_ends = {}
    for event in events:
        year_ends[str(datetime.fromtimestamp(event['ts'],timezone.utc).year)] = event['balance']
    return dict(end_usd=float(balance), net_usd=float(balance-1000), taken=len(trades),
                skips=dict(skips), year_end_balances=year_ends,
                closed_balance_drawdown_percent=float(drawdown*100),
                max_reserved_risk_percent=float(max_reserved*100),
                reduced_risk_opportunities=half_size_entries, trades=trades, events=events)


def interval(events, reference=None):
    start = int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp())
    daily = np.zeros((end-start)//86400)
    for source, sign in [(events,1),(reference or [],-1)]:
        for event in source:
            if start <= event['ts'] < end:
                daily[(event['ts']-start)//86400] += sign*event['pnl']
    rng = np.random.default_rng(20261015)
    starts = rng.integers(0,len(daily)-9,size=(10000,(len(daily)+9)//10))
    samples = daily[(starts[:,:,None]+np.arange(10)).reshape(10000,-1)[:,:len(daily)]].sum(axis=1)
    return [float(x) for x in np.quantile(samples,[.05/32,1-.05/32])]


def main():
    metadata=json.loads((HERE.parent/'research_schedule_audit_20261014'/'metadata.json').read_text('utf-8'))
    reports={symbol:json.loads((HERE/name).read_text('utf-8')) for symbol,name in
             [('EURUSD','result.json'),('GBPUSD','result_GBPUSD.json')]}
    volumes={s:{k:float(next(x for x in metadata['symbols'] if x['name']==s)['specification'][k])/100
                for k in ('minVolume','stepVolume','maxVolume')} for s in reports}
    output={'provenance':dict(protocol_sha256=hashlib.sha256((HERE/'SIZING_PROTOCOL.md').read_bytes()).hexdigest(),
        source_sha256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                       for name in ('result.json','result_GBPUSD.json')},
        metadata_sha256=hashlib.sha256((HERE.parent/'research_schedule_audit_20261014'/'metadata.json').read_bytes()).hexdigest(),
        production_changed=False,fresh_holdout=False)}
    for scenario,cost in [('base',.0002),('stress',.0004)]:
        rows=[dict(r,symbol=s) for s,report in reports.items()
              for r in report['scenarios'][scenario]['rows'] if r['month']>='2025-01']
        arms={p:replay(rows,volumes,p,cost) for p in POLICIES}
        for policy,arm in arms.items():
            arm['net_2026_cash_ci']=interval(arm['events'])
            arm['excess_2026_vs_baseline_ci']=interval(arm['events'],arms['baseline']['events'])
            print(json.dumps(dict(scenario=scenario,policy=policy,**{k:v for k,v in arm.items() if k not in ('events','trades')})),flush=True)
        output[scenario]=arms
    (HERE/'sizing_result.json').write_text(json.dumps(output,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    main()
