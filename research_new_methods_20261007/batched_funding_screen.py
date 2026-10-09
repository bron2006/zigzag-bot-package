"""Offline minimum-operation scenario, current rules on historical proxies."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
import json
import math
from pathlib import Path
from inverse_hedge_screen import load_prices,load_funding,funding_issues,FACE,CAPITAL,END,HOUR


def quantity(value,step,up=False):
    return float((Decimal(str(value))/Decimal(str(step))).to_integral_value(
        rounding=ROUND_CEILING if up else ROUND_FLOOR)*Decimal(str(step)))


def simulate(spot,mark,rows,start,end,step,stress=False):
    chosen,issues=funding_issues(rows,start,end+1)
    if issues:return {'status':'UNKNOWN','issues':issues}
    fs=.002 if stress else .001;ff=.001 if stress else .0005
    s0,m0=spot[start],mark[start];c=FACE/m0
    bought=quantity(c+FACE*ff/m0,step,True)
    cash=CAPITAL-bought*s0*(1+fs);initial=cash
    coins=bought-c-FACE*ff/m0
    fees=bought*s0*fs+FACE*ff/m0*s0
    min_cash=cash;max_residual=coins*s0;peak=CAPITAL;dd=0.0;trades=0;cursor=0
    nominal_funding=0.0;carry_effect=0.0;previous_spot=s0
    def snapshot(t):
        nonlocal peak,dd,max_residual
        wealth=cash+(FACE/mark[t]+coins)*spot[t]
        peak=max(peak,wealth);dd=min(dd,wealth/peak-1)
        max_residual=max(max_residual,coins*spot[t])
    def convert(price):
        nonlocal coins,cash,trades,fees,min_cash
        if coins<0:
            buy=quantity(max(-coins,5/price),step,True)
            cash-=buy*price*(1+fs);fees+=buy*price*fs;coins+=buy;trades+=1
        sell=quantity(max(0,coins),step)
        if sell*price>=5:
            cash+=sell*price*(1-fs);fees+=sell*price*fs;coins-=sell;trades+=1
        min_cash=min(min_cash,cash)
    for t in range(start,end+HOUR,HOUR):
        carry_effect+=coins*(spot[t]-previous_spot);previous_spot=spot[t]
        snapshot(t)
        while cursor<len(chosen) and int(chosen[cursor]['fundingTime'])<min(t+HOUR,end+1):
            r=chosen[cursor];payment=FACE*float(r['fundingRate'])/float(r['markPrice'])
            coins+=payment;nominal_funding+=payment*spot[t];snapshot(t)
            convert(spot[t]);snapshot(t);cursor+=1
    coins+=FACE/mark[end]-FACE*ff/mark[end]
    fees+=FACE*ff/mark[end]*spot[end]
    sell=quantity(coins,step)
    if sell*spot[end]<5:raise ValueError('Exit below minimum')
    cash+=sell*spot[end]*(1-fs);fees+=sell*spot[end]*fs;coins-=sell
    ending_equity=cash+coins*spot[end]
    peak=max(peak,ending_equity);dd=min(dd,ending_equity/peak-1)
    if coins<-1e-12:raise ValueError('Negative exit inventory')
    # Reconstruct PnL with the measured residual-price/reinvestment effect.
    entry_principal=FACE/m0*s0;basis=FACE/mark[end]*spot[end]-entry_principal
    residual_effect=carry_effect
    if not math.isclose(ending_equity-CAPITAL,nominal_funding+basis-fees+carry_effect,abs_tol=1e-7):
        raise ValueError('Coin carry ledger failed reconciliation')
    return {'status':'CURRENT_RULES_PROXY_ONLY','ending_cash_usd':cash,
        'remaining_coin':coins,'remaining_coin_value_usd':coins*spot[end],
        'ending_marked_equity_usd':ending_equity,'profit_usd':ending_equity-CAPITAL,
        'initial_cash_usd':initial,'minimum_cash_usd':min_cash,'cash_reserve_nonnegative':min_cash>=0,
        'maximum_residual_coin_value_before_exit_usd':max_residual,
        'funding_coin_conversion_operations':trades,'funding_records':len(chosen),
        'gross_funding_at_receipt_proxy_usd':nominal_funding,'all_modeled_fees_usd':fees,
        'basis_change_usd':basis,'residual_price_and_reinvestment_effect_usd':residual_effect,
        'hourly_proxy_drawdown':dd,'current_filters_not_historical':True,'orders':0}


def main():
    out={'production_allowed':False,'actual_execution':False,'cases':{}}
    for asset,step in (('BTC',.00001),('ETH',.0001)):
        spot,_=load_prices(asset,'spot');mark,_=load_prices(asset,'mark');rows,_=load_funding(asset)
        for year in (2024,2025,2026):
            start=int(datetime(year,1,1,1,tzinfo=timezone.utc).timestamp()*1000)
            end=min(END,int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()*1000))-HOUR
            for stress in (False,True):
                out['cases'][f'{asset}_{year}_{"stress" if stress else "base"}']=simulate(spot,mark,rows,start,end,step,stress)
    (Path(__file__).parent/'batched_funding_result.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out['cases'],indent=2))


if __name__=='__main__':main()
