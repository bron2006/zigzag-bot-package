"""Bounded demo-only metadata probe; no config/db imports or token refresh.

Only allowlisted read requests can leave this process. Never sends orders.
Raw credentials/account lists are never saved or printed.
"""
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from google.protobuf.json_format import MessageToDict
from ctrader_open_api.messages import OpenApiMessages_pb2 as m
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

ALLOWED = frozenset(('ProtoOAApplicationAuthReq', 'ProtoOAGetAccountListByAccessTokenReq',
                    'ProtoOAAccountAuthReq', 'ProtoOAAssetClassListReq',
                    'ProtoOASymbolCategoryListReq', 'ProtoOASymbolsListReq',
                    'ProtoOASymbolByIdReq', 'ProtoOAGetTrendbarsReq', 'ProtoOAGetTickDataReq'))


def validate_request(request):
    if request.DESCRIPTOR.name not in ALLOWED:
        raise ValueError('Request not in read-only allowlist')


class Probe:
    def __init__(self):
        self.deadline = time.monotonic()+75
        raw = socket.create_connection(('demo.ctraderapi.com', 5035), timeout=8)
        try:
            self.socket = ssl.create_default_context().wrap_socket(raw, server_hostname='demo.ctraderapi.com')
        except BaseException:
            raw.close()
            raise
        self.counter = 0

    def read(self, count):
        result = b''
        while len(result) < count:
            left = self.deadline-time.monotonic()
            if left <= 0:
                raise TimeoutError('Probe deadline')
            self.socket.settimeout(min(8, left))
            part = self.socket.recv(count-len(result))
            if not part:
                raise ConnectionError('Connection closed')
            result += part
        return result

    def request(self, request, response_type):
        validate_request(request)
        self.counter += 1
        identifier = f'feasibility-{self.counter}'
        envelope = ProtoMessage(payloadType=request.payloadType,
                                payload=request.SerializeToString(), clientMsgId=identifier)
        payload = envelope.SerializeToString()
        self.socket.sendall(struct.pack('!I', len(payload))+payload)
        expected = response_type()
        while True:
            size = struct.unpack('!I', self.read(4))[0]
            if not 0 < size <= 15000000:
                raise ValueError('Invalid frame size')
            message = ProtoMessage()
            message.ParseFromString(self.read(size))
            if message.clientMsgId != identifier:
                continue
            if message.payloadType != expected.payloadType:
                # Do not print raw server descriptions: they can contain secrets.
                if message.payloadType == m.ProtoOAErrorRes().payloadType:
                    error = m.ProtoOAErrorRes()
                    error.ParseFromString(message.payload)
                    code = error.errorCode
                    if re.fullmatch(r'[A-Z_]{1,64}', code):
                        print('API error code: '+code)
                raise RuntimeError('Unexpected response or API authentication error')
            expected.ParseFromString(message.payload)
            return expected


def persisted_access_token(env):
    # Reuse timeout construction without importing db/config/schema initialization.
    from sqlalchemy import create_engine, event, text
    source = ast.parse((ROOT/'db.py').read_text(encoding='utf-8-sig'))
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'_is_sqlite_url', '_build_engine', '_set_transaction_deadlines'}]
    namespace = {'create_engine': create_engine, 'event': event}
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'bounded-read-engine', 'exec'), namespace)
    engine = namespace['_build_engine'](env['DATABASE_URL'])
    try:
        with engine.connect() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            token = connection.execute(text('SELECT value FROM app_runtime_settings WHERE key = :key'),
                                       {'key': 'ctrader_access_token'}).scalar_one_or_none()
            connection.rollback()
        if not token:
            raise ValueError('No persisted access token')
        return token
    finally:
        engine.dispose()


def worker(output, use_persisted_token=False, history=False):
    env = dict(dotenv_values(ROOT/'.env'))
    env.update({key: value for key, value in os.environ.items() if key in env})
    required = ('CT_CLIENT_ID', 'CT_CLIENT_SECRET', 'CTRADER_ACCESS_TOKEN', 'DEMO_ACCOUNT_ID')
    if not all(env.get(key) for key in required):
        raise ValueError('Missing local demo credentials')
    if use_persisted_token:
        env['CTRADER_ACCESS_TOKEN'] = persisted_access_token(env)
    account = int(env['DEMO_ACCOUNT_ID'])
    probe = Probe()
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'], clientSecret=env['CT_CLIENT_SECRET']),
                      m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=env['CTRADER_ACCESS_TOKEN']),
                                 m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId == account), None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Configured account not confirmed demo; refusing fallback')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account, accessToken=env['CTRADER_ACCESS_TOKEN']),
                      m.ProtoOAAccountAuthRes)
        if history:
            snapshot = json.loads(Path(__file__).with_name('broker_snapshot.json').read_text(encoding='utf-8'))
            # Representative asset classes chosen for coverage, not returns.
            selected_names = ('EURUSD', 'US500', 'XAUUSD', 'XTIUSD')
            symbols_by_name = {s['name']: s for s in snapshot['symbols']}
            from_ms = int(datetime(2010, 1, 1, tzinfo=timezone.utc).timestamp()*1000)
            to_ms = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()*1000)-1
            histories = []
            for name in selected_names:
                symbol = symbols_by_name[name]
                response = probe.request(m.ProtoOAGetTrendbarsReq(
                    ctidTraderAccountId=account, symbolId=int(symbol['light']['symbolId']),
                    period=ProtoOATrendbarPeriod.D1, fromTimestamp=from_ms, toTimestamp=to_ms, count=6000),
                    m.ProtoOAGetTrendbarsRes)
                bars = [MessageToDict(bar, preserving_proto_field_name=True) for bar in response.trendbar]
                dates = [datetime.fromtimestamp(bar.utcTimestampInMinutes*60, tz=timezone.utc).isoformat()
                         for bar in response.trendbar]
                coverage = dict(name=name, bars=len(bars), first=min(dates) if dates else None,
                                last=max(dates) if dates else None)
                histories.append(dict(**coverage, raw_trendbars=bars,
                                      specification=symbol['specification']))
                print(json.dumps(coverage), flush=True)
            output.write_text(json.dumps(dict(fetched_utc=datetime.now(timezone.utc).isoformat(),
                              confirmed_demo=True, no_orders=True, requested_start='2010-01-01',
                              requested_end_exclusive='2026-10-01', period='D1',
                              historical_costs_available=False, histories=histories), indent=2), encoding='utf-8')
            return
        classes = probe.request(m.ProtoOAAssetClassListReq(ctidTraderAccountId=account), m.ProtoOAAssetClassListRes)
        categories = probe.request(m.ProtoOASymbolCategoryListReq(ctidTraderAccountId=account), m.ProtoOASymbolCategoryListRes)
        symbols = probe.request(m.ProtoOASymbolsListReq(ctidTraderAccountId=account), m.ProtoOASymbolsListRes)
        classmap = {a.id: a.name for a in classes.assetClass}
        catmap = {c.id: (c.name, classmap.get(c.assetClassId, 'unknown')) for c in categories.symbolCategory}
        details = {}
        for first in range(0, len(symbols.symbol), 100):
            ids = [s.symbolId for s in symbols.symbol[first:first+100]]
            response = probe.request(m.ProtoOASymbolByIdReq(ctidTraderAccountId=account, symbolId=ids), m.ProtoOASymbolByIdRes)
            details.update({s.symbolId: MessageToDict(s, preserving_proto_field_name=True) for s in response.symbol})
        records = []
        for symbol in symbols.symbol:
            light = MessageToDict(symbol, preserving_proto_field_name=True)
            category, assetclass = catmap.get(getattr(symbol, 'symbolCategoryId', None), ('unknown', 'unknown'))
            records.append(dict(name=symbol.symbolName, category=category, asset_class=assetclass,
                                light=light, specification=details.get(symbol.symbolId)))
        result = dict(fetched_utc=datetime.now(timezone.utc).isoformat(), endpoint='demo.ctraderapi.com',
                      confirmed_demo=True, no_orders=True, current_terms_not_historical=True,
                      symbol_count=len(records), asset_classes=dict(Counter(r['asset_class'] for r in records)),
                      symbols=records)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({key: value for key, value in result.items() if key != 'symbols'}, ensure_ascii=False))
    finally:
        probe.socket.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--persisted-token', action='store_true')
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('broker_snapshot.json'))
    args = parser.parse_args()
    if args.worker:
        try:
            worker(args.output, args.persisted_token, args.history)
        except Exception as error:
            print('Probe failed safely: '+type(error).__name__)
            sys.exit(1)
    else:
        try:
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--output', str(args.output)]
            if args.persisted_token:
                command.append('--persisted-token')
            if args.history:
                command.append('--history')
            completed = subprocess.run(command, timeout=90)
            sys.exit(completed.returncode)
        except subprocess.TimeoutExpired:
            print('Probe exceeded 90 seconds; isolated child stopped.')
            sys.exit(1)
