"""Checkpointed demo-only history fetch, no order/refresh requests."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

from news_event_calendar import events
from news_continuation import CACHE, signal, snapshot


def ticks(probe,account,symbol,kind,start,end):
    from broker_feasibility import m
    from google.protobuf.json_format import MessageToDict
    from verify_replay_ticks import decode_ticks
    time.sleep(.25)
    response = probe.request(m.ProtoOAGetTickDataReq(ctidTraderAccountId=account,
        symbolId=symbol,type=kind,fromTimestamp=start,toTimestamp=end-1),m.ProtoOAGetTickDataRes)
    if response.hasMore:
        # Tiny6s windows should fit; never silently use a truncated page.
        raise ValueError('Endpoint ticks truncated')
    decoded = decode_ticks([MessageToDict(t,preserving_proto_field_name=True) for t in response.tickData])
    if any(not start<=t['timestamp_ms']<end or t['price']<=0 for t in decoded):
        raise ValueError('Invalid ticks')
    return decoded


def window(probe,account,symbol,deadline):
    return {key:ticks(probe,account,symbol,kind,deadline-1000,deadline+5001)
            for key,kind in [('BID',1),('ASK',2)]}


def worker():
    from broker_feasibility import ROOT, Probe, persisted_access_token, m, ProtoOATrendbarPeriod
    from dotenv import dotenv_values
    from google.protobuf.json_format import MessageToDict
    CACHE.mkdir(exist_ok=True)
    planned = events()
    pending = [e for e in planned if not (CACHE/(e['id']+'.json.gz')).exists()]
    if not pending:
        print('All65 official event caches already present; no connection.')
        return
    env = dotenv_values(ROOT/'.env')
    token,account = persisted_access_token(env),int(env['DEMO_ACCOUNT_ID'])
    snapshot_data = json.loads(Path(__file__).with_name('broker_snapshot.json').read_text(encoding='utf-8'))
    symbol = next(int(s['light']['symbolId']) for s in snapshot_data['symbols'] if s['name']=='EURUSD')
    probe = Probe()
    probe.deadline = time.monotonic()+500
    try:
        probe.request(m.ProtoOAApplicationAuthReq(clientId=env['CT_CLIENT_ID'],clientSecret=env['CT_CLIENT_SECRET']),m.ProtoOAApplicationAuthRes)
        accounts = probe.request(m.ProtoOAGetAccountListByAccessTokenReq(accessToken=token),m.ProtoOAGetAccountListByAccessTokenRes)
        selected = next((a for a in accounts.ctidTraderAccount if a.ctidTraderAccountId==account),None)
        if selected is None or not selected.HasField('isLive') or selected.isLive:
            raise ValueError('Not verified demo')
        probe.request(m.ProtoOAAccountAuthReq(ctidTraderAccountId=account,accessToken=token),m.ProtoOAAccountAuthRes)
        for i,event in enumerate(pending):
            t=event['release_ts']
            time.sleep(.25)
            response=probe.request(m.ProtoOAGetTrendbarsReq(ctidTraderAccountId=account,symbolId=symbol,
                period=ProtoOATrendbarPeriod.M5,fromTimestamp=(t-4500)*1000,
                toTimestamp=(t+900)*1000-1,count=100),m.ProtoOAGetTrendbarsRes)
            bars=[MessageToDict(b,preserving_proto_field_name=True) for b in response.trendbar]
            prepared=signal(bars,t)
            entry_streams={'BID':[],'ASK':[]};exit_streams={'BID':[],'ASK':[]}
            if prepared['status']=='selected':
                entry_streams=window(probe,account,symbol,(t+301)*1000)
                entry=snapshot(entry_streams,(t+301)*1000)
                if entry:
                    exit_streams=window(probe,account,symbol,entry['timestamp_ms']+300000)
            data={'event':event,'raw_trendbars':bars,'entry_streams':entry_streams,
                  'exit_streams':exit_streams,'complete_pages':True,'no_orders':True,
                  'fetched_utc':datetime.now(timezone.utc).isoformat()}
            path=CACHE/(event['id']+'.json.gz')
            with gzip.open(path,'xt',encoding='utf-8') as stream:
                json.dump(data,stream,separators=(',',':'))
            if (i+1)%5==0 or i==0 or i+1==len(pending):
                print(json.dumps({'processed':i+1,'pending':len(pending),'last_event':event['id'],
                                  'bars':len(bars),'last_status':prepared['status']}),flush=True)
    finally:
        probe.socket.close()


if __name__=='__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print('Read-only fetch stopped safely: '+type(error).__name__,flush=True)
            sys.exit(1)
    else:
        try:
            sys.exit(subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],timeout=540).returncode)
        except subprocess.TimeoutExpired:
            print('Fetch deadline reached; isolated child stopped. Checkpoints preserved.')
            sys.exit(1)
