"""Checkpointed full-session quote retrieval/replay, no orders or refresh."""
import bisect
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from dotenv import dotenv_values
from google.protobuf.json_format import MessageToDict
from broker_feasibility import ROOT, Probe, persisted_access_token, m
from verify_replay_ticks import decode_ticks
from replay_vwap import bands, statistics
from validate_broker_probe import decode_bar

FOLDER = Path(__file__).parent


def quotes(probe, account, symbol_id, quote_type, start, end):
    cursor, records = end-1, []
    for page in range(30):
        time.sleep(.22)
        response = probe.request(m.ProtoOAGetTickDataReq(ctidTraderAccountId=account,
            symbolId=symbol_id, type=quote_type, fromTimestamp=start, toTimestamp=cursor), m.ProtoOAGetTickDataRes)
        batch = decode_ticks([MessageToDict(t, preserving_proto_field_name=True) for t in response.tickData])
        if any(not start <= t['timestamp_ms'] <= cursor or t['price'] <= 0 for t in batch):
            raise ValueError('Invalid quote stream')
        records.extend(batch)
        if not response.hasMore:
            return sorted(records, key=lambda t: t['timestamp_ms'])
        if not batch:
            raise ValueError('Empty truncated tick page')
        next_cursor = batch[0]['timestamp_ms']-1
        if next_cursor >= cursor:
            raise ValueError('Nonadvancing tick cursor')
        cursor = next_cursor
    raise ValueError('Quote pagination incomplete')


def session_data(symbol, day, signal):
    raw = json.loads((FOLDER/'vwap_replay_m5'/f'{symbol}.json').read_text(encoding='utf-8'))
    start = int(datetime.fromisoformat(day+'T08:00:00+00:00').timestamp())
    rows = []
    for bar in raw['raw_trendbars']:
        decoded = decode_bar(bar)
        ts = decoded['start_minute']*60
        if start <= ts < start+8*3600:
            rows.append(dict(**decoded, ts=ts, volume=int(bar['volume'])))
    rows.sort(key=lambda r: r['ts'])
    if [r['ts'] for r in rows] != list(range(start, start+8*3600, 300)):
        raise ValueError('Incomplete session')
    vwaps, _, _ = bands(np.array([r['Close'] for r in rows]), np.array([r['volume'] for r in rows]))
    # ATR known before the intention; enough 08:00+ warmup by 12:00.
    past = [r for r in rows if r['ts']+300 <= signal]
    tr = [max(r['High']-r['Low'], abs(r['High']-past[i-1]['Close']), abs(r['Low']-past[i-1]['Close']))
          for i, r in enumerate(past) if i > 0]
    if len(tr) < 14:
        raise ValueError('Insufficient ATR warmup')
    return [r['ts']+300 for r in rows], vwaps.tolist(), float(np.mean(tr[-14:]))


def tick_replay(order, streams, completed, vwaps, commission, slippage=0):
    start = (order['signal_ts']+1)*1000
    end = int(datetime.fromisoformat(order['day']+'T16:00:00+00:00').timestamp()*1000)
    ask = streams['ASK']
    bid = streams['BID']
    limit, stop = order['limit'], order['stop']
    if limit <= stop:
        return dict(status='invalid_risk')
    if not ask or not bid:
        return dict(status='missing_quotes')
    # Equal millisecond ASK updates: use the highest ASK conservatively.
    ask_by_time = {}
    for tick in ask:
        ts = tick['timestamp_ms']
        ask_by_time[ts] = max(ask_by_time.get(ts, tick['price']), tick['price'])
    possible = [(ts, p) for ts, p in sorted(ask_by_time.items()) if start <= ts < end and p <= limit]
    if not possible:
        if end-max(ask_by_time) > 60000:
            return dict(status='missing_ask_at_session_end')
        return dict(status='unfilled')
    fill = possible[0][0]
    risk = limit-stop
    # Include the latest known BID at fill, but not stale quotes.
    prior = [t for t in bid if t['timestamp_ms'] <= fill]
    if not prior or fill-prior[-1]['timestamp_ms'] > 60000:
        return dict(status='missing_bid_at_fill')
    at_fill = [t for t in prior if t['timestamp_ms'] == fill]
    future = at_fill or [dict(timestamp_ms=fill, price=prior[-1]['price'])]
    future += [t for t in bid if fill < t['timestamp_ms'] < end]
    # Same millisecond multiple BID quotes: stop wins over a target.
    grouped = {}
    for tick in future:
        grouped.setdefault(tick['timestamp_ms'], []).append(tick['price'])
    for ts, prices in sorted(grouped.items()):
        low, high = min(prices), max(prices)
        if low <= stop:
            return dict(status='filled', outcome='STOP', fill_ms=fill, exit_ms=ts,
                        r=(low-limit-commission-slippage)/risk)
        i = bisect.bisect_right(completed, ts/1000)-1
        target = vwaps[i] if i >= 0 else float('nan')
        if np.isfinite(target) and target > limit and high >= target:
            return dict(status='filled', outcome='VWAP', fill_ms=fill, exit_ms=ts,
                        r=(target-limit-commission-slippage)/risk)
    if end-bid[-1]['timestamp_ms'] > 60000:
        return dict(status='missing_bid_at_session_end')
    return dict(status='filled', outcome='SESSION_END', fill_ms=fill, exit_ms=end,
                r=(bid[-1]['price']-limit-commission-slippage)/risk)


def worker():
    cache = FOLDER/'vwap_replay_ticks'
    cache.mkdir(exist_ok=True)
    raw = json.loads((FOLDER/'vwap_replay_results.json').read_text(encoding='utf-8'))
    orders = sorted((r for r in raw['records'] if r['units'] == 'literal' and r['stress'] == 1),
                    key=lambda r: (r['day'], r['signal_ts'], r['symbol']))
    snapshot = json.loads((FOLDER/'broker_snapshot.json').read_text(encoding='utf-8'))
    ids = {s['name']: int(s['light']['symbolId']) for s in snapshot['symbols']}
    env = dotenv_values(ROOT/'.env')
    token, account = persisted_access_token(env), int(env['DEMO_ACCOUNT_ID'])
    probe = Probe()
    probe.deadline = time.monotonic()+1400
    results, hashes = [], {}
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'], clientSecret=env['CT_CLIENT_SECRET']), m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token), m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId == account), None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Not confirmed demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account, accessToken=token), m.ProtoOAAccountAuthRes)
        for index, order in enumerate(orders):
            name, day = order['symbol'], order['day']
            path = cache/f'{day}_{name}.json.gz'
            try:
                start = order['signal_ts']*1000-60000
                end = int(datetime.fromisoformat(day+'T16:00:00+00:00').timestamp()*1000)
                if path.exists():
                    with gzip.open(path, 'rt', encoding='utf-8') as stream:
                        data = json.load(stream)
                    if data['start_ms'] != start or data['end_exclusive_ms'] != end:
                        raise ValueError('Cache bounds differ')
                else:
                    streams = {key: quotes(probe, account, ids[name], typ, start, end)
                               for key, typ in (('BID', 1), ('ASK', 2))}
                    data = dict(start_ms=start, end_exclusive_ms=end, complete_pages=True,
                                fetched_utc=datetime.now(timezone.utc).isoformat(), streams=streams)
                    with gzip.open(path, 'wt', encoding='utf-8') as stream:
                        json.dump(data, stream, separators=(',', ':'))
                hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                completed, vwaps, atr = session_data(name, day, order['signal_ts'])
                for stress in (1, 2):
                    measured = tick_replay(order, data['streams'], completed, vwaps,
                                           .02*atr*stress, .02*atr if stress == 2 else 0)
                    results.append(dict(symbol=name, day=day, signal_ts=order['signal_ts'],
                                        stress=stress, limit=order['limit'], stop=order['stop'], **measured))
                state = 'complete'
            except Exception as error:
                state = type(error).__name__
                for stress in (1, 2):
                    results.append(dict(symbol=name, day=day, stress=stress, status='unavailable', error_type=state))
            if (index+1) % 10 == 0 or index+1 == len(orders):
                write_results(results, hashes, len(orders), index+1)
                print(json.dumps(dict(processed=index+1, total=len(orders), last_day=day,
                                      latest_status=state, cached_files=len(hashes))), flush=True)
    finally:
        probe.socket.close()
        write_results(results, hashes, len(orders), len(results)//2)


def write_results(results, hashes, total, processed):
    summary = dict(total_orders=total, processed=processed, all_processed=processed == total, scenarios={})
    for stress in (1, 2):
        selected = [r for r in results if r['stress'] == stress]
        summary['scenarios'][str(stress)] = dict(all=statistics(selected),
            early=statistics([r for r in selected if r['day'] < '2026-09-14']),
            late=statistics([r for r in selected if r['day'] >= '2026-09-14']))
    output = dict(summary=summary, records=results, quote_cache_sha256=hashes,
                  protocol_sha256=hashlib.sha256((FOLDER/'VWAP_TICK_PROTOCOL.md').read_bytes()).hexdigest(),
                  price_touch_not_guaranteed_broker_execution=True)
    (FOLDER/'vwap_tick_results.json').write_text(json.dumps(output, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print('Full tick replay failed safely: '+type(error).__name__)
            sys.exit(1)
    else:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], timeout=1500)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print('Tick replay deadline reached; checkpoints retained; isolated child stopped.')
            sys.exit(1)
