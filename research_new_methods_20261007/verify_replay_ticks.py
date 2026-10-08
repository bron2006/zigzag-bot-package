"""Small deterministic quote audit, not validation of every paper fill."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from dotenv import dotenv_values
from google.protobuf.json_format import MessageToDict
from broker_feasibility import ROOT, Probe, persisted_access_token, m


def decode_ticks(raw):
    time_ms, price = 0, 0
    decoded = []
    for i, record in enumerate(raw):
        time_ms = int(record['timestamp']) if i == 0 else time_ms+int(record['timestamp'])
        price = int(record['tick']) if i == 0 else price+int(record['tick'])
        decoded.append(dict(timestamp_ms=time_ms, price=price/100000))
    return sorted(decoded, key=lambda r: r['timestamp_ms'])


def worker():
    folder = Path(__file__).parent
    replay = json.loads((folder/'vwap_replay_results.json').read_text(encoding='utf-8'))
    snapshot = json.loads((folder/'broker_snapshot.json').read_text(encoding='utf-8'))
    symbol_ids = {s['name']: int(s['light']['symbolId']) for s in snapshot['symbols']}
    eligible = sorted((r for r in replay['records'] if r['units'] == 'literal' and r['stress'] == 1
                       and r['status'] == 'filled'), key=lambda r: (r['signal_ts'], r['symbol']))
    samples, seen = [], set()
    for record in eligible:
        if record['symbol'] not in seen:
            samples.append(record)
            seen.add(record['symbol'])
        if len(samples) == 3:
            break
    env = dotenv_values(ROOT/'.env')
    token, account = persisted_access_token(env), int(env['DEMO_ACCOUNT_ID'])
    probe = Probe()
    audits = []
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'], clientSecret=env['CT_CLIENT_SECRET']), m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token), m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId == account), None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Not confirmed demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account, accessToken=token), m.ProtoOAAccountAuthRes)
        for record in samples:
            start = max(record['signal_ts']*1000, (record['fill_ts']-300)*1000)
            end = (record['fill_ts']+600)*1000-1
            streams = {}
            for name, quote_type in (('BID', 1), ('ASK', 2)):
                response = probe.request(m.ProtoOAGetTickDataReq(ctidTraderAccountId=account,
                    symbolId=symbol_ids[record['symbol']], type=quote_type,
                    fromTimestamp=start, toTimestamp=end), m.ProtoOAGetTickDataRes)
                raw = [MessageToDict(t, preserving_proto_field_name=True) for t in response.tickData]
                decoded = decode_ticks(raw)
                if any(not start <= tick['timestamp_ms'] <= end or tick['price'] <= 0 for tick in decoded):
                    raise ValueError('Tick delta decoding invalid')
                streams[name] = dict(raw=raw, decoded=decoded, has_more=response.hasMore)
            asks = streams['ASK']['decoded']
            possible = [t for t in asks if t['timestamp_ms'] >= record['signal_ts']*1000 and t['price'] <= record['limit']]
            summary = dict(symbol=record['symbol'], day=record['day'], limit=record['limit'],
                proxy_fill_ts=record['fill_ts'], bid_ticks=len(streams['BID']['decoded']), ask_ticks=len(asks),
                quote_window_start_ms=start, quote_window_end_ms=end,
                incomplete=any(s['has_more'] for s in streams.values()),
                ask_touched_limit_in_window=bool(possible),
                first_ask_touch_ms=possible[0]['timestamp_ms'] if possible else None,
                ask_min=min((t['price'] for t in asks), default=None))
            audits.append(dict(summary=summary, streams=streams))
            print(json.dumps(summary), flush=True)
    finally:
        probe.socket.close()
    (folder/'replay_tick_audit.json').write_text(json.dumps(dict(fetched_utc=datetime.now(timezone.utc).isoformat(),
        deterministic_three_samples_only=True, not_full_fill_or_pnl_validation=True, samples=audits), indent=2), encoding='utf-8')


if __name__ == '__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print('Tick audit failed safely: '+type(error).__name__)
            sys.exit(1)
    else:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], timeout=90)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print('Tick audit deadline; isolated child stopped.')
            sys.exit(1)
