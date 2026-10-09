"""Public spot/mark1h checkpoints, no credentials, isolated bounded network."""
from datetime import datetime,timezone
import gzip
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT=Path(__file__).parent
CACHE=ROOT/'inverse_price_cache'
START=int(datetime(2024,1,1,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp()*1000)
HOUR=3600000


def validate(rows,cursor):
    if not isinstance(rows,list) or not rows:raise ValueError('Empty hourlypage')
    for i,row in enumerate(rows):
        if int(row[0])!=cursor+i*HOUR:raise ValueError('Noncontiguous hourlypage')
        o,h,l,c=map(float,row[1:5])
        if not all(math.isfinite(p) for p in (o,h,l,c)):raise ValueError('Nonfiniteprices')
        if not 0<l<=min(o,c)<=max(o,c)<=h:raise ValueError('Invalidprices')


def worker():
    CACHE.mkdir(exist_ok=True)
    for symbol in ('BTC','ETH'):
        for leg in ('spot','mark'):
            cursor=START;pages=[]
            while cursor<END:
                name=f'{symbol}_{leg}_{cursor}.json.gz';path=CACHE/name
                if path.exists():
                    with gzip.open(path,'rt',encoding='utf-8') as stream:rows=json.load(stream)
                else:
                    if leg=='spot':url='https://data-api.binance.vision/api/v3/klines';pair=symbol+'USDT'
                    else:url='https://dapi.binance.com/dapi/v1/markPriceKlines';pair=symbol+'USD_PERP'
                    query=urlencode({'symbol':pair,'interval':'1h','startTime':cursor,'endTime':min(END-1,cursor+1000*HOUR-1),'limit':1000})
                    with urlopen(url+'?'+query,timeout=10) as response:rows=json.load(response)
                    if not isinstance(rows,list) or not rows:raise ValueError('Missinghourlyhistory')
                    validate(rows,cursor)
                    with gzip.open(path,'xt',encoding='utf-8') as stream:json.dump(rows,stream)
                    time.sleep(.15)
                validate(rows,cursor);pages.append(name);cursor=int(rows[-1][0])+HOUR
                if len(pages)>30:raise ValueError('Pagecap')
                if len(pages)%5==0:print(json.dumps({'asset':symbol,'leg':leg,'pages':len(pages),'cursor_utc':datetime.fromtimestamp(cursor/1000,timezone.utc).isoformat()}),flush=True)
            (CACHE/f'{symbol}_{leg}_complete.json').write_text(json.dumps({'pages':pages,'start':START,'end':END,'symbol':symbol,'leg':leg,'complete':True}),encoding='utf-8')
            print(json.dumps({'asset':symbol,'leg':leg,'completed':True,'pages':len(pages)}),flush=True)


if __name__=='__main__':
    if '--worker' in sys.argv:worker()
    else:subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],timeout=240,check=True)
