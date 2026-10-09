"""Independent arithmetic/as-of audit of saved results, not a second strategy."""
from bisect import bisect_right
import gzip
import hashlib
import json
import math
from pathlib import Path

FOLDER=Path(__file__).parent


def independent_quote(streams,deadline):
    # Different implementation: bisect each side at every observed event time.
    sides={}
    for side in ('BID','ASK'):
        grouped={}
        for tick in streams[side]:
            ts=int(tick['timestamp_ms']);price=float(tick['price'])
            if not math.isfinite(price) or price<=0:raise AssertionError('Invalid tick')
            grouped.setdefault(ts,[]).append(price)
        sides[side]=[(t,min(p) if side=='BID' else max(p)) for t,p in sorted(grouped.items())]
    times=sorted({t for items in sides.values() for t,_ in items if deadline<=t<=deadline+5000})
    for now in times:
        book={}
        for side,items in sides.items():
            idx=bisect_right([t for t,_ in items],now)-1
            if idx<0 or now-items[idx][0]>1000:break
            book[side]=items[idx][1]
        if len(book)==2 and book['BID']<=book['ASK']:
            return {'timestamp_ms':now,'bid':book['BID'],'ask':book['ASK']}
    return None


def main():
    report=json.loads((FOLDER/'news_continuation_result_v1.json').read_text(encoding='utf-8'))
    assert len(report['records'])==65
    assert len({r['id'] for r in report['records']})==65
    audited=0
    for row in report['records']:
        path=FOLDER/'news_event_quotes'/(row['id']+'.json.gz')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==report['cache_hashes'][path.name]
        with gzip.open(path,'rt',encoding='utf-8') as stream:data=json.load(stream)
        t=row['release_ts']//60
        raw={int(b['utcTimestampInMinutes']):b for b in data['raw_trendbars']}
        def price(bar,field):return (int(bar['low'])+int(bar.get(field,0)))/100000
        past=[raw[m] for m in range(t-75,t,5)]
        trs=[]
        for before,bar in zip(past,past[1:]):
            close=price(before,'deltaClose');low=price(bar,'unused');high=price(bar,'deltaHigh')
            trs.append(max(high-low,abs(high-close),abs(low-close)))
        atr=sum(trs)/14
        impulse=price(raw[t],'deltaClose')-price(raw[t-5],'deltaClose')
        selected=impulse!=0 and abs(impulse)>=1.5*atr
        assert selected==row['selected']
        if selected:
            assert math.isclose(atr,row['atr'],abs_tol=1e-12)
            assert row['direction']==(1 if impulse>0 else -1)
            entry=independent_quote(data['entry_streams'],(row['release_ts']+301)*1000)
            exit_quote=independent_quote(data['exit_streams'],entry['timestamp_ms']+300000) if entry else None
            assert entry==row['entry_quote'] and exit_quote==row['exit_quote']
            if entry and exit_quote:
                gross=exit_quote['bid']-entry['ask'] if impulse>0 else entry['bid']-exit_quote['ask']
                assert math.isclose(gross/.0001-.7,row['forex_net_pips'],abs_tol=1e-10)
                assert math.isclose(gross/.0001-1.7,row['forex_stress_pips'],abs_tol=1e-10)
                assert 300000<=exit_quote['timestamp_ms']-entry['timestamp_ms']<=305000
                audited+=1
    print(json.dumps({'event_hashes_verified':65,'known_outcomes_independently_audited':audited,'audit':'passed'}))


if __name__=='__main__':main()
