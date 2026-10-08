"""Offline partial-holding controls. No bot imports, credentials or orders."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from daily_trend import load_history, simulate, SYMBOLS


def log_returns(curve):
    curve = np.asarray(curve, dtype=float)
    if not len(curve) or not np.isfinite(curve).all() or (curve <= 0).any():
        raise ValueError("Equity must be finite and positive")
    return np.diff(np.log(np.r_[1., curve]))


def calibrate(early):
    _, trend = simulate(early, .001)
    _, hold = simulate(early, .001, hold=True)
    denominator = log_returns(hold).std(ddof=1)
    if denominator <= 0:
        raise ValueError("Calibration hold volatility must be positive")
    return dict(exposure=float(early.position.mean()),
                volatility=float(np.clip(log_returns(trend).std(ddof=1)/denominator, 0, 1)))


def partial(hold_curve, fraction):
    if not 0 <= fraction <= 1:
        raise ValueError("Fraction outside [0, 1]")
    return 1-fraction+fraction*np.asarray(hold_curve)


def metrics(curve):
    n = len(curve)
    peak = np.maximum.accumulate(np.r_[1., curve])[1:]
    return dict(total_return=float(curve[-1]-1),
                annualized_return=float(curve[-1]**(365.25/n)-1),
                max_drawdown=float(np.min(curve/peak-1)),
                annualized_log_volatility=float(log_returns(curve).std(ddof=1)*np.sqrt(365.25)))


def bootstrap(differences, repetitions=10000, block=30, seed=20261007):
    values = np.asarray(differences)
    n = len(values)
    if n < block:
        raise ValueError("Sample shorter than block")
    rng = np.random.default_rng(seed)
    estimates = []
    for first in range(0, repetitions, 250):
        size = min(250, repetitions-first)
        starts = rng.integers(0, n-block+1, (size, (n+block-1)//block))
        indices = (starts[..., None]+np.arange(block)).reshape(size, -1)[:, :n]
        estimates.append(values[indices].mean(axis=1)*365.25)
    estimates = np.concatenate(estimates)
    return np.quantile(estimates, [.00625, .99375], axis=0).T


def main():
    root = Path(__file__).parent
    directory = root/'public_daily'
    records, rows, differences = [], [], []
    for symbol in SYMBOLS:
        path = directory/f'{symbol}_1d.json'
        history = load_history(path)
        early = history[(history.date >= '2020-01-01') & (history.date < '2024-01-01')]
        late = history[history.date >= '2024-01-01']
        weights = calibrate(early)
        record = dict(symbol=symbol, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      initial_fractions=weights, costs={})
        for fee in (.001, .003):
            _, trend = simulate(late, fee)
            _, hold = simulate(late, fee, hold=True)
            curves = dict(trend=trend, full_hold=hold,
                          exposure_partial=partial(hold, weights['exposure']),
                          volatility_partial=partial(hold, weights['volatility']))
            record['costs'][str(fee)] = {name: metrics(curve) for name, curve in curves.items()}
            for name, curve in curves.items():
                rows.extend(dict(symbol=symbol, fee=fee, model=name, date=str(date.date()), equity=float(value))
                            for date, value in zip(late.date, curve))
            if fee == .001:
                for name in ('exposure_partial', 'volatility_partial'):
                    differences.append(log_returns(trend)-log_returns(curves[name]))
        records.append(record)
    bounds = bootstrap(np.column_stack(differences))
    for i, record in enumerate(records):
        comparisons = {}
        for j, name in enumerate(('exposure_partial', 'volatility_partial')):
            k = 2*i+j
            comparisons[name] = dict(annualized_mean_log_excess=float(np.mean(differences[k])*365.25),
                                     simultaneous_interval=bounds[k].tolist())
        record['base_comparisons'] = comparisons
        stress = record['costs']['0.003']
        record['further_research_gate'] = bool(
            all(item['simultaneous_interval'][0] > 0 for item in comparisons.values())
            and stress['trend']['total_return'] > 0
            and all(stress['trend']['max_drawdown'] > stress[name]['max_drawdown']
                    for name in comparisons))
    result = dict(protocol_sha256=hashlib.sha256((root/'EXPOSURE_PROTOCOL.md').read_bytes()).hexdigest(),
                  evaluation_start='2024-01-01', evaluation_end='2026-09-30',
                  bootstrap_repetitions=10000, block_days=30, individual_coverage=.9875,
                  controls_are_initial_allocations_not_exact_risk_matches=True,
                  results=records, both_assets_pass=all(r['further_research_gate'] for r in records))
    (directory/'exposure_summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    pd.DataFrame(rows).to_csv(directory/'exposure_equity.csv', index=False)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
