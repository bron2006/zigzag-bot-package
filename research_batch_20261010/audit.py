"""Separate Decimal ledgers and primitive price-path replay; offline only."""
from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import batch as b

D = lambda value: Decimal(str(value))


def check_path(trade, bars):
    entry, side = trade['entry'], trade['side']
    stop, target = trade['stop'], trade['target']
    index = next(i for i, bar in enumerate(bars) if bar['ts'] == trade['entry_ts'])
    assert index > 0
    assert bars[index]['ts'] == bars[index-1]['ts']+300
    assert abs(1.5*bars[index-1]['atr']-trade['risk']) < 1e-8
    assert entry == bars[index]['Open']
    assert abs(stop-(entry-side*trade['risk'])) < 1e-8
    assert abs(target-(entry+side*2*trade['risk'])) < 1e-8
    exit_price, exited, reason = bars[-1]['Close'], bars[-1]['ts'], 'close'
    marks, bads = [], []
    for bar in bars[index:]:
        adverse_open = bar['Open'] <= stop if side == 1 else bar['Open'] >= stop
        touched_stop = bar['Low'] <= stop if side == 1 else bar['High'] >= stop
        touched_target = bar['High'] >= target if side == 1 else bar['Low'] <= target
        if adverse_open or touched_stop or touched_target:
            exit_price = bar['Open'] if adverse_open else stop if touched_stop else target
            reason = 'gap' if adverse_open else 'stop' if touched_stop else 'target'
            exited = bar['ts']
            bad = exit_price if adverse_open or touched_stop else bar['Low'] if side == 1 else bar['High']
            bad = max(bad, stop) if side == 1 and not adverse_open else min(bad, stop) if side == -1 and not adverse_open else bad
            marks.append([side*(exit_price-entry), exit_price])
            bads.append([side*(bad-entry), bad])
            break
        marks.append([side*(bar['Close']-entry), bar['Close']])
        bad = bar['Low'] if side == 1 else bar['High']
        bads.append([side*(bad-entry), bad])
    assert (exit_price, exited, reason) == (trade['exit'], trade['exit_bar_ts'], trade['reason'])
    assert abs(side*(exit_price-entry)-trade['gross']) < 1e-8
    assert marks == trade['marks'] and bads == trade['adverse']


def decimal_ledger(trades, spec, symbol, scenario, rounded):
    charge = (D(2) if scenario == 'base' else D(5)) if symbol == 'USTEC' else (D(2) if scenario == 'base' else D(4))*(D('.01') if symbol == 'USDJPY' else D('.0001'))
    balance, taken = D(1000), 0
    fixed_total = D(0)
    for trade in trades:
        risk, stop, entry, exit_price, gross = (D(trade[k]) for k in ('risk', 'stop', 'entry', 'exit', 'gross'))
        per_unit_risk = (risk+charge)/stop if symbol == 'USDJPY' else risk+charge
        notional = D(1) if symbol == 'USDJPY' else entry
        def size_at(equity):
            size = min(equity/D(100)/per_unit_risk, equity*D(5)/notional, D(spec['maxVolume'])/D(100))
            if rounded:
                step = D(spec['stepVolume'])/D(100)
                size = (size/step).to_integral_value(rounding=ROUND_FLOOR)*step
                if size < D(spec['minVolume'])/D(100):
                    return D(0)
            return size
        size = size_at(balance)
        fixed = size_at(D(1000))
        unit_pnl = (gross-charge)/exit_price if symbol == 'USDJPY' else gross-charge
        fixed_total += fixed*unit_pnl
        if size:
            assert size*per_unit_risk <= balance/D(100)+D('1e-15')
            assert size*notional <= balance*D(5)+D('1e-15')
            balance += size*unit_pnl
            taken += 1
    return float(balance-D(1000)), taken, float(fixed_total)


def main():
    result = json.loads((b.HERE/'result_v1.json').read_text())
    paths = json.loads((b.HERE/'trades_v1.json').read_text())
    assert hashlib.sha256((b.HERE/'PROTOCOL.md').read_bytes()).hexdigest() == result['protocol_sha256'] == b.PROTOCOL_HASH
    metadata = json.loads((b.ROOT/'research_new_methods_20261007'/'broker_snapshot.json').read_text())
    specs = {r['name']: r['specification'] for r in metadata['symbols']}
    specs['USTEC'] = json.loads((b.ROOT/'research_nasdaq_pullback_20261010'/'cache'/'metadata.json').read_text())['specification']
    groups = defaultdict(list)
    for trade in paths:
        groups[(trade['symbol'], trade['rule'], trade['day'][:4])].append(trade)
    checked, ledgers = 0, 0
    for symbol in b.MARKETS:
        for filename, digest in result['sources'][symbol].items():
            folder = b.nasdaq.HERE/'cache' if symbol == 'USTEC' else b.fx.CACHE
            assert hashlib.sha256((folder/filename).read_bytes()).hexdigest() == digest
        if symbol == 'USTEC':
            rows, _, _ = b.nasdaq.load_history('M5')
            frame = b.pd.DataFrame(rows)
        else:
            frame, _ = b.fx.load_history(symbol)
        axis = {r['day']: r for r in b.session_axis(b.features(frame), symbol) if r['status'] == 'known'}
        for trade in (t for t in paths if t['symbol'] == symbol):
            session = axis[trade['day']]
            bars = session['bars']
            check_path(trade, bars)
            index = next(i for i, bar in enumerate(bars) if bar['ts'] == trade['entry_ts'])
            poisoned = {k: 999999. if isinstance(v, float) else v for k, v in bars[index].items()}
            altered = bars[:index]+[poisoned]*(len(bars)-index)
            selected = b.select(trade['rule'], altered, session['previous'], b.date.fromisoformat(trade['day']))
            assert selected and selected[:2] == (index, trade['side']) and abs(selected[2]-trade['risk']) < 1e-8
            checked += 1
        for rule in b.RULES+b.CONTROLS:
            item = (result['candidates'] if rule in b.RULES else result['controls'])[symbol+':'+rule]
            for year, summary in item['yearly'].items():
                trades = groups[(symbol, rule, year)]
                assert len(trades) == summary['signals']
                for scenario, values in summary['costs'].items():
                    for key, rounded in (('rounded', True), ('fractional', False)):
                        net, taken, fixed_total = decimal_ledger(trades, specs[symbol], symbol, scenario, rounded)
                        assert abs(net-values[key]['net_usd']) < 1e-6, (symbol, rule, year, scenario, key, net, values[key]['net_usd'])
                        assert taken == values[key]['taken']
                        if rounded and year == '2026' and scenario == 'stress':
                            ci = values['bootstrap']
                            assert abs(fixed_total/summary['known']-ci['mean']) < 1e-8
                            assert ci['familywise_lower'] <= ci['ci95'][0]
                        ledgers += 1
        print(json.dumps(dict(audit_completed=symbol)), flush=True)
    assert checked == result['total_modeled_trades_including_controls']
    output = dict(path_replays=checked, decimal_ledgers=ledgers, protocol_and_all_page_hashes_match=True,
                  every_modeled_entry_unchanged_by_poisoned_future=True,
                  shared_data_and_indicators=True, signal_rules_checked_by_synthetic_causality_tests_not_independent_oracle=True,
                  production_allowed=False)
    (b.HERE/'audit_v1.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output))


if __name__ == '__main__':
    main()
