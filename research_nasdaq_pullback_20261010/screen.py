"""Offline causal OHLC screen. No application/config/DB imports or orders."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'research_new_methods_20261007'))
from validate_broker_probe import decode_bar

NY = ZoneInfo('America/New_York')
# Official NYSE 2024-2026 calendar + Nasdaq Carter mourning alert.
HOLIDAYS = set('2024-01-01 2024-01-15 2024-02-19 2024-03-29 2024-05-27 2024-06-19 2024-07-04 2024-09-02 2024-11-28 2024-12-25 2025-01-01 2025-01-09 2025-01-20 2025-02-17 2025-04-18 2025-05-26 2025-06-19 2025-07-04 2025-09-01 2025-11-27 2025-12-25 2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25'.split())
EARLY = set('2024-07-03 2024-11-29 2024-12-24 2025-07-03 2025-11-28 2025-12-24 2026-11-27 2026-12-24'.split())


def session_timestamps(day):
    opened = int(datetime.combine(day, time(9, 30), NY).timestamp())
    return list(range(opened, opened+23400, 300))


def load_history(label):
    cache = HERE/'cache'
    manifest = json.loads((cache/'complete.json').read_text(encoding='utf-8'))
    contract = manifest['histories'][label]
    rows = {}
    hashes = {}
    duplicates = 0
    for page in contract['pages']:
        path = cache/page['file']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != page['sha256']:
            raise ValueError('Cache SHA mismatch')
        hashes[path.name] = digest
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            raw = json.load(stream)
        for bar in raw['bars']:
            decoded = decode_bar(bar)
            ts = decoded.pop('start_minute')*60
            if contract['start_ms'] <= ts*1000 < contract['end_exclusive_ms']:
                decoded['ts'] = ts
                if ts in rows:
                    if rows[ts] != decoded:
                        raise ValueError('Conflicting duplicate bar')
                    duplicates += 1
                rows[ts] = decoded
    if not rows:
        raise ValueError('Empty history')
    return [rows[t] for t in sorted(rows)], hashes, duplicates


def atr_before(daily, opening):
    completed = [b for b in daily if b['ts']+86400 <= opening and
                 datetime.fromtimestamp(b['ts']+86400, timezone.utc).weekday() < 5]
    if len(completed) < 15:
        return None
    window = completed[-15:]
    if any(b['ts']-a['ts'] > 5*86400 for a, b in zip(window, window[1:])):
        return None
    ranges = [max(b['High']-b['Low'], abs(b['High']-a['Close']), abs(b['Low']-a['Close']))
              for a, b in zip(window, window[1:])]
    value = sum(ranges)/14
    return value if math.isfinite(value) and value > 0 else None


def decide_entry(bars, atr):
    """Return (entry-index, direction, intent-close-ts) or a no-trade reason."""
    anchor = bars[0]['Open']
    upper, lower = anchor+.5*atr, anchor-.5*atr
    for i, bar in enumerate(bars):
        closed = datetime.fromtimestamp(bar['ts']+300, NY)
        if closed.minute % 15 or not time(9, 45) <= closed.time() <= time(15):
            continue
        direction = 1 if bar['Close'] > upper else -1 if bar['Close'] < lower else 0
        if not direction:
            continue
        intent = bar['ts']+300
        for j in range(i+1, min(i+7, len(bars)-1)):
            pullback = bars[j]
            still = pullback['Close'] > upper if direction == 1 else pullback['Close'] < lower
            if not still:
                return None, 'cancelled_reentry'
            if direction*(pullback['Close']-pullback['Open']) < 0:
                entry = bars[j+1]['Open']
                if (direction == 1 and entry <= upper) or (direction == -1 and entry >= lower):
                    return None, 'cancelled_entry_gap'
                return (j+1, direction, intent), 'trade'
        return None, 'expired_intent'
    return None, 'no_breakout'


def exit_trade(bars, index, direction, stop):
    entry = bars[index]['Open']
    worst = 0.0
    closes = []
    adverse_marks = []
    for bar in bars[index:]:
        gap = direction*(bar['Open']-stop) <= 0
        hit = bar['Low'] <= stop if direction == 1 else bar['High'] >= stop
        if gap or hit:
            price = bar['Open'] if gap else stop
            worst = min(worst, direction*(price-entry))
            closes.append(direction*(price-entry))
            adverse_marks.append(direction*(price-entry))
            return price, bar['ts'], 'stop_gap' if gap else 'stop', worst, closes, adverse_marks
        adverse = direction*((bar['Low'] if direction == 1 else bar['High'])-entry)
        worst = min(worst, adverse)
        closes.append(direction*(bar['Close']-entry))
        adverse_marks.append(adverse)
    return bars[-1]['Close'], bars[-1]['ts']+300, 'session_close', worst, closes, adverse_marks


def collect(m5, daily):
    by_ts = {b['ts']: b for b in m5}
    sessions = []
    day = date(2024, 1, 1)
    while day < date(2026, 10, 8):
        if day.weekday() < 5 and day.isoformat() not in HOLIDAYS | EARLY:
            times = session_timestamps(day)
            record = {'day': day.isoformat(), 'year': day.year, 'status': 'missing_session'}
            if all(t in by_ts for t in times):
                bars = [by_ts[t] for t in times]
                atr = atr_before(daily, times[0])
                record['status'] = 'missing_atr'
                if atr is not None:
                    entry_data, reason = decide_entry(bars, atr)
                    record.update(status=reason, atr=atr, anchor=bars[0]['Open'])
                    if entry_data:
                        index, direction, intent = entry_data
                        entry = bars[index]['Open']
                        stop = bars[0]['Open']
                        exit_price, exited, why, worst, closes, adverse_marks = exit_trade(bars, index, direction, stop)
                        distance = direction*(entry-stop)
                        if distance <= 0:
                            raise ValueError('Invalid risk distance')
                        record.update(direction=direction, intent_ts=intent, entry_ts=bars[index]['ts'],
                                      entry=entry, stop=stop, risk_points=distance, exit=exit_price,
                                      exit_ts=exited, exit_reason=why, gross_points=direction*(exit_price-entry),
                                      adverse_points=worst, mark_points=closes, adverse_mark_points=adverse_marks)
            sessions.append(record)
        day += timedelta(days=1)
    return sessions


def block_interval(values, block=5, repeats=5000):
    a = np.asarray(values, dtype=float)
    if len(a) < 2:
        return None
    rng = np.random.default_rng(20261010)
    chunks = math.ceil(len(a)/block)
    starts = rng.integers(0, len(a), size=(repeats, chunks))
    indices = (starts[..., None]+np.arange(block)) % len(a)
    means = a[indices.reshape(repeats, -1)[:, :len(a)]].mean(axis=1)
    return [float(v) for v in np.quantile(means, [.025, .975])]


def account_projection(trades, friction, minimum, step, rounded):
    equity, peak, dd, mark_peak, mark_dd, worst_dd = 1000., 1000., 0., 1000., 0., 0.
    taken, skipped_small, skipped_cap = 0, 0, 0
    for trade in trades:
        budget = .01*equity
        quantity = budget/(trade['risk_points']+friction)
        if rounded:
            quantity = math.floor((quantity+1e-12)/step)*step
            if quantity+1e-12 < minimum:
                skipped_small += 1
                continue
        if quantity*trade['entry'] > 5*equity:
            skipped_cap += 1
            continue
        # Full assumed RT charge in every intratrade mark: conservative diagnostic.
        for points, adverse in zip(trade['mark_points'], trade['adverse_mark_points'], strict=True):
            adverse_mark = equity+quantity*(adverse-friction)
            worst_dd = max(worst_dd, 1-adverse_mark/mark_peak)
            mark = equity+quantity*(points-friction)
            mark_peak = max(mark_peak, mark)
            mark_dd = max(mark_dd, 1-mark/mark_peak)
        equity += quantity*(trade['gross_points']-friction)
        taken += 1
        peak = max(peak, equity)
        dd = max(dd, 1-equity/peak)
        if equity <= 0:
            break
    return {'ending_usd': equity, 'net_usd': equity-1000, 'return_pct': (equity/1000-1)*100,
            'closed_balance_dd_pct': dd*100, 'bar_close_mark_dd_pct': mark_dd*100,
            'sampled_adverse_range_dd_pct': worst_dd*100, 'trades_taken': taken,
            'below_minimum_skips': skipped_small, 'notional_cap_skips': skipped_cap,
            'conditional_not_executable_profit': True}


def summarize(rows, minimum, step):
    known = [r for r in rows if not r['status'].startswith('missing')]
    trades = [r for r in known if r['status'] == 'trade']
    result = {'scheduled_sessions': len(rows), 'known_sessions': len(known),
              'coverage': len(known)/len(rows) if rows else 0,
              'statuses': dict(Counter(r['status'] for r in rows)), 'trades': len(trades),
              'longs': sum(t['direction'] == 1 for t in trades),
              'shorts': sum(t['direction'] == -1 for t in trades),
              'cost_scenarios': {}}
    for label, friction in [('gross', 0.), ('base', 2.), ('stress', 5.)]:
        net = [t['gross_points']-friction for t in trades]
        positive = sum(max(0., n) for n in net)
        negative = -sum(min(0., n) for n in net)
        daily_points = [(r['gross_points']-friction) if r['status'] == 'trade' else 0. for r in known]
        daily_r = [(r['gross_points']-friction)/r['risk_points'] if r['status'] == 'trade' else 0. for r in known]
        result['cost_scenarios'][label] = {
            'assumed_round_trip_points': friction, 'sum_net_points': sum(net),
            'mean_net_points_per_trade': sum(net)/len(net) if net else None,
            'profit_factor': positive/negative if negative else None,
            'win_rate': sum(n > 0 for n in net)/len(net) if net else None,
            'mean_r_per_trade': sum((t['gross_points']-friction)/t['risk_points'] for t in trades)/len(trades) if trades else None,
            'mean_points_per_known_session_ci95': block_interval(daily_points),
            'mean_r_per_known_session_ci95': block_interval(daily_r),
            'net_points_without_best_three': sum(net)-sum(sorted(net, reverse=True)[:3]),
            'fractional_account': account_projection(trades, friction, minimum, step, False),
            'rounded_account': account_projection(trades, friction, minimum, step, True)}
    result['gross_break_even_round_trip_points'] = sum(t['gross_points'] for t in trades)/len(trades) if trades else None
    return result


def main():
    frozen_hash = json.loads((HERE/'cache'/'complete.json').read_text())['protocol_sha256']
    current_hash = hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest()
    amended_hash = '0faf40692bc3adfa34760bea3a0dc54c0785da142590a4384c4dd3d9a49be126'
    original_hash = '36eb4263844cfa7c67c4e9f5506767365880021511852cad466a92751bb3c36e'
    amendment = frozen_hash == original_hash and current_hash == amended_hash and (HERE/'PRE_RESULT_AMENDMENT.md').exists()
    if frozen_hash != current_hash and not amendment:
        raise ValueError('Protocol changed since history completion')
    m5, m5hashes, duplicates = load_history('M5')
    daily, d1hashes, daily_duplicates = load_history('D1')
    meta = json.loads((HERE/'cache'/'metadata.json').read_text(encoding='utf-8'))
    spec = meta['specification']
    minimum, step = int(spec['minVolume'])/100, int(spec['stepVolume'])/100
    if meta['light']['quoteAssetId'] != '16' or spec.get('commission') != '0':
        raise ValueError('USD/zero-current-commission assumptions require review')
    rows = collect(m5, daily)
    yearly = {str(y): summarize([r for r in rows if r['year'] == y], minimum, step) for y in (2024, 2025, 2026)}
    final = yearly['2026']
    checks = {'confirmation_at_least_100_trades': final['trades'] >= 100,
              'confirmation_coverage_at_least_95pct': final['coverage'] >= .95,
              'stress_profit_positive_each_year': all(v['cost_scenarios']['stress']['sum_net_points'] > 0 for v in yearly.values()),
              'confirmation_stress_CI_lower_positive': bool(final['cost_scenarios']['stress']['mean_points_per_known_session_ci95'] and
                 final['cost_scenarios']['stress']['mean_points_per_known_session_ci95'][0] > 0)}
    result = {'strategy': 'fixed USTEC session expansion + pullback v1', 'production_allowed': False,
              'prospective_OOS': False, 'historical_bid_ask_fills_verified': False,
              'pre_result_protocol_clarification': amendment,
              'commission_metadata_current_not_historical': spec['commission'], 'minimum_units': minimum, 'step_units': step,
              'm5_bars': len(m5), 'd1_bars': len(daily), 'same_duplicates': duplicates+daily_duplicates,
              'source_sha256': {**m5hashes, **d1hashes},
              'protocol_sha256_at_fetch': json.loads((HERE/'cache'/'complete.json').read_text())['protocol_sha256'],
              'protocol_sha256_now': hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
              'cheap_gate_checks': checks, 'cheap_gate_passed': all(checks.values()), 'yearly': yearly}
    if result['protocol_sha256_now'] != result['protocol_sha256_at_fetch'] and not amendment:
        raise ValueError('Protocol changed since history completion')
    (HERE/'result_v1.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    (HERE/'sessions_v1.json').write_text(json.dumps(rows, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha256'}, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
