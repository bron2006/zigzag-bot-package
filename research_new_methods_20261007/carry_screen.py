"""Public-only dated-futures executable-side screen; isolated bounded worker."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

FOLDER=Path(__file__).parent

def get(host,path,**params):
    allowed={('https://fapi.binance.com','/fapi/v1/exchangeInfo'),
             ('https://fapi.binance.com','/fapi/v1/time'),
             ('https://fapi.binance.com','/fapi/v1/ticker/bookTicker'),
             ('https://fapi.binance.com','/fapi/v1/depth'),
             ('https://data-api.binance.vision','/api/v3/depth'),
             ('https://data-api.binance.vision','/api/v3/ticker/bookTicker')}
    if (host,path) not in allowed:
        raise ValueError('Only explicitly allowed public GETs')
    with urlopen(host+path+('?' + urlencode(params) if params else ''),timeout=8) as response:
        return json.load(response)

def measure(spot,future,delivery,server_ms):
    ask,bid=float(spot['askPrice']),float(future['bidPrice'])
    if not 0<float(spot['bidPrice'])<=ask or not 0<bid<=float(future['askPrice']):
        raise ValueError('Invalid order book')
    days=(delivery-server_ms)/86400000
    if days<=0:
        raise ValueError('Expired contract')
    gap=bid/ask-1
    return dict(days_to_delivery=days,gross_gap=gap,gross_simple_annualized=gap*365.25/days,
        break_even_total_cost=gap,net_cost_004=gap-.004,net_cost_008=gap-.008,
        stress_simple_annualized_on_illustrative_2x_capital=(gap-.008)/2*365.25/days,
        quoted_common_top_level_quantity=min(float(spot['askQty']),float(future['bidQty'])))

def worker():
    info=get('https://fapi.binance.com','/fapi/v1/exchangeInfo')
    contracts=[s for s in info['symbols'] if s.get('pair') in ('BTCUSDT','ETHUSDT')
        and s.get('contractType') in ('CURRENT_QUARTER','NEXT_QUARTER') and s.get('status')=='TRADING']
    rounds=[]
    for iteration in range(3):
        started=get('https://fapi.binance.com','/fapi/v1/time')['serverTime']
        with ThreadPoolExecutor(max_workers=6) as pool:
            spot_jobs={p:pool.submit(get,'https://data-api.binance.vision','/api/v3/ticker/bookTicker',symbol=p) for p in ('BTCUSDT','ETHUSDT')}
            future_jobs={s['symbol']:pool.submit(get,'https://fapi.binance.com','/fapi/v1/ticker/bookTicker',symbol=s['symbol']) for s in contracts}
            spot={p:job.result() for p,job in spot_jobs.items()}
            futures={p:job.result() for p,job in future_jobs.items()}
        finished=get('https://fapi.binance.com','/fapi/v1/time')['serverTime']
        if finished-started>15000:
            raise ValueError('Acquisition window too wide')
        records=[]
        for s in contracts:
            book=futures[s['symbol']]
            age=finished-int(book['time'])
            records.append(dict(symbol=s['symbol'],pair=s['pair'],contract_type=s['contractType'],
                delivery_ms=s['deliveryDate'],quote_age_ms=age,fresh=-1000<=age<=15000,
                **measure(spot[s['pair']],book,s['deliveryDate'],finished)))
        rounds.append(dict(start_server_ms=started,end_server_ms=finished,spot_raw=spot,futures_raw=futures,records=records))
        time.sleep(.5)
    gates={}
    for s in contracts:
        rows=[next(r for r in batch['records'] if r['symbol']==s['symbol']) for batch in rounds]
        gates[s['symbol']]=all(r['net_cost_008']>0 for r in rows) if all(r['fresh'] for r in rows) else None
    result=dict(fetched_utc=datetime.now(timezone.utc).isoformat(),contracts=[{k:s[k] for k in ('symbol','pair','contractType','deliveryDate','status')} for s in contracts],
        rounds=rounds,stress_cost_screen_pass=gates,not_confirmed_account_profit=True)
    (FOLDER/'carry_snapshot.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gates=gates,latest=rounds[-1]['records']),indent=2))

def average_fill(levels,quantity):
    if quantity<=0:
        raise ValueError('Quantity must be positive')
    remaining,value=quantity,0.
    for price,size in levels:
        price,size=float(price),float(size)
        if price<=0 or size<0:
            raise ValueError('Invalid depth')
        used=min(remaining,size)
        value+=used*price
        remaining-=used
        if remaining<=1e-12:
            return value/quantity
    return None

def depth_worker():
    original=json.loads((FOLDER/'carry_snapshot.json').read_text(encoding='utf-8'))
    selected=[s for s in original['contracts'] if original['stress_cost_screen_pass'][s['symbol']] is True]
    start=get('https://fapi.binance.com','/fapi/v1/time')['serverTime']
    with ThreadPoolExecutor(max_workers=6) as pool:
        spot_jobs={p:pool.submit(get,'https://data-api.binance.vision','/api/v3/depth',symbol=p,limit=100) for p in sorted(set(s['pair'] for s in selected))}
        future_jobs={s['symbol']:pool.submit(get,'https://fapi.binance.com','/fapi/v1/depth',symbol=s['symbol'],limit=100) for s in selected}
        spot={p:j.result() for p,j in spot_jobs.items()}
        futures={p:j.result() for p,j in future_jobs.items()}
    end=get('https://fapi.binance.com','/fapi/v1/time')['serverTime']
    if end-start>15000:
        raise ValueError('Depth acquisition window too wide')
    records=[]
    for contract in selected:
        name,pair=contract['symbol'],contract['pair']
        book=futures[name]
        fresh=-1000<=end-int(book['E'])<=15000
        asks=spot[pair]['asks']; bids=book['bids']
        if not asks or not bids:
            raise ValueError('Empty depth')
        if [float(p) for p,q in asks]!=sorted(float(p) for p,q in asks) or [float(p) for p,q in bids]!=sorted((float(p) for p,q in bids),reverse=True):
            raise ValueError('Depth ordering invalid')
        days=(contract['deliveryDate']-end)/86400000
        for notional in (1000,5000,10000):
            quantity=notional/float(asks[0][0])
            buy,sell=average_fill(asks,quantity),average_fill(bids,quantity)
            record=dict(symbol=name,spot_notional_reference=notional,base_quantity=quantity,fresh=fresh,days_to_delivery=days)
            if buy is None or sell is None:
                record['status']='insufficient_visible_depth'
            elif not fresh:
                record['status']='stale_depth'
            else:
                gap=sell/buy-1
                record.update(status='measured',spot_average_ask=buy,futures_average_bid=sell,gross_gap=gap,
                    net_after_extra_008_buffer=gap-.008,
                    simple_annualized_on_illustrative_2x_capital=(gap-.008)/2*365.25/days,
                    residual_after_illustrative_3pct_capital_hurdle=gap-.008-2*.03*days/365.25)
            records.append(record)
    result=dict(start_server_ms=start,end_server_ms=end,spot_raw=spot,futures_raw=futures,records=records,
                volume_reference_is_not_order_size_recommendation=True,
                extra_008_is_conservative_buffer_not_verified_tariff=True)
    (FOLDER/'carry_depth_snapshot.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(records,indent=2))

if __name__=='__main__':
    if '--worker' in sys.argv:
        depth_worker() if '--depth' in sys.argv else worker()
    else:
        try:
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker']+(['--depth'] if '--depth' in sys.argv else []),timeout=90,check=True)
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            print('Public screen failed safely; no opportunity asserted.')
            sys.exit(1)
