"""Offline causal replay of logged intentions; proxy fills, never orders."""
import ast
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import numpy as np

from validate_broker_probe import decode_bar

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(__file__).parent
source = ast.parse((ROOT/'vwap_mean_reversion_event_study.py').read_text(encoding='utf-8-sig'))
function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'compute_causal_vwap_bands')
namespace = {'np': np, 'Z_BAND': 2.}
exec(compile(ast.Module(body=[function], type_ignores=[]), 'shared-causal-vwap', 'exec'), namespace)
bands = namespace['compute_causal_vwap_bands']


def timestamp(record):
    # All snapshot dates are within the verified UTC+3 summer interval.
    dt = datetime.fromisoformat(record['local_wall_time'])
    if not datetime(2026, 8, 25) <= dt < datetime(2026, 10, 8):
        raise ValueError('Date outside verified timezone interval')
    return int(dt.replace(tzinfo=timezone(timedelta(hours=3))).timestamp())


def replay(order, rows, spread, commission):
    entry, stop, when = order['limit'], order['stop'], order['timestamp']
    risk = entry-stop
    if risk <= 0:
        return dict(status='invalid_risk')
    earliest = ((when+299)//300)*300
    filled = False
    for i, row in enumerate(rows):
        if row['ts'] < earliest:
            continue
        if not filled:
            if row['Low']+spread > entry:
                continue
            filled = True
            fill_time = row['ts']
            if row['Low'] <= stop:
                price = min(stop, row['Open'])
                return dict(status='filled', outcome='STOP_fill_bar', r=(price-entry-commission)/risk,
                            fill_ts=fill_time, exit_ts=row['ts'])
            continue
        if row['Low'] <= stop:
            price = min(stop, row['Open'])
            return dict(status='filled', outcome='STOP', r=(price-entry-commission)/risk,
                        fill_ts=fill_time, exit_ts=row['ts'])
        target = rows[i-1]['vwap']
        if np.isfinite(target) and target > entry and row['High'] >= target:
            return dict(status='filled', outcome='VWAP', r=(target-entry-commission)/risk,
                        fill_ts=fill_time, exit_ts=row['ts'])
    if not filled:
        return dict(status='unfilled')
    return dict(status='filled', outcome='SESSION_END', r=(rows[-1]['Close']-entry-commission)/risk,
                fill_ts=fill_time, exit_ts=rows[-1]['ts']+300)


def statistics(records):
    filled = [r for r in records if r['status'] == 'filled']
    result = dict(statuses=dict(Counter(r['status'] for r in records)), filled=len(filled))
    if not filled:
        result.update(mean_r=None, pf=None, total_r=None, day_cluster_mean_ci=None)
        return result
    values = np.array([r['r'] for r in filled])
    wins, losses = values[values > 0].sum(), -values[values < 0].sum()
    daily = defaultdict(list)
    for record in filled:
        daily[record['day']].append(record['r'])
    sums = np.array([sum(v) for v in daily.values()])
    counts = np.array([len(v) for v in daily.values()])
    rng = np.random.default_rng(20261009)
    indices = rng.integers(0, len(sums), (10000, len(sums)))
    bootstrap = sums[indices].sum(axis=1)/counts[indices].sum(axis=1)
    result.update(mean_r=float(values.mean()), total_r=float(values.sum()),
                  pf=float(wins/losses) if losses else None,
                  days_with_fills=len(daily), day_cluster_mean_ci=np.quantile(bootstrap, [.025, .975]).tolist(),
                  outcomes=dict(Counter(r['outcome'] for r in filled)))
    return result


def main():
    raw = json.loads((FOLDER/'vwap_intentions_inventory.json').read_text(encoding='utf-8'))
    originals = raw['intentions']
    exact = {}
    for record in originals:
        key = (record['local_wall_time'], record['symbol'], record['limit_price'], record['stop_price'], record['volume'])
        exact.setdefault(key, record)
    candidates, outside = {}, 0
    for record in sorted(exact.values(), key=lambda r: (r['local_wall_time'], r['symbol'])):
        ts = timestamp(record)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if dt.weekday() >= 5 or not 12 <= dt.hour < 16:
            outside += 1
            continue
        key = (record['symbol'], dt.date().isoformat())
        candidates.setdefault(key, dict(**record, timestamp=ts, day=key[1]))
    results, manifest = [], {}
    for symbol in raw['summary']['symbols']:
        path = FOLDER/'vwap_replay_m5'/f'{symbol}.json'
        if not path.exists():
            for (name, day), record in candidates.items():
                if name == symbol:
                    for units in ('literal', 'units_diagnostic'):
                        for stress in (1, 2):
                            results.append(dict(symbol=name, day=day, units=units, stress=stress, status='missing_history'))
            continue
        manifest[symbol] = hashlib.sha256(path.read_bytes()).hexdigest()
        history = json.loads(path.read_text(encoding='utf-8'))
        decoded = []
        for bar in history['raw_trendbars']:
            row = decode_bar(bar)
            row.update(ts=row['start_minute']*60, Volume=int(bar['volume']))
            decoded.append(row)
        decoded.sort(key=lambda r: r['ts'])
        if len({r['ts'] for r in decoded}) != len(decoded):
            raise ValueError('Duplicate raw history')
        highs, lows, closes = (np.array([r[field] for r in decoded]) for field in ('High', 'Low', 'Close'))
        previous = np.r_[closes[0], closes[:-1]]
        tr = np.maximum(highs-lows, np.maximum(np.abs(highs-previous), np.abs(lows-previous)))
        for i, row in enumerate(decoded):
            row['atr'] = float(np.mean(tr[i-13:i+1])) if i >= 13 else float('nan')
        sessions = defaultdict(list)
        for row in decoded:
            dt = datetime.fromtimestamp(row['ts'], tz=timezone.utc)
            if dt.weekday() < 5 and 8 <= dt.hour < 16:
                sessions[dt.date().isoformat()].append(row)
        for (name, day), record in candidates.items():
            if name != symbol:
                continue
            rows = sessions.get(day, [])
            start = int(datetime.fromisoformat(day+'T08:00:00+00:00').timestamp())
            complete = [r['ts'] for r in rows] == list(range(start, start+8*3600, 300))
            past = [r for r in rows if r['ts']+300 <= record['timestamp']]
            for units in ('literal', 'units_diagnostic'):
                factor = 1. if units == 'literal' else 10**int(history['specification']['digits'])/100000
                limit, stop = record['limit_price']*factor, record['stop_price']*factor
                for stress in (1, 2):
                    base = dict(symbol=symbol, day=day, units=units, stress=stress,
                                signal_ts=record['timestamp'], logged_limit=record['limit_price'],
                                logged_stop=record['stop_price'], limit=limit, stop=stop,
                                source=record['source'], line=record['line'])
                    if not complete or not past or not np.isfinite(past[-1]['atr']):
                        result = dict(status='unavailable_session')
                    elif not .5 <= limit/past[-1]['Close'] <= 2:
                        result = dict(status='scale_mismatch')
                    else:
                        vwaps, _, _ = bands(np.array([r['Close'] for r in rows]), np.array([r['Volume'] for r in rows]))
                        for row, value in zip(rows, vwaps):
                            row['vwap'] = value
                        atr = past[-1]['atr']
                        result = replay(dict(limit=limit, stop=stop, timestamp=record['timestamp']),
                                        rows, .20*atr*stress, .02*atr*stress)
                    results.append(dict(**base, **result))
    summary = dict(raw_log_records=len(originals), exact_unique_log_records=len(exact),
                   outside_entry_window=outside, pair_day_candidates=len(candidates),
                   fills_are_m5_proxies_not_confirmed=True, scenarios={})
    for units in ('literal', 'units_diagnostic'):
        for stress in (1, 2):
            selected = [r for r in results if r['units'] == units and r['stress'] == stress]
            summary['scenarios'][f'{units}_stress{stress}'] = dict(
                all=statistics(selected), early=statistics([r for r in selected if r['day'] < '2026-09-14']),
                late=statistics([r for r in selected if r['day'] >= '2026-09-14']))
    days = []
    first, last = map(datetime.fromisoformat, (raw['summary']['days'][0], raw['summary']['days'][-1]))
    dt = first
    while dt <= last:
        if dt.weekday() < 5:
            day = dt.date().isoformat()
            baseline = [r for r in results if r['day'] == day and r['units'] == 'literal' and r['stress'] == 1]
            filled = [r for r in baseline if r['status'] == 'filled']
            days.append(dict(day=day, raw_log_records=sum(r['local_wall_time'].startswith(day) for r in originals),
                             **statistics(baseline)))
        dt += timedelta(days=1)
    summary['days'] = days
    summary['daily_table_scenario'] = 'literal_stress1'
    summary['units_diagnostic_valid_for_strategy'] = False
    output = dict(summary=summary, records=results, history_sha256=manifest,
                  protocol_sha256=hashlib.sha256((FOLDER/'VWAP_REPLAY_PROTOCOL.md').read_bytes()).hexdigest())
    (FOLDER/'vwap_replay_results.json').write_text(json.dumps(output, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'days'}, indent=2))


if __name__ == '__main__':
    main()
