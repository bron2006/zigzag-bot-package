"""Offline frozen-model diagnostic. No bot/config/db imports or execution."""
import ast
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
from typing import Optional
import warnings

import joblib
import numpy as np
import pandas as pd
import pandas_ta
from validate_broker_probe import decode_bar

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(__file__).parent
ARMS = (('EURUSD', 900), ('EURUSD', 300), ('GBPCHF', 300), ('AUDJPY', 300))


def feature_function():
    source = ast.parse((ROOT / 'analysis.py').read_text(encoding='utf-8-sig'))
    nodes = [n for n in source.body if
        (isinstance(n, ast.FunctionDef) and n.name == '_prepare_features') or
        (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
            {'MODEL_FEATURE_NAMES', 'FEATURE_SOURCE_MAP'} for t in n.targets))]
    namespace = {'pd': pd, 'Optional': Optional, 'logger': logging.getLogger('offline-contract')}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'exact-production-features', 'exec'), namespace)
    return namespace['_prepare_features']


def load_bars(symbol):
    raw = json.loads((FOLDER / 'vwap_replay_m5' / f'{symbol}.json').read_text(encoding='utf-8'))
    bars = [{**decode_bar(b), 'Volume': int(b['volume'])} for b in raw['raw_trendbars']]
    df = pd.DataFrame(bars).sort_values('start_minute').reset_index(drop=True)
    df['ts'] = df.pop('start_minute') * 60
    if df['ts'].duplicated().any() or not df['ts'].is_monotonic_increasing:
        raise ValueError('Invalid timestamps')
    return df


def to_m15(df):
    records = []
    for key, group in df.groupby(df['ts'] // 900):
        base = int(key) * 900
        if group['ts'].tolist() != [base, base + 300, base + 600]:
            continue
        records.append({'ts': base, 'Open': group.Open.iloc[0], 'High': group.High.max(),
            'Low': group.Low.min(), 'Close': group.Close.iloc[-1], 'Volume': group.Volume.sum()})
    return pd.DataFrame(records)


def endpoint(df, index, period, horizon=900):
    count = horizon // period
    if index + count >= len(df):
        return None
    expected = int(df.ts.iloc[index]) + np.arange(1, count + 1) * period
    if not np.array_equal(df.ts.iloc[index + 1:index + count + 1].to_numpy(), expected):
        return None
    return float(df.Close.iloc[index + count])


def day_interval(days, wins, counts, repeats=4000):
    grouped = defaultdict(lambda: [0., 0.])
    for day, won, count in zip(days, wins, counts, strict=True):
        grouped[day][0] += float(won)
        grouped[day][1] += float(count)
    a = np.array(list(grouped.values()), dtype=float)
    if len(a) < 2 or a[:, 1].sum() == 0:
        return None
    rng = np.random.default_rng(20261009)
    samples = a[rng.integers(0, len(a), size=(repeats, len(a)))].sum(axis=1)
    valid = samples[:, 1] > 0
    return [round(float(x), 4) for x in np.quantile(samples[valid, 0] / samples[valid, 1], [.025, .975])]


def summarize(probabilities, moves, days):
    p, move = np.asarray(probabilities), np.asarray(moves)
    nonflat = move != 0
    score = (p * 100).astype(int)
    selected = ((score > 75) | (score < 25)) & nonflat
    correct = (p > .5) == (move > 0)
    count = int(selected.sum())
    original = int(correct[selected].sum())
    always_up = (move > 0).astype(int)
    return {'all_nonflat': int(nonflat.sum()), 'all_original_accuracy': float(correct[nonflat].mean()) if nonflat.any() else None,
        'threshold_signals': count, 'ties': int((move == 0).sum()),
        'original_wins': original, 'deployed_inverted_wins': count - original,
        'original_rate': original / count if count else None,
        'deployed_inverted_rate': (count - original) / count if count else None,
        'always_up_rate_same_signals': float(always_up[selected].mean()) if count else None,
        'always_down_rate_same_signals': float(1 - always_up[selected].mean()) if count else None,
        'original_day_cluster_ci95': day_interval(days, correct.astype(int) * selected, selected),
        'original_excess_over_always_up_day_cluster_ci95': day_interval(days, (correct.astype(int) - always_up) * selected, selected),
        'signal_days': len(set(np.asarray(days)[selected])),
        'below25': int(((score < 25) & nonflat).sum()), 'above75': int(((score > 75) & nonflat).sum())}


def main():
    model = joblib.load(ROOT / 'lgbm_model.pkl')
    scaler = joblib.load(ROOT / 'lgbm_scaler.pkl')
    model.set_params(n_jobs=1)  # only inference scheduling; never write the model
    features = feature_function()
    names = list(scaler.feature_names_in_)
    training = pd.read_csv(ROOT / 'data' / 'EURUSD_15m_history.csv').iloc[:11040][names]
    lower, upper = training.min().to_numpy(), training.max().to_numpy()
    report = {'retrospective': True, 'prospective_OOS': False, 'no_profit_claim': True,
        'full_live_strategy': False, 'horizon_seconds': 900, 'window_bars': 300,
        'model_sha256': hashlib.sha256((ROOT / 'lgbm_model.pkl').read_bytes()).hexdigest(),
        'scaler_sha256': hashlib.sha256((ROOT / 'lgbm_scaler.pkl').read_bytes()).hexdigest(),
        'analysis_sha256': hashlib.sha256((ROOT / 'analysis.py').read_bytes()).hexdigest(), 'arms': []}
    for symbol, period in ARMS:
        print(f'Calculating {symbol} M{period//60}, past bars only...', flush=True)
        df = load_bars(symbol)
        if period == 900:
            df = to_m15(df)
        matrix, moves, days = [], [], []
        missing = 0
        for i in range(249, len(df)):
            future = endpoint(df, i, period)
            if future is None:
                missing += 1
                continue
            feature = features(df.iloc[max(0, i - 299):i + 1])
            if feature is None:
                raise ValueError('Feature failure: do not silently discard observations')
            matrix.append(feature[names].iloc[0].to_numpy())
            moves.append(future - float(df.Close.iloc[i]))
            days.append(datetime.fromtimestamp(int(df.ts.iloc[i]) + period, timezone.utc).date().isoformat())
        frame = pd.DataFrame(matrix, columns=names)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=FutureWarning)
            probabilities = model.predict_proba(scaler.transform(frame))[:, list(model.classes_).index(1)]
        result = {'symbol': symbol, 'period': period, 'bars': len(df), 'missing_future': missing,
            'first_bar_utc': datetime.fromtimestamp(int(df.ts.iloc[0]), timezone.utc).isoformat(),
            'last_bar_utc': datetime.fromtimestamp(int(df.ts.iloc[-1]), timezone.utc).isoformat(),
            'outside_training_feature_range_fraction': float(((frame.to_numpy() < lower) | (frame.to_numpy() > upper)).any(axis=1).mean()),
            **summarize(probabilities, moves, days)}
        report['arms'].append(result)
        print(json.dumps(result), flush=True)
    (FOLDER / 'model_contract_result_v1.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
