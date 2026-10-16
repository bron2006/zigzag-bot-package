"""Second state-machine implementation; replays every session offline.

Shares only cache decoding and calendar with screen, NOT entry/exit/ATR logic.
Thus not an independent data source or external strategy verification.
"""
import json
import math
from datetime import datetime, timezone
from statistics import median
import screen as s


def oracle(bars, daily):
    eligible = []
    for b in daily:
        completed = b['ts']+86400
        if completed <= bars[0]['ts'] and datetime.fromtimestamp(completed, timezone.utc).weekday() < 5:
            eligible.append(b)
    window = eligible[-15:]
    if len(window) < 15 or any(window[i]['ts']-window[i-1]['ts'] > 432000 for i in range(1, 15)):
        return 'missing_atr', None
    atr = sum(max(window[i]['High'], window[i-1]['Close'])-
              min(window[i]['Low'], window[i-1]['Close']) for i in range(1, 15))/14
    anchor = bars[0]['Open']
    side, intent, entry_index = 0, None, None
    status = 'no_breakout'
    for i, b in enumerate(bars):
        end = datetime.fromtimestamp(b['ts']+300, s.NY)
        if not side:
            if (end.hour*60+end.minute) not in range(585, 901, 15):
                continue
            if abs(b['Close']-anchor) <= atr/2:
                continue
            side = 1 if b['Close'] > anchor else -1
            intent = b['ts']+300
            status = 'expired_intent'
            continue
        if b['ts']+300 > intent+1800:
            break
        if side*(b['Close']-anchor) <= atr/2:
            status = 'cancelled_reentry'
            break
        if side*(b['Close']-b['Open']) >= 0:
            continue
        if i+1 == len(bars):
            break
        if side*(bars[i+1]['Open']-anchor) <= atr/2:
            status = 'cancelled_entry_gap'
            break
        entry_index = i+1
        status = 'trade'
        break
    if status != 'trade':
        return status, None
    entry = bars[entry_index]['Open']
    marks, adverse = [], []
    exit_price, exit_ts, exit_reason = bars[-1]['Close'], bars[-1]['ts']+300, 'session_close'
    for b in bars[entry_index:]:
        if side*(b['Open']-anchor) <= 0:
            exit_price, exit_ts, exit_reason = b['Open'], b['ts'], 'stop_gap'
        elif (b['Low'] <= anchor if side == 1 else b['High'] >= anchor):
            exit_price, exit_ts, exit_reason = anchor, b['ts'], 'stop'
        else:
            marks.append(side*(b['Close']-entry))
            adverse.append(side*((b['Low'] if side == 1 else b['High'])-entry))
            continue
        marks.append(side*(exit_price-entry))
        adverse.append(side*(exit_price-entry))
        break
    return status, dict(atr=atr, anchor=anchor, direction=side, intent_ts=intent,
        entry_ts=bars[entry_index]['ts'], entry=entry, stop=anchor, risk_points=abs(entry-anchor),
        exit=exit_price, exit_ts=exit_ts, exit_reason=exit_reason,
        gross_points=side*(exit_price-entry), mark_points=marks, adverse_mark_points=adverse,
        adverse_points=min([0.]+adverse))


def main():
    m5, _, _ = s.load_history('M5')
    daily, _, _ = s.load_history('D1')
    by_ts = {b['ts']: b for b in m5}
    rows = json.loads((s.HERE/'sessions_v1.json').read_text())
    for row in rows:
        times = s.session_timestamps(s.date.fromisoformat(row['day']))
        if not all(t in by_ts for t in times):
            assert row['status'] == 'missing_session'
            continue
        status, expected = oracle([by_ts[t] for t in times], daily)
        assert status == row['status'], (row['day'], status, row['status'])
        if expected:
            for key, value in expected.items():
                actual = row[key]
                if isinstance(value, float):
                    assert math.isclose(value, actual, abs_tol=1e-8), (row['day'], key)
                else:
                    assert value == actual, (row['day'], key)
    result = json.loads((s.HERE/'result_v1.json').read_text())
    for year, summary in result['yearly'].items():
        trades = [r for r in rows if str(r['year']) == year and r['status'] == 'trade']
        for scenario in summary['cost_scenarios'].values():
            cost = scenario['assumed_round_trip_points']
            assert math.isclose(sum(t['gross_points']-cost for t in trades), scenario['sum_net_points'], abs_tol=1e-8)
            balance = 1000.
            for trade in trades:
                size = balance*.01/(trade['risk_points']+cost)
                assert size*trade['entry'] <= balance*5
                assert size <= 250  # current maxVolume / 100; not binding in this sample
                balance += size*(trade['gross_points']-cost)
            assert math.isclose(balance, scenario['fractional_account']['ending_usd'], abs_tol=1e-8)
            assert scenario['rounded_account']['trades_taken'] == 0
    risks = [.1*(r['risk_points']+5) for r in rows if r['status'] == 'trade']
    output = dict(all_sessions_replayed=len(rows), all_trades_replayed=len(risks),
                  state_machine_match=True, yearly_cost_and_fractional_balances_match=True,
                  current_minimum_contract_stress_stop_usd=dict(min=min(risks), median=median(risks), max=max(risks)),
                  shared_source_and_calendar=True, production_allowed=False)
    (s.HERE/'audit_v1.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
