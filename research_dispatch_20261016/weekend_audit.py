"""Independent native-JSON Decimal cache and weekend-event audit."""
from decimal import Decimal as D
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean

ROOT=Path(__file__).resolve().parents[1]
START,END=1704067200,1791417600


def decode(raw):
    if len(raw)<12:raise ValueError('Incomplete native kline')
    stamp=int(raw[0]);closed=int(raw[6])
    if stamp%3600000 or closed!=stamp+3600000-1:
        raise ValueError('Not a complete UTC hourly candle')
    prices=[D(str(x)) for x in raw[1:5]]
    op,hi,lo,close=prices
    if not all(x.is_finite() and x>0 for x in prices) or not lo<=min(op,close)<=max(op,close)<=hi:
        raise ValueError('Invalid native OHLC')
    return dict(ts=stamp//1000,Open=op,High=hi,Low=lo,Close=close)


def load(asset):
    if asset not in ('BTC','ETH'):raise ValueError('Unknown frozen asset')
    folder=ROOT/'research_new_methods_20261007/inverse_price_cache'
    manifest_path=folder/(asset+'_spot_complete.json')
    manifest=json.loads(manifest_path.read_text('utf-8'))
    if manifest.get('complete') is not True or manifest['leg']!='spot' or manifest['symbol']!=asset:
        raise ValueError('Wrong/incomplete cached instrument')
    if manifest['start']!=START*1000 or manifest['end']!=END*1000:
        raise ValueError('Unexpected frozen study bounds')
    bars={};hashes={}
    for page in manifest['pages']:
        filename=page['file'] if isinstance(page,dict) else page
        if Path(filename).name!=filename or not filename.startswith(asset+'_spot_'):
            raise ValueError('Unexpected page target')
        path=folder/filename;digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if isinstance(page,dict) and page['sha256']!=digest:raise ValueError('Acquisition hash mismatch')
        hashes[filename]=digest
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for raw in json.load(stream):
                row=decode(raw);ts=row['ts']
                if not START<=ts<END:continue
                if ts in bars:raise ValueError('Duplicate hourly candle')
                bars[ts]=row
    if sorted(bars)!=list(range(START,END,3600)):raise ValueError('Incomplete or misaligned hourly axis')
    return bars,dict(manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                     input_hashes=hashes,hourly_bars=len(bars),native_close_time_verified=True,
                     acquisition_integrity_proven=False,executable_bid_ask=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache-only',action='store_true')
    args=parser.parse_args();checks={}
    result=None
    if not args.cache_only:
        folder=ROOT/'research_weekend_20261016'
        result=json.loads((folder/'result.json').read_text('utf-8'))
        assert hashlib.sha256((folder/'PROTOCOL.md').read_bytes()).hexdigest()==result['protocol_sha256']
        assert hashlib.sha256((folder/'run.py').read_bytes()).hexdigest()==result['source_sha256']
    for asset in ('BTC','ETH'):
        bars,info=load(asset);checks[asset]=info
        if result is not None:
            data=result['assets'][asset]
            for filename,digest in info['input_hashes'].items():assert data['input_hashes'][filename]==digest
            assert data['input_hashes'][asset+'_spot_complete.json']==info['manifest_sha256']
            totals=dict(closed=0,pending=0,max_gross_error=0)
            own={}
            for row in data['rows']:
                week=row['week']
                for name,days,side in [('weekend',4,1),('weekday',1,1),('short',4,-1)]:
                    entry_ts=week+days*86400+20*3600;out=row['arms'][name]
                    assert out['entry_ts']==entry_ts
                    if entry_ts>=END:
                        assert out['status']=='pending';totals['pending']+=1;continue
                    assert out['decision_ts']==entry_ts-3600
                    assert out['atr_first_ts']==entry_ts-16*3600 and out['atr_last_ts']==entry_ts-2*3600
                    history=[bars[t] for t in range(entry_ts-16*3600,entry_ts-3600,3600)]
                    tr=[max(b['High']-b['Low'],abs(b['High']-a['Close']),abs(b['Low']-a['Close']))
                        for a,b in zip(history,history[1:])]
                    assert len(tr)==14
                    atr=(sum(tr)/14).quantize(D('1e-12'));distance=2*atr
                    assert abs(atr-D(str(out['atr'])))<D('1e-8')
                    entry=bars[entry_ts]['Open'];stop=entry-side*distance;price=reason=None
                    for ts in range(entry_ts,entry_ts+48*3600,3600):
                        if ts>=END:break
                        bar=bars[ts]
                        if side*(bar['Open']-stop)<=0:price,reason,exit_ts=bar['Open'],'gap_stop',ts;break
                        if bar['Low']<=stop if side==1 else bar['High']>=stop:
                            price,reason,exit_ts=stop,'stop',ts+3600;break
                    if price is None:
                        if entry_ts+48*3600>=END:
                            assert out['status']=='pending';totals['pending']+=1;continue
                        price=bars[entry_ts+48*3600]['Open'];reason='deadline';exit_ts=entry_ts+48*3600
                    assert out['status']=='closed' and out['reason']==reason and out['exit_ts']==exit_ts
                    assert out['charged_hours']==(exit_ts-entry_ts)//3600
                    assert abs(price-D(str(out['exit'])))<D('1e-8')
                    assert abs(stop-D(str(out['stop'])))<D('1e-8')
                    gross=side*(price-entry)/entry
                    error=abs(float(gross)-out['gross']);assert error<1e-12
                    totals['max_gross_error']=max(totals['max_gross_error'],error)
                    own[week,name]=dict(gross=gross,hours=D(out['charged_hours']),side=side)
                    totals['closed']+=1
            for case,fee in [('gross',D(0)),('base',D('.002')),('stress',D('.003'))]:
                for summary in data['cases'][case]:
                    rows=[r for r in data['rows'] if r['year']==summary['year']]
                    values=[];censored={key:0 for key in ('weekday','short')}
                    for row in rows:
                        original=own.get((row['week'],'weekend'))
                        if original is None:continue
                        carry=D('.2')*original['hours']/D(365*24) if fee else D(0)
                        values.append(original['gross']-fee-carry)
                        for key in censored:
                            if (row['week'],key) not in own:censored[key]+=1
                    assert len(values)==summary['known']
                    assert abs(float(mean(values)*10000)-summary['mean_bp'])<1e-8
                    assert censored==summary['paired_censored']
            info['independent_outcome_checks']=totals
        print(json.dumps(dict(asset=asset,**{k:v for k,v in info.items() if k!='input_hashes'})),flush=True)
    (ROOT/'research_dispatch_20261016/weekend_cache_audit.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')


if __name__=='__main__':main()
