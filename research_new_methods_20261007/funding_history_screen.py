"""Premium component only, never orders or realized hedge/NAV backtest."""
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT=Path(__file__).parent
CACHE=ROOT/'funding_history_cache'
SYMBOLS=('BTCUSDT','ETHUSDT')
START=int(datetime(2023,1,1,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp()*1000)


def validate(rows,symbol,start):
    previous=start-1
    for row in rows:
        ts=int(row['fundingTime']);rate=float(row['fundingRate'])
        if row['symbol']!=symbol or not previous<ts<END or ts<start or not math.isfinite(rate):
            raise ValueError('Funding page mismatch/nonascending/nonfinite')
        previous=ts


def summarize(rows):
    years={}
    for row in rows:
        year=str(datetime.fromtimestamp(int(row['fundingTime'])/1000,timezone.utc).year)
        years.setdefault(year,[]).append(row)
    out={}
    for year,part in years.items():
        rates=[float(r['fundingRate']) for r in part]
        gaps=[int(b['fundingTime'])-int(a['fundingTime']) for a,b in zip(part,part[1:])]
        rate_sum=sum(rates)
        out[year]={'observations':len(part),'sum_settled_rate':rate_sum,
            'negative_count':sum(r<0 for r in rates),'positive_count':sum(r>0 for r in rates),
            'min_rate':min(rates),'max_rate':max(rates),'max_observed_gap_hours':max(gaps,default=0)/3600000,
            'gaps_over_8h_tolerance':sum(g>8*3600000+60000 for g in gaps),
            'first_utc':datetime.fromtimestamp(int(part[0]['fundingTime'])/1000,timezone.utc).isoformat(),
            'last_utc':datetime.fromtimestamp(int(part[-1]['fundingTime'])/1000,timezone.utc).isoformat(),
            'partial_year':year=='2026','component_after_004cost_on_arbitrary_2capital':None if year=='2026' else (rate_sum-.004)/2,
            'component_after_008cost_on_arbitrary_2capital':None if year=='2026' else (rate_sum-.008)/2}
    return out


def worker(coin=False):
    symbols=('BTCUSD_PERP','ETHUSD_PERP') if coin else SYMBOLS
    base='https://dapi.binance.com/dapi/v1/fundingRate' if coin else 'https://fapi.binance.com/fapi/v1/fundingRate'
    CACHE.mkdir(exist_ok=True);report={'venue':'COIN-M' if coin else 'USD-M','premium_component_only':True,'actual_execution':False,'orders':0,'production_allowed':False,'symbols':{}}
    for symbol in symbols:
        cursor=START;rows=[];hashes={}
        for page in range(10):
            path=CACHE/f'{symbol}_{cursor}.json.gz'
            if path.exists():
                with gzip.open(path,'rt',encoding='utf-8') as stream:part=json.load(stream)
            else:
                query=urlencode({'symbol':symbol,'startTime':cursor,'endTime':END-1,'limit':1000})
                with urlopen(base+'?'+query,timeout=10) as response:part=json.load(response)
                if not isinstance(part,list):raise ValueError('Unexpected response')
                validate(part,symbol,cursor)
                with gzip.open(path,'xt',encoding='utf-8') as stream:json.dump(part,stream)
                time.sleep(.3)
            validate(part,symbol,cursor);hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            if not part:break
            rows.extend(part);cursor=int(part[-1]['fundingTime'])+1
        else:raise ValueError('Pagination cap reached')
        if not rows or len({int(r['fundingTime']) for r in rows})!=len(rows):raise ValueError('Empty/duplicate history')
        report['symbols'][symbol]={'cache_hashes':hashes,'years':summarize(rows),
            'missing_markprice_count':sum(not r.get('markPrice') for r in rows),
            'overall_gaps_over_8h_tolerance':sum(int(b['fundingTime'])-int(a['fundingTime'])>8*3600000+60000 for a,b in zip(rows,rows[1:]))}
        print(json.dumps({symbol:report['symbols'][symbol]['years']},indent=2),flush=True)
    (ROOT/('funding_coin_history_result.json' if coin else 'funding_history_result.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    if '--worker' in sys.argv:worker('--coin' in sys.argv)
    else:subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker']+(['--coin'] if '--coin' in sys.argv else []),timeout=90,check=True)
