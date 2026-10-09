"""Separate Decimal cash ledger reconstruction; does not import simulator."""
from datetime import datetime,timezone
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).parent


def prices(asset,leg):
    cache=ROOT/'inverse_price_cache'
    manifest=json.loads((cache/f'{asset}_{leg}_complete.json').read_text())
    out={}
    for name in manifest['pages']:
        with gzip.open(cache/name,'rt',encoding='utf-8') as stream:
            for row in json.load(stream):
                ts=int(row[0])
                if ts in out:raise AssertionError('Duplicate price')
                out[ts]=D(row[1])
    return out


def main():
    report=json.loads((ROOT/'inverse_hedge_result.json').read_text())
    batched=json.loads((ROOT/'batched_funding_result.json').read_text())
    checked=0;batch_checked=0
    for name,digest in report['hashes'].items():
        cache='inverse_price_cache' if '_spot_' in name or '_mark_' in name else 'funding_history_cache'
        assert hashlib.sha256((ROOT/cache/name).read_bytes()).hexdigest()==digest
    for asset in ('BTC','ETH'):
        spot=prices(asset,'spot');mark=prices(asset,'mark');funding=[]
        paths=json.loads((ROOT/'funding_coin_history_result.json').read_text())['symbols'][asset+'USD_PERP']['cache_hashes']
        for name in paths:
            with gzip.open(ROOT/'funding_history_cache'/name,'rt',encoding='utf-8') as stream:funding.extend(json.load(stream))
        for year in (2024,2025):
            start=int(datetime(year,1,1,1,tzinfo=timezone.utc).timestamp()*1000)
            end=int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()*1000)-3600000
            chosen=[r for r in funding if start<=int(r['fundingTime'])<=end]
            expected=(366 if year==2024 else 365)*3-1
            assert len(chosen)==expected
            for stress in (False,True):
                fs=D('.002' if stress else '.001');ff=D('.001' if stress else '.0005')
                # Full entry purchase, settlement ledger, full closing proceeds.
                cash=D(1000)-(D(900)/mark[start])*(1+ff)*spot[start]*(1+fs)
                gross=D(0);conversion=D(0)
                for r in chosen:
                    hour=(int(r['fundingTime'])//3600000)*3600000
                    flow=D(900)*D(r['fundingRate'])/D(r['markPrice'])*spot[hour]
                    gross+=flow;conversion+=abs(flow)*fs;cash+=flow-abs(flow)*fs
                # Inverse short plus original matched coin = face/current mark.
                cash+=D(900)/mark[end]*(1-ff)*spot[end]*(1-fs)
                result=report['cases'][f'{asset}_{year}_{"stress" if stress else "base"}']
                assert abs(float(cash)-result['ending_cash_usd'])<1e-7
                assert abs(float(gross)-result['gross_funding_usd'])<1e-7
                assert abs(float(conversion)-result['funding_conversion_fee_usd'])<1e-7
                checked+=1
                step=D('.00001' if asset=='BTC' else '.0001')
                def rounded(q,up=False):
                    return (q/step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*step
                bought=rounded(D(900)/mark[start]*(1+ff),True)
                b_cash=D(1000)-bought*spot[start]*(1+fs)
                inventory=bought-D(900)/mark[start]*(1+ff);operations=0
                for r in chosen:
                    hour=int(r['fundingTime'])//3600000*3600000;price=spot[hour]
                    inventory+=D(900)*D(r['fundingRate'])/D(r['markPrice'])
                    if inventory<0:
                        buy=rounded(max(-inventory,D(5)/price),True)
                        b_cash-=buy*price*(1+fs);inventory+=buy;operations+=1
                    sell=rounded(max(D(0),inventory))
                    if sell*price>=5:
                        b_cash+=sell*price*(1-fs);inventory-=sell;operations+=1
                inventory+=D(900)/mark[end]*(1-ff)
                sell=rounded(inventory);b_cash+=sell*spot[end]*(1-fs);inventory-=sell
                b_result=batched['cases'][f'{asset}_{year}_{"stress" if stress else "base"}']
                assert abs(float(b_cash)-b_result['ending_cash_usd'])<1e-7
                assert abs(float(inventory)-b_result['remaining_coin'])<1e-10
                assert operations==b_result['funding_coin_conversion_operations']
                batch_checked+=1
        for stress in ('base','stress'):
            assert report['cases'][f'{asset}_2026_{stress}']['status']=='UNKNOWN'
    print(json.dumps({'independent_decimal_ledgers_checked':checked,'hashes_checked':len(report['hashes']),
        'independent_batched_decimal_ledgers_checked':batch_checked,
        'partial_2026_unknown_cases_checked':4,'result':'PASS'}))


if __name__=='__main__':main()
