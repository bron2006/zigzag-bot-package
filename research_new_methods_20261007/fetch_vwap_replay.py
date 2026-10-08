"""Read-only checkpointed M5 acquisition for replay. No token refresh/orders."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from dotenv import dotenv_values
from google.protobuf.json_format import MessageToDict
from broker_feasibility import ROOT, Probe, persisted_access_token, m, ProtoOATrendbarPeriod


def worker():
    folder = Path(__file__).with_name('vwap_replay_m5')
    folder.mkdir(exist_ok=True)
    inventory = json.loads(Path(__file__).with_name('vwap_intentions_inventory.json').read_text(encoding='utf-8'))
    symbols = inventory['summary']['symbols']
    dates = inventory['summary']['days']
    start = int(datetime.fromisoformat(dates[0]+'T08:00:00+00:00').timestamp()*1000)
    end = int(datetime.fromisoformat(dates[-1]+'T16:00:00+00:00').timestamp()*1000)
    snapshot = json.loads(Path(__file__).with_name('broker_snapshot.json').read_text(encoding='utf-8'))
    names = {s['name']: s for s in snapshot['symbols']}
    env = dotenv_values(ROOT/'.env')
    token = persisted_access_token(env)
    account = int(env['DEMO_ACCOUNT_ID'])
    probe = Probe()
    probe.deadline = time.monotonic()+600
    statuses = []
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'], clientSecret=env['CT_CLIENT_SECRET']), m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token), m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId == account), None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Account not confirmed demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account, accessToken=token), m.ProtoOAAccountAuthRes)
        for name in symbols:
            path = folder/f'{name}.json'
            if path.exists():
                cached = json.loads(path.read_text(encoding='utf-8'))
                if cached.get('start_ms') == start and cached.get('end_exclusive_ms') == end:
                    print(json.dumps(dict(symbol=name, cached=True)), flush=True)
                    continue
            try:
                rows, cursor = {}, end-1
                for page in range(6):
                    time.sleep(.25)
                    response = probe.request(m.ProtoOAGetTrendbarsReq(ctidTraderAccountId=account,
                        symbolId=int(names[name]['light']['symbolId']), period=ProtoOATrendbarPeriod.M5,
                        fromTimestamp=start, toTimestamp=cursor, count=6000), m.ProtoOAGetTrendbarsRes)
                    batch = list(response.trendbar)
                    if not batch:
                        break
                    oldest = min(b.utcTimestampInMinutes*60000 for b in batch)
                    for bar in batch:
                        timestamp = bar.utcTimestampInMinutes*60000
                        if start <= timestamp < end:
                            rows[timestamp] = MessageToDict(bar, preserving_proto_field_name=True)
                    if oldest <= start:
                        break
                    new_cursor = oldest-1
                    if new_cursor >= cursor:
                        raise ValueError('Nonadvancing history cursor')
                    cursor = new_cursor
                else:
                    raise ValueError('History pagination incomplete')
                record = dict(symbol=name, fetched_utc=datetime.now(timezone.utc).isoformat(),
                    start_ms=start, end_exclusive_ms=end, no_orders=True, period='M5',
                    specification=names[name]['specification'], raw_trendbars=[rows[t] for t in sorted(rows)])
                path.write_text(json.dumps(record), encoding='utf-8')
                status = dict(symbol=name, bars=len(rows), ok=bool(rows))
            except Exception as error:
                status = dict(symbol=name, ok=False, error_type=type(error).__name__)
            statuses.append(status)
            print(json.dumps(status), flush=True)
    finally:
        probe.socket.close()
        (folder/'fetch_status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')


if __name__ == '__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print('Read-only fetch failed: '+type(error).__name__, flush=True)
            sys.exit(1)
    else:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], timeout=660)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print('Fetch deadline reached; isolated child stopped; checkpoints preserved.')
            sys.exit(1)
