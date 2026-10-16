"""Bounded, demo-only allowlisted history acquisition; never sends orders."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'research_new_methods_20261007'))
from broker_feasibility import Probe, persisted_access_token, m, ProtoOATrendbarPeriod
from dotenv import dotenv_values
from google.protobuf.json_format import MessageToDict

START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()*1000)
END = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp()*1000)
DAILY_START = int(datetime(2023, 11, 1, tzinfo=timezone.utc).timestamp()*1000)


def worker():
    cache = HERE / 'cache'
    cache.mkdir(exist_ok=True)
    if (cache / 'complete.json').exists():
        print('Complete cache exists: no network used.', flush=True)
        return
    env = dotenv_values(ROOT / '.env')
    token = persisted_access_token(env)
    account = int(env['DEMO_ACCOUNT_ID'])
    probe = Probe()
    probe.deadline = time.monotonic() + 210
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'], clientSecret=env['CT_CLIENT_SECRET']), m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token), m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId == account), None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Configured account not confirmed demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account, accessToken=token), m.ProtoOAAccountAuthRes)
        listed = probe.request(m.ProtoOASymbolsListReq(ctidTraderAccountId=account), m.ProtoOASymbolsListRes)
        symbol = next((s for s in listed.symbol if s.symbolName == 'USTEC' and s.enabled), None)
        if symbol is None:
            raise ValueError('Exact enabled USTEC symbol absent; no fallback')
        details = probe.request(m.ProtoOASymbolByIdReq(ctidTraderAccountId=account, symbolId=[symbol.symbolId]), m.ProtoOASymbolByIdRes)
        spec = next(s for s in details.symbol if s.symbolId == symbol.symbolId)
        metadata = {'name': 'USTEC', 'confirmed_demo': True, 'no_orders': True,
                    'current_terms_not_historical': True, 'fetched_utc': datetime.now(timezone.utc).isoformat(),
                    'light': MessageToDict(symbol, preserving_proto_field_name=True),
                    'specification': MessageToDict(spec, preserving_proto_field_name=True)}
        (cache / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        manifests = {}
        for label, period, first in [('D1', ProtoOATrendbarPeriod.D1, DAILY_START), ('M5', ProtoOATrendbarPeriod.M5, START)]:
            cursor = END - 1
            pages = []
            for page in range(80):
                path = cache / f'{label}_{cursor}.json.gz'
                if path.exists():
                    with gzip.open(path, 'rt', encoding='utf-8') as stream:
                        data = json.load(stream)
                    if (data['start_ms'], data['cursor_ms'], data['period'], data['symbol_id']) != (first, cursor, label, symbol.symbolId):
                        raise ValueError('Cache contract mismatch')
                else:
                    time.sleep(.25)
                    response = probe.request(m.ProtoOAGetTrendbarsReq(ctidTraderAccountId=account, symbolId=symbol.symbolId,
                        period=period, fromTimestamp=first, toTimestamp=cursor, count=6000), m.ProtoOAGetTrendbarsRes)
                    data = {'start_ms': first, 'cursor_ms': cursor, 'period': label, 'symbol_id': symbol.symbolId,
                            'bars': [MessageToDict(b, preserving_proto_field_name=True) for b in response.trendbar]}
                    with gzip.open(path, 'xt', encoding='utf-8') as stream:
                        json.dump(data, stream, separators=(',', ':'))
                pages.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
                if not data['bars']:
                    raise ValueError('History ends before requested start')
                oldest = min(int(b['utcTimestampInMinutes'])*60000 for b in data['bars'])
                if page % 5 == 0:
                    print(json.dumps({'period': label, 'pages': page+1, 'oldest_utc': datetime.fromtimestamp(oldest/1000, timezone.utc).isoformat()}), flush=True)
                if oldest <= first:
                    break
                if oldest - 1 >= cursor:
                    raise ValueError('Nonadvancing cursor')
                cursor = oldest - 1
            else:
                raise ValueError('Page cap reached')
            manifests[label] = {'pages': pages, 'start_ms': first, 'end_exclusive_ms': END}
        (cache / 'complete.json').write_text(json.dumps({'protocol_sha256': hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
            'symbol': 'USTEC', 'no_orders': True, 'confirmed_demo': True, 'histories': manifests}, indent=2), encoding='utf-8')
        print('USTEC M5 and D1 history completed; zero orders/refreshes.', flush=True)
    finally:
        probe.socket.close()


if __name__ == '__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print('Fetch stopped safely: ' + type(error).__name__, flush=True)
            sys.exit(1)
    else:
        try:
            sys.exit(subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], timeout=240).returncode)
        except subprocess.TimeoutExpired:
            print('240-second hard limit; isolated child stopped; cache retained.', flush=True)
            sys.exit(1)
