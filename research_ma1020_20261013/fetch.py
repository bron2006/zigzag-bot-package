"""Public Binance spot M15 volume history. No account, keys or orders."""
from datetime import datetime,timezone
from pathlib import Path
import gzip
import hashlib
import json
import math
import requests
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;START=1767225600000;END=1791417600000;STEP=900000


def validate(rows,cursor):
    if not isinstance(rows,list) or not rows:raise ValueError('No public data')
    for i,r in enumerate(rows):
        if int(r[0])!=cursor+i*STEP or len(r)<8:raise ValueError('Noncontiguous M15')
        o,h,l,c=map(float,r[1:5]);v=float(r[5])
        if not all(math.isfinite(x) for x in (o,h,l,c,v)) or not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError('Invalid OHLCV')


def worker():
    folder=HERE/'cache';folder.mkdir(exist_ok=True);deadline=time.monotonic()+180;session=requests.Session()
    for symbol in ('BTCUSDT','ETHUSDT'):
        if (folder/(symbol+'_complete.json')).exists():continue
        cursor=START;pages=[]
        for page in range(100):
            if time.monotonic()>deadline:raise TimeoutError('Public fetch deadline')
            file=folder/f'{symbol}_{cursor}.json.gz'
            if file.exists():
                with gzip.open(file,'rt',encoding='utf-8') as f:rows=json.load(f)
            else:
                for attempt in range(2):
                    try:
                        r=session.get('https://data-api.binance.vision/api/v3/klines',params=dict(symbol=symbol,interval='15m',startTime=cursor,endTime=min(END-1,cursor+1000*STEP-1),limit=1000),timeout=(5,10));break
                    except requests.exceptions.Timeout:
                        if attempt:raise
                r.raise_for_status();rows=r.json();validate(rows,cursor)
                with gzip.open(file,'xt',encoding='utf-8') as f:json.dump(rows,f)
                time.sleep(.1)
            validate(rows,cursor);pages.append(dict(file=file.name,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
            cursor=int(rows[-1][0])+STEP
            if page%5==0:print(json.dumps(dict(symbol=symbol,pages=page+1,through_utc=datetime.fromtimestamp(cursor/1000,timezone.utc).isoformat())),flush=True)
            if cursor>=END:break
        else:raise ValueError('Page cap')
        (folder/(symbol+'_complete.json')).write_text(json.dumps(dict(symbol=symbol,period='M15',start=START,end=END,pages=pages,complete=True,no_orders=True),indent=2),encoding='utf-8')
        print('Complete public M15: '+symbol,flush=True)


if __name__=='__main__':
    if '--worker' in sys.argv:
        try:worker()
        except Exception as e:print('Public fetch stopped: '+type(e).__name__);sys.exit(1)
    else:
        try:sys.exit(subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],timeout=210).returncode)
        except subprocess.TimeoutExpired:print('Hard deadline; checkpoints retained.');sys.exit(1)
