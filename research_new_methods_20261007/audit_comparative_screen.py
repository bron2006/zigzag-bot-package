"""Independent stdlib OHLC/EMA/ATR/first-signal reconstruction, no engine calls."""
from collections import deque
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).parent
START=int(datetime(2024,1,1,tzinfo=timezone.utc).timestamp())
END=int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp())
RULES=('trend','breakout','reversion')
SYMBOLS=('EURUSD','GBPUSD','USDJPY')


def rebuild(symbol):
    folder=ROOT/'comparative_m5'
    manifest=json.loads((folder/(symbol+'_complete.json')).read_text())
    assert manifest['symbol']==symbol and manifest['period']=='M5' and manifest['complete']
    assert manifest['start_ms']==START*1000 and manifest['end_exclusive_ms']==END*1000
    raw={};hashes={};cursor=END*1000-1
    for name in manifest['pages']:
        path=folder/name;hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path,'rt',encoding='utf-8') as stream:page=json.load(stream)
        assert page['symbol']==symbol and page['cursor_ms']==cursor and page['start_ms']==START*1000
        for b in page['raw_trendbars']:
            ts=int(b['utcTimestampInMinutes'])*60
            assert ts%300==0 and ts*1000<=cursor
            if not START<=ts<END:continue
            low=int(b['low']);o=low+int(b.get('deltaOpen',0));c=low+int(b.get('deltaClose',0));h=low+int(b.get('deltaHigh',0))
            assert 0<low<=min(o,c)<=max(o,c)<=h
            value=(ts,o/100000,h/100000,low/100000,c/100000)
            assert ts not in raw or raw[ts]==value
            raw[ts]=value
        oldest=min(int(b['utcTimestampInMinutes'])*60000 for b in page['raw_trendbars'])
        assert oldest-1<cursor
        cursor=oldest-1
    assert cursor<START*1000
    bars=[raw[t] for t in sorted(raw)];features={};previous=None;warm=0
    trs=deque(maxlen=14);past=deque(maxlen=20)
    for ts,o,h,l,c in bars:
        if previous is None or ts-previous[0]!=300:
            trs.clear();past.clear();warm=0;fast=slow=c
        else:
            fast+=(2/11)*(c-fast);slow+=(2/51)*(c-slow)
        tr=h-l if warm==0 else max(h-l,abs(h-previous[4]),abs(l-previous[4]))
        trs.append(tr);warm+=1
        if warm>=60:
            atr=sum(trs)/14;upper=max(b[2] for b in past);lower=min(b[3] for b in past);mean=sum(b[4] for b in past)/20
            if atr>0:
                features[ts]=(atr,{'trend':1 if fast-slow>=atr and c>fast else -1 if fast-slow<=-atr and c<fast else 0,
                    'breakout':1 if c>upper else -1 if c<lower else 0,
                    'reversion':-1 if c-mean>=2*atr else 1 if c-mean<=-2*atr else 0})
        past.append((ts,o,h,l,c));previous=(ts,o,h,l,c)
    sessions={}
    for ts in raw:
        if 8*3600<=ts%86400<16*3600:sessions.setdefault(ts//86400,[]).append(ts)
    expected={};days=[]
    for day,times in sorted(sessions.items()):
        times=sorted(times)
        if times!=list(range(day*86400+8*3600,day*86400+16*3600,300)):continue
        date=datetime.fromtimestamp(day*86400,timezone.utc).date().isoformat();days.append(date)
        for rule in RULES:
            selected=next((ts for ts in times if ts%86400<=16*3600-900 and ts in features and features[ts][1][rule]),None)
            if selected is None:continue
            assert selected+300 in raw and selected+600 in raw
            atr,signals=features[selected];d=signals[rule];entry=raw[selected+600][1];exit_price=raw[selected+600][4]
            pip=.01 if symbol=='USDJPY' else .0001;move=(exit_price-entry)/atr
            cost=max(.44,4*pip/atr);sign=(exit_price>entry)-(exit_price<entry)
            expected[(date,symbol,rule)]={'direction':d,'signal_ts':selected+300,'entry_ts':selected+600,'exit_ts':selected+900,
                'entry':entry,'exit':exit_price,'atr':atr,'stress_net_atr':d*move-cost,'gross_atr':d*move,
                'base_net_atr':d*move-max(.22,2*pip/atr),'binary80':0 if sign==0 else .8 if sign*d>0 else -1.,
                'always_buy_stress_atr':move-cost,'always_sell_stress_atr':-move-cost,
                'always_buy_binary80':0 if sign==0 else .8 if sign>0 else -1.,
                'always_sell_binary80':0 if sign==0 else .8 if sign<0 else -1.,'price_sign':sign}
    return expected,hashes,days


def main():
    reports={phase:json.loads((ROOT/f'comparative_{phase}_v1.json').read_text()) for phase in ('early','final')}
    checked=0;cache_hashes={}
    for symbol in SYMBOLS:
        expected,hashes,days=rebuild(symbol);cache_hashes.update(hashes)
        for phase,report in reports.items():
            select=lambda date:(date<'2026-01-01')==(phase=='early')
            rows={(r['day'],r['symbol'],r['rule']):r for r in report['records'] if r['symbol']==symbol}
            want={key:value for key,value in expected.items() if select(key[0])}
            assert rows.keys()==want.keys()
            assert report['coverage'][symbol]['full_session_dates']==[day for day in days if select(day)]
            for key,wanted in want.items():
                for field,value in wanted.items():
                    assert math.isclose(rows[key][field],value,rel_tol=1e-9,abs_tol=1e-10),(key,field,rows[key][field],value)
                checked+=1
    for report in reports.values():
        assert report['cache_hashes']==cache_hashes
        for name,digest in report['signatures'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
        assert report['orders']==0 and not report['actual_execution'] and not report['prospective_OOS']
    print(json.dumps({'independent_reconstruction':'passed','records_checked':checked,'pages_checked':len(cache_hashes),
        'symbols':SYMBOLS,'orders':0},indent=2))


if __name__=='__main__':main()
