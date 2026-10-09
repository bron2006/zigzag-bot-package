"""Isolated, deterministic research. No config/db/broker imports or orders."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from model_contract_probe import load_bars, day_interval

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parent
SYMBOLS = ('EURUSD', 'GBPCHF', 'AUDJPY')
NAMES = ['ret1', 'ret3', 'ret12', 'body', 'range', 'vol', 'ema20_dist', 'ema50_dist']
TRAIN_END = int(datetime(2026, 9, 16, tzinfo=timezone.utc).timestamp())
VALID_END = int(datetime(2026, 9, 23, tzinfo=timezone.utc).timestamp())


def features(bars):
    """Prefix-stable; restart indicators after every non-contiguous interval."""
    if bars.empty:
        return pd.DataFrame(columns=NAMES, index=bars.index, dtype=float)
    if bars.ts.duplicated().any() or not bars.ts.is_monotonic_increasing:
        raise ValueError('Bars must have unique increasing timestamps')
    prices = bars[['Open', 'High', 'Low', 'Close']]
    if (not np.isfinite(prices).all().all() or (prices <= 0).any().any()
            or (bars.High < prices.max(axis=1)).any()
            or (bars.Low > prices.min(axis=1)).any()):
        raise ValueError('Invalid OHLC')
    parts = []
    groups = bars.ts.diff().ne(300).cumsum()
    for _, frame in bars.groupby(groups):
        close = frame.Close
        ret = close.pct_change(fill_method=None)
        vol = ret.rolling(20, min_periods=20).std(ddof=0)
        scale = (vol * close).replace(0, np.nan)
        out = pd.DataFrame(index=frame.index)
        for length in (1, 3, 12):
            out[f'ret{length}'] = close.pct_change(length, fill_method=None)
        out['body'] = (close - frame.Open) / (frame.High - frame.Low).replace(0, np.nan)
        out['range'] = (frame.High - frame.Low) / close
        out['vol'] = vol
        for length in (20, 50):
            out[f'ema{length}_dist'] = (close - close.ewm(span=length, adjust=False).mean()) / scale
        out.iloc[:199] = np.nan
        parts.append(out)
    return pd.concat(parts).sort_index()[NAMES]


def dataset(symbol):
    bars = load_bars(symbol)
    x = features(bars)
    contiguous = bars.ts.shift(-1).eq(bars.ts + 300)
    x['move'] = bars.Close.shift(-1) - bars.Close
    x['momentum'] = np.sign(bars.Close - bars.Open)
    x['decision_ts'] = bars.ts + 300
    x['target_ts'] = bars.ts + 600
    x['symbol'] = symbol
    return x.loc[contiguous & np.isfinite(x[NAMES]).all(axis=1)].copy()


def split_masks(frame):
    return {
        'train': (frame.decision_ts < TRAIN_END) & (frame.target_ts < TRAIN_END),
        'validation': (frame.decision_ts >= TRAIN_END) & (frame.decision_ts < VALID_END)
            & (frame.target_ts < VALID_END),
        'test': frame.decision_ts >= VALID_END,
    }


def payoff(direction, moves, payout):
    direction, moves = np.asarray(direction), np.asarray(moves)
    # Flat is a hypothetical refund; baseline WAIT also zero, never a win.
    return np.where((moves == 0) | (direction == 0), 0.,
                    np.where(direction * moves > 0, payout, -1.))


def evaluate(model, frame):
    p = model.predict_proba(frame[NAMES])[:, list(model.classes_).index(1)]
    selected = (p >= .55) | (p <= .45)
    chosen = frame.loc[selected]
    direction = np.where(p[selected] >= .55, 1, -1)
    moves = chosen.move.to_numpy()
    days = pd.to_datetime(chosen.decision_ts, unit='s', utc=True).dt.strftime('%Y-%m-%d').to_numpy()
    n = len(chosen)
    decided = moves != 0
    result = {'observations': len(frame), 'selected': n, 'decided': int(decided.sum()),
        'first_decision_utc': datetime.fromtimestamp(int(frame.decision_ts.min()), timezone.utc).isoformat(),
        'last_target_utc': datetime.fromtimestamp(int(frame.target_ts.max()), timezone.utc).isoformat(),
        'flat_refunds_assumed': int((~decided).sum()), 'days': len(set(days)),
        'buy': int((direction == 1).sum()), 'sell': int((direction == -1).sum()),
        'wins': int((direction * moves > 0).sum()),
        'winrate': float((direction[decided] * moves[decided] > 0).mean()) if decided.any() else None,
        'payout_scenarios': {}, 'baseline_advantage_ci95_at80': {}}
    if not n:
        return result
    counts = np.ones(n)
    for payout in (.7, .8, .9):
        values = payoff(direction, moves, payout)
        result['payout_scenarios'][str(payout)] = {'mean_units': float(values.mean()),
            'day_ci95': day_interval(days, values, counts)}
    values = payoff(direction, moves, .8)
    for name, base in [('always_up', np.ones(n)), ('always_down', -np.ones(n)),
                       ('candle_momentum', chosen.momentum.to_numpy())]:
        baseline = payoff(base, moves, .8)
        result['baseline_advantage_ci95_at80'][name] = day_interval(days, values - baseline, counts)
    return result


def passes_gate(validation, test):
    val = validation['payout_scenarios'].get('0.8')
    final = test['payout_scenarios'].get('0.8')
    baselines = test.get('baseline_advantage_ci95_at80', {})
    return bool(val and final and test['decided'] >= 200 and test['days'] >= 10
        and val['mean_units'] > 0 and final['day_ci95'] and final['day_ci95'][0] > 0
        and set(baselines) == {'always_up', 'always_down', 'candle_momentum'}
        and all(ci and ci[0] > 0 for ci in baselines.values()))


def main():
    originals = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                 for name in ('lgbm_model.pkl', 'lgbm_scaler.pkl')}
    frame = pd.concat([dataset(symbol) for symbol in SYMBOLS], ignore_index=True)
    frame = frame.sort_values(['decision_ts', 'symbol']).reset_index(drop=True)
    masks = split_masks(frame)
    train = frame.loc[masks['train'] & frame.move.ne(0)]
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1., solver='lbfgs', max_iter=2000))
    model.fit(train[NAMES], (train.move > 0).astype(int))
    results = {name: evaluate(model, frame.loc[mask]) for name, mask in masks.items()}
    accepted = passes_gate(results['validation'], results['test'])
    report = {'status': 'paper_candidate_only' if accepted else 'rejected',
        'prospective_OOS': False, 'production_changed': False, 'orders': 0,
        'horizon_seconds': 300, 'features': NAMES, 'symbols': SYMBOLS,
        'training_rows_nonflat': len(train), 'results': results,
        'library_versions': {name: importlib.metadata.version(name) for name in ('numpy', 'pandas', 'scikit-learn', 'joblib')},
        'protocol_sha256': hashlib.sha256((FOLDER / 'NORMALIZED_SIGNAL_PROTOCOL.md').read_bytes()).hexdigest(),
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'original_model_hashes': originals, 'data_exclusions': {
            symbol: {'raw_bars': len(load_bars(symbol)), 'usable': int(frame.symbol.eq(symbol).sum()),
                     'reason': 'minimum200 contiguous warmup, finite features, contiguous future endpoint'}
            for symbol in SYMBOLS},
        'cache_hashes': {symbol: hashlib.sha256((FOLDER / 'vwap_replay_m5' / f'{symbol}.json').read_bytes()).hexdigest()
                         for symbol in SYMBOLS}}
    artifact = FOLDER / 'normalized_signal_candidate_v1.pkl'
    joblib.dump({'model': model, 'features': NAMES, 'horizon_seconds': 300,
                 'status': report['status'], 'production_allowed': False}, artifact)
    report['candidate_sha256'] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    for name, original in originals.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != original:
            raise RuntimeError('Production model unexpectedly changed')
    (FOLDER / 'normalized_signal_result_v1.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
