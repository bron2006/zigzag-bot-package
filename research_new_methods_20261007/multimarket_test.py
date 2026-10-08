"""Offline fixed monthly CFD trend pilot. No credentials/network/bot imports."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from validate_broker_probe import decode_bar

NAMES = ('EURUSD', 'US500', 'XAUUSD', 'XTIUSD')


def monthly_prices(raw):
    series = {}
    for history in raw['histories']:
        records = []
        seen = set()
        for bar in history['raw_trendbars']:
            decoded = decode_bar(bar)
            timestamp = decoded['start_minute']
            if timestamp in seen:
                raise ValueError('Duplicate raw timestamp')
            seen.add(timestamp)
            session = datetime.fromtimestamp(timestamp*60, tz=timezone.utc)+timedelta(hours=12)
            # Sep 30 session is included; session beginning Sep 30 21 UTC is Oct 1 and excluded.
            if session.date().isoformat() >= '2026-10-01':
                continue
            records.append((pd.Period(session.date(), freq='M'), timestamp, decoded['Close']))
        table = pd.DataFrame(records, columns=['month', 'timestamp', 'Close']).sort_values('timestamp')
        series[history['name']] = table.groupby('month').Close.last()
    prices = pd.DataFrame(series).reindex(columns=NAMES)
    required = pd.period_range('2017-08', '2026-09', freq='M')
    prices = prices.reindex(required)
    if prices.isna().any().any() or (prices <= 0).any().any():
        raise ValueError('Incomplete common monthly history')
    return prices


def model_weights(prices):
    returns = prices.pct_change(fill_method=None)
    signal = sum(np.sign(prices/prices.shift(h)-1) for h in (1, 3, 12))/3
    volatility = returns.rolling(36, min_periods=36).std(ddof=1)*np.sqrt(12)
    size = (.10/(4*volatility)).clip(upper=.25)
    # One full month buffer between information and execution.
    weights = (signal*size).shift(2)
    return returns, weights


def simulate(returns, weights, fee, drag):
    if not np.isfinite(weights).all() or not np.isfinite(returns).all():
        raise ValueError('Nonfinite simulation inputs')
    if np.any(np.abs(weights).sum(axis=1) > 1+1e-12):
        raise ValueError('Leverage not allowed')
    equity, previous, previous_returns, previous_factor = 1., np.zeros(returns.shape[1]), None, 1.
    curve, factors, turnover_values = [], [], []
    for current_returns, target in zip(returns, weights):
        drifted = previous if previous_returns is None else previous*(1+previous_returns)/previous_factor
        turnover = np.abs(target-drifted).sum()
        net = target@current_returns - fee*turnover - drag*np.abs(target).sum()/12
        factor = 1+net
        if factor <= 0:
            raise ValueError('Insolvent monthly model')
        equity *= factor
        curve.append(equity)
        factors.append(factor)
        turnover_values.append(turnover)
        previous, previous_returns, previous_factor = target, current_returns, factor
    terminal_drift = previous*(1+previous_returns)/previous_factor
    terminal_turnover = np.abs(terminal_drift).sum()
    liquidation_factor = 1-fee*terminal_turnover
    if liquidation_factor <= 0:
        raise ValueError('Insolvent liquidation')
    curve[-1] *= liquidation_factor
    factors[-1] *= liquidation_factor
    peak = np.maximum.accumulate(np.r_[1., curve])[1:]
    factors = np.asarray(factors)
    return dict(total_return=float(curve[-1]-1), cagr=float(curve[-1]**(12/len(curve))-1),
                monthly_close_max_drawdown=float(np.min(np.asarray(curve)/peak-1)),
                annualized_volatility=float(np.std(factors-1, ddof=1)*np.sqrt(12)),
                average_gross_exposure=float(np.abs(weights).sum(axis=1).mean()),
                total_turnover=float(sum(turnover_values)+terminal_turnover)), np.asarray(curve), factors


def paired_interval(difference, repetitions=10000):
    rng = np.random.default_rng(20261008)
    n, block = len(difference), 3
    starts = rng.integers(0, n-block+1, (repetitions, (n+block-1)//block))
    indices = (starts[..., None]+np.arange(block)).reshape(repetitions, -1)[:, :n]
    values = np.asarray(difference)[indices].mean(axis=1)*12
    return np.quantile(values, [.025, .975]).tolist()


def break_even_drag(returns, weights, fee):
    at_zero, _, _ = simulate(returns, weights, fee, 0)
    if at_zero['total_return'] <= 0:
        return None
    low, high = 0., .12
    at_high, _, _ = simulate(returns, weights, fee, high)
    if at_high['total_return'] > 0:
        return dict(above_tested_limit=.12)
    for _ in range(40):
        middle = (low+high)/2
        result, _, _ = simulate(returns, weights, fee, middle)
        if result['total_return'] > 0:
            low = middle
        else:
            high = middle
    return (low+high)/2


def main():
    root = Path(__file__).parent
    path = root/'broker_history_probe.json'
    prices = monthly_prices(json.loads(path.read_text(encoding='utf-8')))
    returns, weights = model_weights(prices)
    output = dict(protocol_sha256=hashlib.sha256((root/'MULTIMARKET_PROTOCOL.md').read_bytes()).hexdigest(),
                  source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  model='monthly_weight_approximation_not_broker_execution', historical_costs_known=False,
                  blocks={})
    scenarios = [('gross', 0, 0), ('turnover_only', .001, 0)]
    scenarios += [(f'base_drag_{d}', .001, d/100) for d in (3, 6, 12)]
    scenarios += [(f'stress_drag_{d}', .003, d/100) for d in (0, 3, 6, 12)]
    for label, first, last in (('early', '2021-01', '2022-12'), ('late', '2023-01', '2026-09')):
        r, w = returns.loc[first:last], weights.loc[first:last]
        rv, wv = r.to_numpy(), w.to_numpy()
        block = dict(months=len(r), scenarios={})
        block['zero_total_return_drag_threshold'] = {
            'base_turnover': break_even_drag(rv, wv, .001),
            'stress_turnover': break_even_drag(rv, wv, .003)}
        for scenario, fee, drag in scenarios:
            result = {}
            model_arrays = dict(trend=wv, matched_long=np.abs(wv), equal_long=np.full_like(wv, .25))
            all_factors = {}
            for name, array in model_arrays.items():
                metrics, curve, factors = simulate(rv, array, fee, drag)
                annual = {}
                for year in sorted(set(r.index.year)):
                    annual[str(year)] = float(np.prod(factors[r.index.year == year])-1)
                metrics['calendar_year_returns'] = annual
                metrics['monthly_equity'] = curve.tolist()
                result[name] = metrics
                all_factors[name] = factors
            if scenario == 'stress_drag_6':
                difference = np.log(all_factors['trend'])-np.log(all_factors['matched_long'])
                result['paired_annualized_log_excess_interval'] = paired_interval(difference)
                result['component_returns'] = {}
                for i, name in enumerate(NAMES):
                    metrics, _, _ = simulate(rv[:, i:i+1], wv[:, i:i+1], fee, drag)
                    result['component_returns'][name] = metrics['total_return']
            block['scenarios'][scenario] = result
        output['blocks'][label] = block
    stress = output['blocks']['late']['scenarios']['stress_drag_6']
    output['further_research_gate'] = bool(stress['trend']['total_return'] > 0
        and stress['trend']['total_return'] > stress['matched_long']['total_return']
        and stress['paired_annualized_log_excess_interval'][0] > 0
        and sum(v > 0 for v in stress['component_returns'].values()) >= 3)
    (root/'multimarket_results.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    for label, block in output['blocks'].items():
        for scenario, result in block['scenarios'].items():
            print(json.dumps(dict(block=label, scenario=scenario,
                trend_return=result['trend']['total_return'], trend_cagr=result['trend']['cagr'],
                trend_dd=result['trend']['monthly_close_max_drawdown'],
                matched_long_return=result['matched_long']['total_return'],
                equal_long_return=result['equal_long']['total_return'])))
    print(json.dumps(dict(gate=output['further_research_gate'],
                         stress_components=stress['component_returns'],
                         stress_interval=stress['paired_annualized_log_excess_interval'])))


if __name__ == '__main__':
    main()
