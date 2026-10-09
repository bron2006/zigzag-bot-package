"""Read-only, demo-only paginated M5 checkpoints; no order/token-refresh APIs."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

FOLDER=Path(__file__).parent
CACHE=FOLDER/'comparative_m5'
SYMBOLS=('EURUSD','GBPUSD','USDJPY')
START=int(datetime(2024,1,1,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp()*1000)


def worker():
    from broker_feasibility import ROOT,Probe,persisted_access_token,m,ProtoOATrendbarPeriod
    from dotenv import dotenv_values
    from google.protobuf.json_format import MessageToDict
    CACHE.mkdir(exist_ok=True)
    if all((CACHE/(symbol+'_complete.json')).exists() for symbol in SYMBOLS):
        print('All three history manifests present; no connection.');return
    env=dotenv_values(ROOT/'.env')
    token,account=persisted_access_token(env),int(env['DEMO_ACCOUNT_ID'])
    metadata=json.loads((FOLDER/'broker_snapshot.json').read_text(encoding='utf-8'))
    ids={s['name']:int(s['light']['symbolId']) for s in metadata['symbols']}
    probe=Probe();probe.deadline=time.monotonic()+840
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'],clientSecret=env['CT_CLIENT_SECRET']),m.ProtoOAApplicationAuthRes)
        accounts=probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token),m.ProtoOAGetAccountListByAccessTokenRes)
        selected=next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId==account),None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:raise ValueError('Not verified demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account,accessToken=token),m.ProtoOAAccountAuthRes)
        for symbol in SYMBOLS:
            manifest=CACHE/(symbol+'_complete.json')
            if manifest.exists():continue
            cursor=END-1;pages=[];total=0
            for page in range(80):
                path=CACHE/f'{symbol}_{cursor}.json.gz'
                if path.exists():
                    with gzip.open(path,'rt',encoding='utf-8') as stream:data=json.load(stream)
                    if data['start_ms']!=START or data['cursor_ms']!=cursor or data['symbol']!=symbol:
                        raise ValueError('Checkpoint contract mismatch')
                else:
                    time.sleep(.25)
                    response=probe.request(m.ProtoOAGetTrendbarsReq(ctidTraderAccountId=account,
                        symbolId=ids[symbol],period=ProtoOATrendbarPeriod.M5,
                        fromTimestamp=START,toTimestamp=cursor,count=6000),m.ProtoOAGetTrendbarsRes)
                    data={'symbol':symbol,'start_ms':START,'cursor_ms':cursor,'no_orders':True,
                        'fetched_utc':datetime.now(timezone.utc).isoformat(),
                        'raw_trendbars':[MessageToDict(b,preserving_proto_field_name=True) for b in response.trendbar]}
                    with gzip.open(path,'xt',encoding='utf-8') as stream:json.dump(data,stream,separators=(',',':'))
                pages.append(path.name);bars=data['raw_trendbars'];total+=len(bars)
                if not bars:raise ValueError('History ended before requested start; do not mark complete')
                oldest=min(int(b['utcTimestampInMinutes'])*60000 for b in bars)
                if page%5==0:print(json.dumps({'symbol':symbol,'pages':page+1,'bars_received':total,
                    'oldest_utc':datetime.fromtimestamp(oldest/1000,timezone.utc).isoformat()}),flush=True)
                if oldest<=START:break
                if oldest-1>=cursor:raise ValueError('Nonadvancing history cursor')
                cursor=oldest-1
            else:raise ValueError('Pagination cap reached')
            manifest.write_text(json.dumps({'symbol':symbol,'period':'M5','start_ms':START,
                'end_exclusive_ms':END,'pages':pages,'complete':True,'no_orders':True},indent=2),encoding='utf-8')
            print(json.dumps({'completed':symbol,'pages':len(pages),'bars_received':total}),flush=True)
    finally:probe.socket.close()


if __name__=='__main__':
    if '--worker' in sys.argv:
        try:worker()
        except Exception as error:
            print('History fetch stopped safely: '+type(error).__name__,flush=True);sys.exit(1)
    else:
        try:sys.exit(subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],timeout=900).returncode)
        except subprocess.TimeoutExpired:
            print('Isolated history child stopped at hard deadline; immutable checkpoints retained.');sys.exit(1)
