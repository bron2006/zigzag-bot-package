"""Bounded public current rules/quotes probe, no keys, orders or accounts."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import urlopen


def get(base,path,params):
    with urlopen(base+path+'?'+urlencode(params),timeout=6) as response:return json.load(response)


def worker():
    out={'retrieved_utc':datetime.now(timezone.utc).isoformat(),'current_not_historical':True,
         'account_permission_checked':False,'orders':0,'symbols':{}}
    coin_info=get('https://dapi.binance.com','/dapi/v1/exchangeInfo',{})
    for asset in ('BTC','ETH'):
        pair=asset+'USDT';future=asset+'USD_PERP'
        rules=get('https://data-api.binance.vision','/api/v3/exchangeInfo',{'symbol':pair})['symbols'][0]
        spot=get('https://data-api.binance.vision','/api/v3/ticker/bookTicker',{'symbol':pair})
        derivative=get('https://dapi.binance.com','/dapi/v1/ticker/bookTicker',{'symbol':future})[0]
        coin=next(r for r in coin_info['symbols'] if r['symbol']==future)
        out['symbols'][asset]={'spot_rules':rules['filters'],'future_rules':coin['filters'],
            'contract_face_usd':coin['contractSize'],'spot_quote':spot,'future_quote':derivative,
            'spot_quote_receipt_not_exchange_timestamp':True,'simultaneous_quotes':False,
            'illustrative_0001_funding_on_900_usd':.09,
            'eligibility_unverified':True,'actual_account_fees_unverified':True}
    (Path(__file__).parent/'funding_execution_probe_result.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    if '--worker' in sys.argv:worker()
    else:subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],timeout=55,check=True)
