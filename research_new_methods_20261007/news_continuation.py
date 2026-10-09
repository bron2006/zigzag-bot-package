"""Pure news-continuation rule and offline evaluation; no production imports."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from news_event_calendar import events
from validate_broker_probe import decode_bar

FOLDER = Path(__file__).parent
CACHE = FOLDER / 'news_event_quotes'


def signal(raw_bars, release_ts):
    rows = sorted(({**decode_bar(b), 'ts': int(b['utcTimestampInMinutes'])*60}
                   for b in raw_bars), key=lambda b: b['ts'])
    if len({b['ts'] for b in rows}) != len(rows):
        raise ValueError('Duplicate bars')
    # Future bars must not affect signal eligibility, ATR or direction.
    past = [b for b in rows if release_ts-4500 <= b['ts'] < release_ts]
    impulse = next((b for b in rows if b['ts'] == release_ts), None)
    if [b['ts'] for b in past] != list(range(release_ts-4500, release_ts, 300)) or impulse is None:
        return {'status': 'missing_bars'}
    tr = [max(b['High']-b['Low'], abs(b['High']-past[i-1]['Close']),
              abs(b['Low']-past[i-1]['Close'])) for i, b in enumerate(past) if i]
    atr = float(np.mean(tr))
    move = impulse['Close'] - past[-1]['Close']
    if not np.isfinite(atr) or atr <= 0:
        return {'status': 'invalid_atr'}
    if move == 0 or abs(move) < 1.5*atr:
        return {'status': 'weak_impulse', 'atr': atr, 'impulse': move}
    return {'status': 'selected', 'direction': 1 if move > 0 else -1,
            'atr': atr, 'impulse': move, 'decision_ts': release_ts+300}


def snapshot(streams, deadline_ms):
    """First valid causal joined quote within5s, each side age<=1s."""
    grouped = {}
    for side in ('BID', 'ASK'):
        for tick in streams[side]:
            ts, price = int(tick['timestamp_ms']), float(tick['price'])
            if not np.isfinite(price) or price <= 0:
                raise ValueError('Invalid quote price')
            grouped.setdefault(ts, {}).setdefault(side, []).append(price)
    latest = {}
    for ts, sides in sorted(grouped.items()):
        if ts > deadline_ms+5000:
            break
        for side, values in sides.items():
            # Conservative same-millisecond duplicate handling.
            latest[side] = (ts, min(values) if side == 'BID' else max(values))
        if ts < deadline_ms or len(latest) != 2:
            continue
        if any(ts-item[0] > 1000 for item in latest.values()):
            continue
        bid, ask = latest['BID'][1], latest['ASK'][1]
        if bid <= ask:
            return {'timestamp_ms': ts, 'bid': bid, 'ask': ask}
    return None


def outcome(direction, entry, exit_quote):
    if entry is None or exit_quote is None:
        return {'status': 'missing_endpoint'}
    if direction not in (-1,1) or not 300000 <= exit_quote['timestamp_ms']-entry['timestamp_ms'] <=305000:
        raise ValueError('Invalid direction or five-minute endpoint')
    gross = exit_quote['bid']-entry['ask'] if direction == 1 else entry['bid']-exit_quote['ask']
    mid_move = direction*((exit_quote['bid']+exit_quote['ask'])-(entry['bid']+entry['ask']))/2
    return {'status': 'known', 'forex_net_pips': gross/.0001-.7,
            'forex_stress_pips': gross/.0001-1.7,
            'midpoint_direction': int(np.sign(mid_move)),
            'entry_ms': entry['timestamp_ms'], 'exit_ms': exit_quote['timestamp_ms'],
            'entry_spread_pips': (entry['ask']-entry['bid'])/.0001}


def ci(values):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return None
    rng = np.random.default_rng(20261009)
    samples = values[rng.integers(0, len(values), size=(4000,len(values)))].mean(axis=1)
    return [float(v) for v in np.quantile(samples, [.025,.975])]


def summarize(records):
    known = [r for r in records if r.get('status') == 'known']
    selected = [r for r in records if r.get('selected')]
    result = {'events': len(records), 'statuses': dict(Counter(r['status'] for r in records)),
              'selected': len(selected), 'known': len(known),
              'coverage': len(known)/len(selected) if selected else None}
    if not known:
        return result
    for key in ('forex_net_pips','forex_stress_pips'):
        values = [r[key] for r in known]
        result[key] = {'mean': float(np.mean(values)), 'ci95': ci(values), 'sum': float(np.sum(values))}
    direction = np.array([r['direction'] for r in known])
    signs = np.array([r['midpoint_direction'] for r in known])
    result['midpoint_wins'] = int((signs > 0).sum())
    result['midpoint_decided'] = int((signs != 0).sum())
    result['midpoint_winrate'] = float((signs[signs != 0] > 0).mean()) if (signs != 0).any() else None
    result['binary_payout_proxy'] = {}
    for payout in (.7,.8,.9):
        values = np.where(signs == 0, 0., np.where(signs > 0,payout,-1.))
        result['binary_payout_proxy'][str(payout)] = {'mean_units': float(values.mean()),'ci95': ci(values)}
    result['paired_binary_advantage_ci95_at80'] = {}
    chosen_payoff = np.where(signs == 0, 0., np.where(signs > 0,.8,-1.))
    for label, base in [('always_up',signs*direction),('always_down',-signs*direction)]:
        base_payoff = np.where(base==0,0.,np.where(base>0,.8,-1.))
        result['paired_binary_advantage_ci95_at80'][label] = ci(chosen_payoff-base_payoff)
    result['paired_forex_advantage_ci95'] = {}
    # Recalculate opposite-direction execution from cached entry/exit, preserving spread/cost.
    for label, baseline_direction in [('always_up',np.ones(len(known))),('always_down',-np.ones(len(known)))]:
        baseline = [outcome(int(d),r['entry_quote'],r['exit_quote'])['forex_stress_pips']
                    for d,r in zip(baseline_direction,known,strict=True)]
        result['paired_forex_advantage_ci95'][label] = ci(np.array([r['forex_stress_pips'] for r in known])-baseline)
    result['direction_counts'] = dict(Counter('BUY' if d==1 else 'SELL' for d in direction))
    opposite = [outcome(-r['direction'],r['entry_quote'],r['exit_quote'])['forex_stress_pips'] for r in known]
    result['opposite_direction_diagnostic_not_strategy'] = {'forex_stress_mean_pips':float(np.mean(opposite)),
                                                           'midpoint_winrate':1-result['midpoint_winrate'] if result['midpoint_winrate'] is not None else None}
    return result


def main():
    records, hashes = [], {}
    calendar = events()
    if len({e['date'] for e in calendar}) != len(calendar):
        raise ValueError('Date bootstrap requires independent date groups, duplicate release date found')
    for event in calendar:
        path = CACHE / (event['id']+'.json.gz')
        if not path.exists():
            records.append({**event, 'status': 'not_fetched', 'selected': False})
            continue
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            data = json.load(stream)
        if data['event'] != event or not data['complete_pages']:
            raise ValueError('Cache contract changed/incomplete')
        prepared = signal(data['raw_trendbars'],event['release_ts'])
        result = {**event,**prepared,'selected': prepared['status']=='selected'}
        if result['selected']:
            entry = snapshot(data['entry_streams'], (event['release_ts']+301)*1000)
            exit_quote = snapshot(data['exit_streams'],entry['timestamp_ms']+300000) if entry else None
            result.update(outcome(result['direction'],entry,exit_quote))
            result.update(entry_quote=entry,exit_quote=exit_quote)
        records.append(result)
    early = summarize([r for r in records if r['date'] < '2025-01-01'])
    late = summarize([r for r in records if r['date'] >= '2025-01-01'])
    usable = (late['known'] >= 30 and (late['coverage'] or 0) >= .9
              and not any(r['status'] == 'not_fetched' for r in records))
    forex_gate = bool(usable and early.get('forex_stress_pips',{}).get('mean',-1)>0
        and late['forex_stress_pips']['ci95'][0]>0
        and all(bounds and bounds[0]>0 for bounds in late['paired_forex_advantage_ci95'].values()))
    binary_gate = bool(usable and early.get('binary_payout_proxy',{}).get('0.8',{}).get('mean_units',-1)>0
        and late['binary_payout_proxy']['0.8']['ci95'][0]>0
        and all(bounds and bounds[0]>0 for bounds in late['paired_binary_advantage_ci95_at80'].values()))
    report = {'status': 'paper_candidate_only' if forex_gate or binary_gate else 'not_qualified',
        'forex_gate':forex_gate,'binary_proxy_gate':binary_gate,'not_binomo_settlement':True,
        'no_profit_claim':True,'prospective_OOS':False,'orders':0,
        'early2024':early,'late2025_2026':late,'records':records,'cache_hashes':hashes,
        'protocol_sha256':hashlib.sha256((FOLDER/'NEWS_CONTINUATION_PROTOCOL.md').read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'production_model_hashes':{name:hashlib.sha256((FOLDER.parent/name).read_bytes()).hexdigest()
                                   for name in ('lgbm_model.pkl','lgbm_scaler.pkl')}}
    (FOLDER/'news_continuation_result_v1.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','cache_hashes')},indent=2))


if __name__ == '__main__':
    main()
