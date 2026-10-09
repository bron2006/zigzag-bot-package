"""Bounded read-only M5 fetch for EURUSD; never refreshes tokens or sends orders."""
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time


def worker():
    from broker_feasibility import ROOT, Probe, persisted_access_token, m, ProtoOATrendbarPeriod
    from dotenv import dotenv_values
    from google.protobuf.json_format import MessageToDict
    folder = Path(__file__).parent
    path = folder / 'vwap_replay_m5' / 'EURUSD.json'
    start = int(datetime(2026, 8, 25, 8, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 10, 7, 16, tzinfo=timezone.utc).timestamp() * 1000)
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if existing['start_ms'] == start and existing['end_exclusive_ms'] == end:
            print(json.dumps({'cached': True, 'bars': len(existing['raw_trendbars'])}))
            return
        raise ValueError('Existing cache has another interval; no overwrite')
    env = dotenv_values(ROOT / '.env')
    token = persisted_access_token(env)
    account = int(env['DEMO_ACCOUNT_ID'])
    snapshot = json.loads((folder / 'broker_snapshot.json').read_text(encoding='utf-8'))
    symbol = next(s for s in snapshot['symbols'] if s['name'] == 'EURUSD')
    probe = Probe()
    probe.deadline = time.monotonic() + 180
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'], clientSecret=env['CT_CLIENT_SECRET']), m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token), m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next(a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId == account)
        if not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Demo account not verified')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account, accessToken=token), m.ProtoOAAccountAuthRes)
        rows, cursor = {}, end - 1
        for _ in range(12):
            time.sleep(.25)
            response = probe.request(m.ProtoOAGetTrendbarsReq(ctidTraderAccountId=account,
                symbolId=int(symbol['light']['symbolId']), period=ProtoOATrendbarPeriod.M5,
                fromTimestamp=start, toTimestamp=cursor, count=6000), m.ProtoOAGetTrendbarsRes)
            if not response.trendbar:
                break
            oldest = min(b.utcTimestampInMinutes * 60000 for b in response.trendbar)
            for bar in response.trendbar:
                ts = bar.utcTimestampInMinutes * 60000
                if start <= ts < end:
                    rows[ts] = MessageToDict(bar, preserving_proto_field_name=True)
            if oldest <= start:
                break
            new_cursor = oldest - 1
            if new_cursor >= cursor:
                raise ValueError('Nonadvancing cursor')
            cursor = new_cursor
        else:
            raise ValueError('Incomplete pagination')
        if not rows:
            raise ValueError('Empty history')
        path.write_text(json.dumps({'symbol': 'EURUSD', 'period': 'M5', 'no_orders': True,
            'start_ms': start, 'end_exclusive_ms': end, 'fetched_utc': datetime.now(timezone.utc).isoformat(),
            'raw_trendbars': [rows[t] for t in sorted(rows)]}), encoding='utf-8')
        print(json.dumps({'symbol': 'EURUSD', 'bars': len(rows), 'orders': 0, 'token_refreshes': 0}))
    finally:
        probe.socket.close()


if __name__ == '__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print(json.dumps({'error_type': type(error).__name__}))
            sys.exit(1)
    else:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], timeout=210)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print('Read-only history deadline reached; isolated child stopped.')
            sys.exit(1)
