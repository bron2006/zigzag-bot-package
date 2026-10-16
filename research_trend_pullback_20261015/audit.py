"""Independent Decimal exit/cash replay; never imports runtime configuration."""
from decimal import Decimal as D
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pullback_audit_run', HERE / 'run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def main():
    audit = {}
    for symbol, filename in [('EURUSD', 'result.json'), ('GBPUSD', 'result_GBPUSD.json')]:
        report = json.loads((HERE / filename).read_text('utf-8'))
        raw, hashes, _ = runner.wf.load(symbol)
        assert hashes == report['input_hashes']
        bars = {int(b['ts']): b for b in raw.to_dict('records')}
        count = 0
        error = 0
        assert [r['entry_ts'] for r in report['scenarios']['base']['rows']] == [
            r['entry_ts'] for r in report['scenarios']['stress']['rows']]
        for scenario, arm in report['scenarios'].items():
            cost = D('.0002' if scenario == 'base' else '.0004')
            previous_exit = -1
            by_entry = {}
            for row in arm['rows']:
                assert row['status'] == 'closed'
                assert row['entry_ts'] >= previous_exit
                assert row['entry_ts'] == row['decision_ts'] + 300
                side = D(row['side'])
                entry = D(str(bars[row['entry_ts']]['Open']))
                distance = D(str(row['stop_distance']))
                stop = entry - side * distance
                target = entry + side * 2 * distance
                assert abs(stop - D(str(row['stop']))) < D('1e-12')
                price = reason = None
                for ts in range(row['entry_ts'], row['entry_ts'] + 14400, 300):
                    b = bars[ts]
                    o, high, low = [D(str(b[k])) for k in ('Open', 'High', 'Low')]
                    if side * (o - stop) <= 0:
                        price, reason = o, 'gap_stop'
                    elif low <= stop if side == 1 else high >= stop:
                        price, reason = stop, 'stop'
                    elif high >= target if side == 1 else low <= target:
                        price, reason = target, 'target'
                    if price is not None:
                        break
                if price is None:
                    price, reason = D(str(b['Close'])), 'deadline'
                assert reason == row['reason'] and ts + 300 == row['exit_ts']
                assert abs(price - D(str(row['exit']))) < D('1e-12')
                net = (side * (price - entry) - cost) / (distance + cost)
                error = max(error, abs(float(net) - row['net_R']))
                assert error < 1e-10
                by_entry[row['entry_ts']] = (side, entry, price)
                previous_exit = row['exit_ts']
                count += 1
            balance = D('1000')
            for trade in arm['projection']['trades']:
                side, entry, price = by_entry[trade['entry_ts']]
                pnl = D(str(trade['units'])) * (side * (price - entry) - cost)
                balance += pnl
                assert abs(float(pnl) - trade['pnl']) < 1e-8
                assert abs(float(balance) - trade['balance']) < 1e-8
            assert abs(float(balance) - arm['projection']['end_usd']) < 1e-8
        for name, digest in report['original_hashes'].items():
            assert hashlib.sha256((HERE.parent / name).read_bytes()).hexdigest() == digest
        audit[symbol] = dict(scenario_rows_replayed=count, max_R_error=error,
                             inputs_and_original_models_unchanged=True, cash_matches=True)
    (HERE / 'audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    print(json.dumps(audit))


if __name__ == '__main__':
    main()
