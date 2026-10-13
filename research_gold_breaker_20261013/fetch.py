"""Isolated demo READ-only M1 acquisition. No DB, orders or token refresh."""
from datetime import datetime,timezone
from pathlib import Path
import gzip
import hashlib
import json
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from broker_feasibility import Probe,m,ProtoOATrendbarPeriod,persisted_access_token
from dotenv import dotenv_values
from google.protobuf.json_format import MessageToDict

START=int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,10,13,tzinfo=timezone.utc).timestamp()*1000)


def worker():
    cache=HERE/'cache';cache.mkdir(exist_ok=True)
    if (cache/'complete.json').exists():print('Complete local cache; no connection.');return
    env=dotenv_values(ROOT/'.env');token=persisted_access_token(env) if '--persisted' in sys.argv else env.get('CTRADER_ACCESS_TOKEN')
    if not token:raise ValueError('No configured local read access token')
    account=int(env['DEMO_ACCOUNT_ID']);probe=Probe();probe.deadline=time.monotonic()+180
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'],clientSecret=env['CT_CLIENT_SECRET']),m.ProtoOAApplicationAuthRes)
        accounts=probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token),m.ProtoOAGetAccountListByAccessTokenRes)
        selected=next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId==account),None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:raise ValueError('Not explicitly verified demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account,accessToken=token),m.ProtoOAAccountAuthRes)
        listed=probe.request(m.ProtoOASymbolsListReq(ctidTraderAccountId=account),m.ProtoOASymbolsListRes)
        symbol=next((s for s in listed.symbol if s.symbolName=='XAUUSD' and s.enabled),None)
        if symbol is None:raise ValueError('Exact XAUUSD absent; no fallback')
        details=probe.request(m.ProtoOASymbolByIdReq(ctidTraderAccountId=account,symbolId=[symbol.symbolId]),m.ProtoOASymbolByIdRes)
        spec=next(s for s in details.symbol if s.symbolId==symbol.symbolId)
        (cache/'metadata.json').write_text(json.dumps(dict(symbol='XAUUSD',confirmed_demo=True,no_orders=True,
            fetched_utc=datetime.now(timezone.utc).isoformat(),current_terms_not_historical=True,
            specification=MessageToDict(spec,preserving_proto_field_name=True)),indent=2),encoding='utf-8')
        cursor=END-1;pages=[];total=0
        for page in range(100):
            file=cache/f'M1_{cursor}.json.gz'
            if file.exists():
                with gzip.open(file,'rt',encoding='utf-8') as stream:data=json.load(stream)
                if (data['start_ms'],data['cursor_ms'],data['symbol_id'],data['period'])!=(START,cursor,symbol.symbolId,'M1'):raise ValueError('Cache mismatch')
            else:
                time.sleep(.25)
                result=probe.request(m.ProtoOAGetTrendbarsReq(ctidTraderAccountId=account,symbolId=symbol.symbolId,
                    period=ProtoOATrendbarPeriod.M1,fromTimestamp=START,toTimestamp=cursor,count=6000),m.ProtoOAGetTrendbarsRes)
                data=dict(start_ms=START,cursor_ms=cursor,symbol_id=symbol.symbolId,period='M1',
                          bars=[MessageToDict(b,preserving_proto_field_name=True) for b in result.trendbar])
                with gzip.open(file,'xt',encoding='utf-8') as stream:json.dump(data,stream,separators=(',',':'))
            pages.append(dict(file=file.name,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
            if not data['bars']:raise ValueError('History ended before requested start')
            total+=len(data['bars']);oldest=min(int(b['utcTimestampInMinutes'])*60000 for b in data['bars'])
            print(json.dumps(dict(page=page+1,bars=total,oldest_utc=datetime.fromtimestamp(oldest/1000,timezone.utc).isoformat())),flush=True)
            if oldest<=START:break
            if oldest-1>=cursor:raise ValueError('Nonadvancing cursor')
            cursor=oldest-1
        else:raise ValueError('Page cap reached')
        (cache/'complete.json').write_text(json.dumps(dict(symbol='XAUUSD',period='M1',confirmed_demo=True,no_orders=True,
            start_ms=START,end_exclusive_ms=END,pages=pages,complete=True),indent=2),encoding='utf-8')
        print('M1 history completed; no orders/refreshes.',flush=True)
    finally:probe.socket.close()


if __name__=='__main__':
    if '--worker' in sys.argv:
        try:worker()
        except Exception as error:print('Stopped safely: '+type(error).__name__,flush=True);sys.exit(1)
    else:
        try:sys.exit(subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker']+(['--persisted'] if '--persisted' in sys.argv else []),timeout=210).returncode)
        except subprocess.TimeoutExpired:print('Hard deadline reached; checkpoints retained.');sys.exit(1)
