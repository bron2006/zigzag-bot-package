"""Offline descriptive analysis; no blacklists, thresholds or DB changes."""
import ast
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


def wilson(wins, n, z=1.959963984540054):
    if not n:
        return None
    p = wins/n
    denom = 1+z*z/n
    middle = (p+z*z/(2*n))/denom
    half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
    return [(middle-half)*100, (middle+half)*100]


def direction(row):
    if row['outcome'] not in ('up_timed', 'down_timed', 'flat_timed'):
        return None
    entry, exit_price = row['entry_price'], row['exit_price']
    if row['verdict'] not in ('BUY', 'SELL') or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (entry, exit_price)):
        return None
    return (exit_price > entry) if row['verdict'] == 'BUY' else (exit_price < entry)


def stats(rows):
    decided = [r for r in rows if direction(r) is not None]
    wins = sum(direction(r) for r in decided)
    n = len(decided)
    ties = sum(r['exit_price'] == r['entry_price'] for r in decided)
    result = dict(total=len(rows), measured=n, wins=wins, losses=n-wins, ties_counted_as_losses=ties,
                  winrate=100*wins/n if n else None, wilson95_independence_assumption=wilson(wins, n),
                  unknown=sum(r['outcome'] == 'unknown' for r in rows),
                  legacy_unverified=sum(r['outcome'] in ('up', 'down', 'flat', 'tp', 'sl', 'timeout') for r in rows),
                  measured_utc_days=len({r['entry_ts'][:10] for r in decided}),
                  by_direction={}, by_day={})
    for side in ('BUY', 'SELL'):
        part = [r for r in decided if r['verdict'] == side]
        result['by_direction'][side] = dict(n=len(part), wins=sum(direction(r) for r in part))
    for day in sorted({r['entry_ts'][:10] for r in decided}):
        part = [r for r in decided if r['entry_ts'][:10] == day]
        result['by_day'][day] = dict(n=len(part), wins=sum(direction(r) for r in part))
    result['hypothetical_return_per_unit_stake'] = {
        str(payout): (payout*wins-(n-wins))/n if n else None for payout in (.7, .8, .9)}
    return result


def main():
    snapshot_path = HERE/'snapshot.json'
    data = json.loads(snapshot_path.read_text())
    now = datetime.fromisoformat(data['snapshot_utc'].rstrip('Z'))
    signals, trades = data['signals'], data['binomo_trades']
    report = dict(snapshot_utc=data['snapshot_utc'], readonly=True,
                  raw_snapshot_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                  independence_CIs_not_cluster_adjusted=True,
                  current_actual_execution_profit_verified=False,
                  signal_statistics_not_profit=True, watchlist=data['owner_db_watchlist'], periods={})
    # Reuse exact production aggregate by AST, NOT by importing db/schema.
    source = ast.parse((HERE.parent/'db.py').read_text(encoding='utf-8-sig'))
    nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and
             n.name in ('_binomo_style_direction', '_aggregate_signal_outcomes_binomo_style')]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'production-aggregate', 'exec'), namespace)
    aggregate = namespace['_aggregate_signal_outcomes_binomo_style']
    for days in (7, 30, 365):
        rows = [r for r in signals if datetime.fromisoformat(r['entry_ts']) >= now-timedelta(days=days)]
        own = stats(rows)
        actual_api = aggregate([SimpleNamespace(**r) for r in rows], verified_only=True)
        assert (own['wins'], own['losses']) == (actual_api['wins'], actual_api['losses'])
        pairs = {p: stats([r for r in rows if r['pair'] == p]) for p in sorted({r['pair'] for r in rows} | set(data['owner_db_watchlist']))}
        report['periods'][str(days)] = dict(all=own, production_api_aggregate=actual_api, pairs=pairs)
    measured = [r for r in signals if direction(r) is not None]
    report['measured_range_utc'] = [min(r['entry_ts'] for r in measured), max(r['entry_ts'] for r in measured)] if measured else None
    report['quality'] = dict(statuses=dict(Counter(r['outcome'] for r in signals)),
        invalid_measured_prices=sum(r['outcome'].endswith('_timed') and direction(r) is None for r in signals),
        endpoint_processing_delay_seconds=[(datetime.fromisoformat(r['resolved_at'])-datetime.fromisoformat(r['entry_ts'])).total_seconds()-r['horizon_seconds'] for r in measured if r['resolved_at'] and r['horizon_seconds']],
        fresh_actual_trades_30d=sum(datetime.fromisoformat(t['entry_ts']) >= now-timedelta(days=30) for t in trades))
    report['actual_trade_cohorts'] = {}
    for mode in sorted({t['account_mode'] for t in trades}):
        part = [t for t in trades if t['account_mode'] == mode]
        valid = [t for t in part if t['result'] in ('win', 'loss') and isinstance(t['amount'], (int, float)) and t['amount'] > 0 and isinstance(t['payout_amount'], (int, float)) and math.isfinite(t['payout_amount'])]
        mapping = {r['id']: r for r in signals}
        matched_measured = [t for t in valid if t['signal_outcome_id'] in mapping and direction(mapping[t['signal_outcome_id']]) is not None]
        bypair = {}
        for pair in sorted({t['pair'] for t in valid}, key=lambda p: p or ''):
            group = [t for t in valid if t['pair'] == pair]
            bypair[pair or '?'] = dict(n=len(group), wins=sum(t['result'] == 'win' for t in group),
                net_account_currency=sum(t['payout_amount']-t['amount'] for t in group),
                sum_stakes=sum(t['amount'] for t in group), expiry_mismatches=sum(bool(t['expiry_mismatch']) for t in group))
        report['actual_trade_cohorts'][mode] = dict(total=len(part), result_counts=dict(Counter(t['result'] for t in part)),
            settled_with_payout=len(valid), net_account_currency=sum(t['payout_amount']-t['amount'] for t in valid),
            matched_current_measured_signals=len(matched_measured),
            first_entry=min(t['entry_ts'] for t in part), last_entry=max(t['entry_ts'] for t in part), bypair=bypair)
    # Show how the executor's current unverified default differs from UI.
    recent = [r for r in signals if datetime.fromisoformat(r['entry_ts']) >= now-timedelta(days=30)]
    report['executor_vs_ui_30d'] = {p: dict(
        executor_unverified_default=aggregate([SimpleNamespace(**r) for r in recent if r['pair'] == p]),
        ui_verified_only=aggregate([SimpleNamespace(**r) for r in recent if r['pair'] == p], verified_only=True))
        for p in data['owner_db_watchlist']}
    scores = defaultdict(list)
    for row in measured:
        if row['score'] is not None:
            confidence = 100-row['score'] if row['verdict'] == 'BUY' else row['score']
            scores[str((confidence//5)*5)].append(row)
    report['normalized_score_groups'] = {k: stats(v) for k, v in sorted(scores.items())}
    (HERE/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    concise = dict(snapshot_utc=report['snapshot_utc'], measured_range=report['measured_range_utc'],
        overall=report['periods']['30']['all'], pairs=report['periods']['30']['pairs'],
        actual=report['actual_trade_cohorts'], quality={k:v for k,v in report['quality'].items() if k != 'endpoint_processing_delay_seconds'},
        score_groups=report['normalized_score_groups'])
    print(json.dumps(concise, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
