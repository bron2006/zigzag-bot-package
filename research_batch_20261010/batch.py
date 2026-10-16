"""Offline fixed 96-candidate screen, no network/DB/application imports."""
from collections import Counter
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT/'research_new_methods_20261007'))
import comparative_screen as fx
sys.path.insert(0, str(ROOT/'research_nasdaq_pullback_20261010'))
import screen as nasdaq

PROTOCOL_HASH = '377483b41cdfc07d57a586ea360397727cc9d0cbc8b45ffc845a32a915ac8bbe'
RULES = ('orb5', 'orb15', 'orb30', 'failed_orb15', 'retest_orb15',
         'gap_follow', 'gap_fade', 'prior_range', 'nr7', 'ema_cross',
         'ema_pullback', 'donchian20', 'bb_reentry', 'rsi2', 'macd',
         'stochastic', 'inside_break', 'compression', 'morning_follow',
         'morning_fade', 'afternoon_follow', 'dual_thrust', 'open_reclaim',
         'three_impulse')
CONTROLS = ('control_long', 'control_short', 'control_random')
MARKETS = ('USTEC', 'EURUSD', 'GBPUSD', 'USDJPY')


def features(frame):
    out = []
    for _, g in frame.groupby(frame.ts.diff().ne(300).cumsum()):
        c, h, l = g.Close, g.High, g.Low
        p = c.shift(1)
        f = g.copy()
        f['atr'] = pd.concat([h-l, (h-p).abs(), (l-p).abs()], axis=1).max(axis=1).rolling(14).mean()
        f['ema9'], f['ema21'] = c.ewm(span=9, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
        f['macd'] = c.ewm(span=12, adjust=False).mean()-c.ewm(span=26, adjust=False).mean()
        f['macdsig'] = f.macd.ewm(span=9, adjust=False).mean()
        mean, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
        f['bbup'], f['bblo'] = mean+2*sd, mean-2*sd
        gain, loss = c.diff().clip(lower=0).rolling(2).sum(), -c.diff().clip(upper=0).rolling(2).sum()
        f['rsi'] = 100*gain/(gain+loss)
        low, high = l.rolling(14).min(), h.rolling(14).max()
        f['stoch'] = 100*(c-low)/(high-low)
        f['dcup'], f['dclo'] = h.rolling(20).max().shift(1), l.rolling(20).min().shift(1)
        f['range12hi'], f['range12lo'] = h.rolling(12).max().shift(1), l.rolling(12).min().shift(1)
        f['range60'] = (h.rolling(60).max()-l.rolling(60).min()).shift(1)
        f['ready'] = np.arange(len(g)) >= 59
        # Previous closed-bar values remain within uninterrupted segments.
        for key in ('ema9', 'ema21', 'macd', 'macdsig', 'bbup', 'bblo', 'rsi', 'stoch'):
            f['prev_'+key] = f[key].shift(1)
        f['prev_close'] = c.shift(1)
        out.append(f)
    return pd.concat(out).sort_index()


def times_for(day, symbol):
    if symbol == 'USTEC':
        return nasdaq.session_timestamps(day)
    start = int(datetime.combine(day, time(8), ZoneInfo('Europe/London')).timestamp())
    return list(range(start, start+8*3600, 300))


def session_axis(frame, symbol):
    lookup = {int(r['ts']): r for r in frame.to_dict('records')}
    rows, previous = [], []
    day = date(2024, 1, 1)
    while day < date(2026, 10, 8):
        if day.weekday() < 5 and (symbol != 'USTEC' or day.isoformat() not in nasdaq.HOLIDAYS | nasdaq.EARLY):
            times = times_for(day, symbol)
            row = dict(day=day.isoformat(), year=day.year, status='missing_session')
            if all(t in lookup for t in times):
                bars = [lookup[t] for t in times]
                row.update(status='known', bars=bars, previous=list(previous))
                previous.append(dict(day=day, High=max(b['High'] for b in bars),
                                     Low=min(b['Low'] for b in bars), Close=bars[-1]['Close']))
                previous = previous[-7:]
            rows.append(row)
        day += timedelta(days=1)
    return rows


def sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def select(rule, bars, previous, day):
    anchor = bars[0]['Open']
    prev = previous[-1] if previous and (day-previous[-1]['day']).days <= 5 else None
    ranges = [p['High']-p['Low'] for p in previous]
    history_ok = all((b['day']-a['day']).days <= 5 for a, b in zip(previous, previous[1:]))
    excursion = 0
    orhigh, orlow = max(b['High'] for b in bars[:3]), min(b['Low'] for b in bars[:3])
    for i in range(len(bars)-3):
        b = bars[i]
        if not b['ready'] or not math.isfinite(b['atr']) or b['atr'] <= 0:
            continue
        c, o, atr = b['Close'], b['Open'], b['atr']
        direction = 0
        if rule.startswith('control_') and i == 11:
            direction = 1 if rule == 'control_long' else -1 if rule == 'control_short' else (1 if int(hashlib.sha256(str(day).encode()).hexdigest(), 16) % 2 else -1)
        elif rule in ('orb5', 'orb15', 'orb30'):
            n = {'orb5': 1, 'orb15': 3, 'orb30': 6}[rule]
            if i >= n:
                high, low = max(x['High'] for x in bars[:n]), min(x['Low'] for x in bars[:n])
                direction = 1 if c > high else -1 if c < low else 0
        elif rule in ('failed_orb15', 'retest_orb15') and i >= 3:
            if not excursion:
                excursion = 1 if c > orhigh else -1 if c < orlow else 0
                continue
            if rule == 'failed_orb15':
                if orlow <= c <= orhigh:
                    direction = -excursion
            else:
                if orlow <= c <= orhigh or excursion*(c-(orhigh if excursion == 1 else orlow)) <= 0:
                    return None
                touched = b['Low'] <= orhigh if excursion == 1 else b['High'] >= orlow
                if touched:
                    direction = excursion
        elif rule in ('gap_follow', 'gap_fade') and prev and i >= 5:
            gap = anchor-prev['Close']
            if abs(gap) >= .25*(prev['High']-prev['Low']) and sign(gap)*(c-prev['Close']) > 0:
                direction = sign(gap)*(1 if rule == 'gap_follow' else -1)
        elif rule in ('prior_range', 'nr7') and prev:
            if rule == 'prior_range' or (len(previous) == 7 and history_ok and ranges[-1] <= min(ranges)):
                direction = 1 if c > prev['High'] else -1 if c < prev['Low'] else 0
        elif rule == 'ema_cross':
            now, before = b['ema9']-b['ema21'], b['prev_ema9']-b['prev_ema21']
            direction = 1 if now > 0 >= before else -1 if now < 0 <= before else 0
        elif rule == 'ema_pullback':
            if b['ema9']-b['ema21'] >= .25*atr and b['Low'] <= b['ema9'] < c and c > o:
                direction = 1
            elif b['ema21']-b['ema9'] >= .25*atr and b['High'] >= b['ema9'] > c and c < o:
                direction = -1
        elif rule == 'donchian20':
            direction = 1 if c > b['dcup'] else -1 if c < b['dclo'] else 0
        elif rule == 'bb_reentry':
            if b['prev_close'] < b['prev_bblo'] and b['bblo'] <= c <= b['bbup']:
                direction = 1
            elif b['prev_close'] > b['prev_bbup'] and b['bblo'] <= c <= b['bbup']:
                direction = -1
        elif rule == 'rsi2':
            direction = 1 if b['prev_rsi'] < 10 <= b['rsi'] else -1 if b['prev_rsi'] > 90 >= b['rsi'] else 0
        elif rule == 'macd':
            now, before = b['macd']-b['macdsig'], b['prev_macd']-b['prev_macdsig']
            direction = 1 if now > 0 >= before else -1 if now < 0 <= before else 0
        elif rule == 'stochastic':
            direction = 1 if b['prev_stoch'] < 20 <= b['stoch'] else -1 if b['prev_stoch'] > 80 >= b['stoch'] else 0
        elif rule == 'inside_break' and i >= 2:
            mother, inside = bars[i-2], bars[i-1]
            if inside['High'] <= mother['High'] and inside['Low'] >= mother['Low']:
                direction = 1 if c > mother['High'] else -1 if c < mother['Low'] else 0
        elif rule == 'compression' and b['range12hi']-b['range12lo'] <= .5*b['range60']:
            direction = 1 if c > b['range12hi'] else -1 if c < b['range12lo'] else 0
        elif rule in ('morning_follow', 'morning_fade') and prev and i == 23:
            if abs(c-anchor) >= .25*(prev['High']-prev['Low']):
                direction = sign(c-anchor)*(1 if rule == 'morning_follow' else -1)
        elif rule == 'afternoon_follow' and i == 53:
            change = c-bars[41]['Close']
            if abs(change) >= 2*atr:
                direction = sign(change)
        elif rule == 'dual_thrust' and prev and len(previous) >= 4 and history_ok:
            p = previous[-4:]
            width = .5*max(max(x['High'] for x in p)-min(x['Close'] for x in p),
                           max(x['Close'] for x in p)-min(x['Low'] for x in p))
            direction = 1 if c > anchor+width else -1 if c < anchor-width else 0
        elif rule == 'open_reclaim':
            if not excursion:
                if abs(c-anchor) >= .5*atr:
                    excursion = sign(c-anchor)
                continue
            if excursion*(c-anchor) < 0:
                direction = -excursion
        elif rule == 'three_impulse' and i >= 2:
            trio = bars[i-2:i+1]
            signs = [sign(x['Close']-x['Open']) for x in trio]
            if signs[0] and signs.count(signs[0]) == 3 and abs(c-trio[0]['Open']) >= 2*atr:
                direction = signs[0]
        if direction:
            return i+1, direction, 1.5*atr
    return None


def simulate(bars, index, side, risk):
    entry = bars[index]['Open']
    stop, target = entry-side*risk, entry+side*2*risk
    marks, adverse = [], []
    for b in bars[index:]:
        gap = side*(b['Open']-stop) <= 0
        stop_hit = b['Low'] <= stop if side == 1 else b['High'] >= stop
        tp_hit = b['High'] >= target if side == 1 else b['Low'] <= target
        if gap or stop_hit or tp_hit:
            price = b['Open'] if gap else stop if stop_hit else target
            reason = 'gap' if gap else 'stop' if stop_hit else 'target'
            marks.append((side*(price-entry), price))
            # On TP bars, adverse extreme may have preceded TP; capped by stop.
            bad = price if gap or stop_hit else (max(b['Low'], stop) if side == 1 else min(b['High'], stop))
            adverse.append((side*(bad-entry), bad))
            return dict(entry=entry, risk=risk, stop=stop, target=target,
                        side=side, exit=price, gross=side*(price-entry), reason=reason,
                        entry_ts=bars[index]['ts'], exit_bar_ts=b['ts'], marks=marks, adverse=adverse)
        marks.append((side*(b['Close']-entry), b['Close']))
        price = b['Low'] if side == 1 else b['High']
        adverse.append((side*(price-entry), price))
    price = bars[-1]['Close']
    return dict(entry=entry, risk=risk, stop=stop, target=target, side=side,
                exit=price, gross=side*(price-entry), reason='close',
                entry_ts=bars[index]['ts'], exit_bar_ts=bars[-1]['ts'], marks=marks, adverse=adverse)


def cost(symbol, scenario):
    return (2. if scenario == 'base' else 5.) if symbol == 'USTEC' else (2. if scenario == 'base' else 4.)*(.01 if symbol == 'USDJPY' else .0001)


def unit_usd(value, price, symbol):
    return value/price if symbol == 'USDJPY' else value


def quantity(trade, balance, charge, spec, symbol, rounded):
    budget_unit = unit_usd(trade['risk']+charge, trade['stop'], symbol)
    notional_unit = 1. if symbol == 'USDJPY' else trade['entry']
    size = min(balance*.01/budget_unit, balance*5/notional_unit, int(spec['maxVolume'])/100)
    if rounded:
        step, minimum = int(spec['stepVolume'])/100, int(spec['minVolume'])/100
        size = math.floor((size+1e-10)/step)*step
        if size+1e-10 < minimum:
            return 0.
    return size


def ledger(rows, symbol, scenario, spec, rounded):
    balance, peak, dd, markpeak, markdd = 1000., 1000., 0., 1000., 0.
    taken, skipped = 0, 0
    nets, fixed_daily = [], []
    charge = cost(symbol, scenario)
    for row in rows:
        trade = row.get('trade')
        daily = 0.
        if trade:
            size = quantity(trade, balance, charge, spec, symbol, rounded)
            fixed_size = quantity(trade, 1000., charge, spec, symbol, rounded)
            daily = fixed_size*unit_usd(trade['gross']-charge, trade['exit'], symbol)
            if not size:
                skipped += 1
            else:
                taken += 1
                for (points, price), (badpoints, badprice) in zip(trade['marks'], trade['adverse'], strict=True):
                    badmark = balance+size*unit_usd(badpoints-charge, badprice, symbol)
                    markdd = max(markdd, 1-badmark/markpeak)
                    mark = balance+size*unit_usd(points-charge, price, symbol)
                    markpeak = max(markpeak, mark)
                    markdd = max(markdd, 1-mark/markpeak)
                net = size*unit_usd(trade['gross']-charge, trade['exit'], symbol)
                balance += net
                nets.append(net)
                peak = max(peak, balance)
                dd = max(dd, 1-balance/peak)
        fixed_daily.append(daily)
    gain, loss = sum(max(n, 0.) for n in nets), -sum(min(n, 0.) for n in nets)
    return dict(net_usd=balance-1000, taken=taken, below_minimum_skips=skipped,
                pf=gain/loss if loss else None, win_rate=sum(n > 0 for n in nets)/len(nets) if nets else None,
                balance_dd_pct=dd*100, sampled_adverse_dd_pct=markdd*100,
                fixed_daily_usd=fixed_daily, without_three_best_fixed_days=sum(fixed_daily)-sum(sorted(fixed_daily, reverse=True)[:3]))


def intervals(values):
    a = np.asarray(values, dtype=float)
    if len(a) < 10:
        return None
    rng = np.random.default_rng(20261010)
    # Chunk memory; same RNG/axis length means same indices across rules.
    means = []
    for _ in range(20):
        starts = rng.integers(0, len(a), size=(1000, math.ceil(len(a)/5)))
        ix = ((starts[..., None]+np.arange(5)) % len(a)).reshape(1000, -1)[:, :len(a)]
        means.extend(a[ix].mean(axis=1).tolist())
    return dict(ci95=np.quantile(means, [.025, .975]).tolist(),
                familywise_lower=float(np.quantile(means, .05/96)),
                mean=float(a.mean()))


def main():
    if hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest() != PROTOCOL_HASH:
        raise ValueError('Frozen batch protocol changed')
    metadata = json.loads((ROOT/'research_new_methods_20261007'/'broker_snapshot.json').read_text())
    specs = {r['name']: r['specification'] for r in metadata['symbols'] if r['name'] in MARKETS}
    specs['USTEC'] = json.loads((ROOT/'research_nasdaq_pullback_20261010'/'cache'/'metadata.json').read_text())['specification']
    result = dict(protocol_sha256=PROTOCOL_HASH, candidate_count=96, control_count=12,
                  execution_verified=False, production_allowed=False, prospective_OOS=False,
                  sources={}, markets={}, candidates={}, controls={})
    paths = []
    for symbol in MARKETS:
        if symbol == 'USTEC':
            bars, hashes, _ = nasdaq.load_history('M5')
            frame = pd.DataFrame(bars)
        else:
            frame, hashes = fx.load_history(symbol)
        result['sources'][symbol] = hashes
        axis = session_axis(features(frame), symbol)
        known = [r for r in axis if r['status'] == 'known']
        result['markets'][symbol] = dict(bars=len(frame), scheduled=len(axis), known=len(known),
                                       statuses=dict(Counter(r['status'] for r in axis)))
        for rule in RULES+CONTROLS:
            rows = []
            for session in known:
                entry = select(rule, session['bars'], session['previous'], date.fromisoformat(session['day']))
                row = dict(day=session['day'], year=session['year'])
                if entry:
                    index, side, risk = entry
                    row['trade'] = simulate(session['bars'], index, side, risk)
                    paths.append(dict(symbol=symbol, rule=rule, day=row['day'], **row['trade']))
                rows.append(row)
            yearly = {}
            for year in (2024, 2025, 2026):
                part = [r for r in rows if r['year'] == year]
                scheduled = sum(r['year'] == year for r in axis)
                summary = dict(signals=sum('trade' in r for r in part), known=len(part), scheduled=scheduled,
                               coverage=len(part)/scheduled if scheduled else 0, costs={})
                for scenario in ('base', 'stress'):
                    rounded = ledger(part, symbol, scenario, specs[symbol], True)
                    ideal = ledger(part, symbol, scenario, specs[symbol], False)
                    # Only fixed stress/2026 is inferential; no selection on base/year variants.
                    ci = intervals(rounded['fixed_daily_usd']) if scenario == 'stress' and year == 2026 else None
                    rounded.pop('fixed_daily_usd')
                    ideal.pop('fixed_daily_usd')
                    summary['costs'][scenario] = dict(rounded=rounded, fractional=ideal, bootstrap=ci)
                yearly[str(year)] = summary
            final = yearly['2026']
            stressed = final['costs']['stress']
            checks = dict(coverage=final['coverage'] >= .95, sample=stressed['rounded']['taken'] >= 100,
                          positive_all_years=all(y['costs']['stress']['rounded']['net_usd'] > 0 for y in yearly.values()),
                          multiplicity_lower_positive=bool(stressed['bootstrap'] and stressed['bootstrap']['familywise_lower'] > 0))
            entry = dict(symbol=symbol, rule=rule, yearly=yearly, cheap_gate=checks,
                         cheap_pass=all(checks.values()))
            result['candidates' if rule in RULES else 'controls'][symbol+':'+rule] = entry
        print(json.dumps(dict(completed=symbol, scheduled=len(axis), known=len(known), rules=27)), flush=True)
    result['total_modeled_trades_including_controls'] = len(paths)
    (HERE/'result_v1.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    (HERE/'trades_v1.json').write_text(json.dumps(paths, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    passes = [k for k, v in result['candidates'].items() if v['cheap_pass']]
    print(json.dumps(dict(candidates=96, passes=passes, production_allowed=False)))


if __name__ == '__main__':
    main()
