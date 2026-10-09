"""Offline inverse hedge approximation. No account, order or network API."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from fetch_inverse_prices import CACHE, START, END, HOUR, validate
from funding_history_screen import CACHE as FUNDING_CACHE
from inverse_hedge_math import equity_usd, funding_usd_if_immediately_converted

ROOT=Path(__file__).parent
FACE=900.0
CAPITAL=1000.0


def load_prices(asset,leg):
    manifest=json.loads((CACHE/f'{asset}_{leg}_complete.json').read_text())
    if (manifest['start'],manifest['end'],manifest['symbol'],manifest['leg'],manifest['complete'])!=(START,END,asset,leg,True):
        raise ValueError('Manifest mismatch')
    rows=[];cursor=START;hashes={}
    for name in manifest['pages']:
        if name!=f'{asset}_{leg}_{cursor}.json.gz':raise ValueError('Unexpected page')
        path=CACHE/name
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path,'rt',encoding='utf-8') as stream:part=json.load(stream)
        validate(part,cursor);rows.extend(part);cursor=int(part[-1][0])+HOUR
    if cursor!=END:raise ValueError('Incomplete hourly coverage')
    return {int(r[0]):float(r[1]) for r in rows},hashes


def load_funding(asset):
    report=json.loads((ROOT/'funding_coin_history_result.json').read_text())['symbols'][asset+'USD_PERP']
    rows=[]
    for name,digest in report['cache_hashes'].items():
        path=FUNDING_CACHE/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Funding hash mismatch')
        with gzip.open(path,'rt',encoding='utf-8') as stream:rows.extend(json.load(stream))
    times=[int(r['fundingTime']) for r in rows]
    if times!=sorted(set(times)):raise ValueError('Duplicate funding')
    if any(r['symbol']!=asset+'USD_PERP' for r in rows):raise ValueError('Wrong funding asset')
    return rows,report['cache_hashes']


def funding_issues(rows,start,end):
    """Require the frozen eight-hour schedule, including both coverage edges."""
    chosen=[r for r in rows if start<=int(r['fundingTime'])<end]
    expected=list(range(((start+8*HOUR-1)//(8*HOUR))*(8*HOUR),end,8*HOUR))
    # Audit the nominal boundary record even if its few-ms delay is after
    # the final snapshot; it remains excluded from credited cashflows.
    audited=[r for r in rows if start<=int(r['fundingTime'])<end+60000
             and (int(r['fundingTime'])//HOUR)*HOUR<end]
    buckets=[(int(r['fundingTime'])//HOUR)*HOUR for r in audited]
    issues=[]
    if buckets!=expected:issues.append('missing_or_unexpected_8h_settlement')
    for r in chosen:
        try:mark=float(r['markPrice']);rate=float(r['fundingRate'])
        except (ValueError,KeyError,TypeError):issues.append('missing_settlement_mark_or_rate');break
        if not math.isfinite(mark) or mark<=0 or not math.isfinite(rate):
            issues.append('invalid_settlement_mark_or_rate');break
        if int(r['fundingTime'])%HOUR>60000:issues.append('unexpected_settlement_time');break
    return chosen,issues


def simulate(spot,mark,rows,start,end,stress=False):
    # end is the final Open snapshot; no later settlement is credited.
    chosen,issues=funding_issues(rows,start,end+1)
    if issues:return {'status':'UNKNOWN','issues':issues,'funding_records':len(chosen)}
    hours=list(range(start,end+HOUR,HOUR))
    if any(t not in spot or t not in mark for t in hours):raise ValueError('Unpaired price timestamp')
    fs=.002 if stress else .001;ff=.001 if stress else .0005
    s0,m0=spot[start],mark[start];collateral=FACE/m0
    principal=collateral*s0
    entry_future_fee=FACE*ff/m0*s0
    entry_spot_fee=(principal+entry_future_fee)*fs
    cash=CAPITAL-principal-entry_future_fee-entry_spot_fee
    initial_cash=cash;min_cash=cash;gross_funding=conversion_fee=0.0
    peak=CAPITAL;max_dd=0.0;min_margin_ratio=float('inf');cursor=0
    # Event timestamps, not the earlier hourly timestamp, receive funding.
    def snapshot(t):
        nonlocal peak,max_dd,min_margin_ratio
        state=equity_usd(collateral,FACE,m0,mark[t],spot[t],cash)
        wealth=state['equity_usd'];peak=max(peak,wealth)
        max_dd=min(max_dd,wealth/peak-1)
        min_margin_ratio=min(min_margin_ratio,state['margin_coin']/(FACE/mark[t]))
    for t in hours:
        snapshot(t)
        next_t=min(t+HOUR,end+1)
        while cursor<len(chosen) and int(chosen[cursor]['fundingTime'])<next_t:
            r=chosen[cursor];ts=int(r['fundingTime'])
            if ts<t:raise ValueError('Funding event ordering')
            flow=funding_usd_if_immediately_converted(FACE,float(r['fundingRate']),float(r['markPrice']),spot[t])
            fee=abs(flow)*fs;gross_funding+=flow;conversion_fee+=fee
            cash+=flow-fee;min_cash=min(min_cash,cash);snapshot(t);cursor+=1
    if cursor!=len(chosen):raise ValueError('Unconsumed funding')
    end_state=equity_usd(collateral,FACE,m0,mark[end],spot[end],cash)
    exit_future_fee=FACE*ff/mark[end]*spot[end]
    exit_spot_fee=(end_state['margin_coin']*spot[end]-exit_future_fee)*fs
    ending_cash=end_state['equity_usd']-exit_future_fee-exit_spot_fee
    peak=max(peak,ending_cash);max_dd=min(max_dd,ending_cash/peak-1)
    basis=end_state['margin_coin']*spot[end]-principal
    fees=entry_future_fee+entry_spot_fee+exit_future_fee+exit_spot_fee+conversion_fee
    profit=ending_cash-CAPITAL
    if not math.isclose(profit,gross_funding+basis-fees,abs_tol=1e-8):raise ValueError('Ledger reconciliation failed')
    return {'status':'APPROXIMATION_ONLY','initial_cash_usd':initial_cash,'minimum_cash_usd':min_cash,
        'ending_cash_usd':ending_cash,'profit_usd':profit,'return_on_1000':profit/CAPITAL,
        'gross_funding_usd':gross_funding,'funding_conversion_fee_usd':conversion_fee,
        'basis_valuation_change_usd':basis,'all_modeled_fees_usd':fees,
        'hourly_proxy_drawdown':max_dd,'minimum_margin_coin_over_notional_coin':min_margin_ratio,
        'maintenance_1_5_10_percent_pass':[min_margin_ratio>x for x in (.01,.05,.10)],
        'cash_reserve_nonnegative':min_cash>=0,'funding_records':len(chosen),
        'settlement_prices_are_hourly_proxies':True,'actual_execution':False}


def main():
    out={'orders':0,'production_allowed':False,'historical_fill_audit':False,
         'USDT_assumed_equal_USD':True,'instant_subminimum_funding_conversion_not_executable':True,
         'ADL_and_withdrawal_permissions_not_modeled':True,'cases':{},'hashes':{}}
    for asset in ('BTC','ETH'):
        spot,hs=load_prices(asset,'spot');mark,hm=load_prices(asset,'mark');rows,hf=load_funding(asset)
        out['hashes'].update(hs);out['hashes'].update(hm);out['hashes'].update(hf)
        for year in (2024,2025,2026):
            start=int(datetime(year,1,1,1,tzinfo=timezone.utc).timestamp()*1000)
            boundary=min(END,int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()*1000))
            for stress in (False,True):
                key=f'{asset}_{year}_{"stress" if stress else "base"}'
                out['cases'][key]=simulate(spot,mark,rows,start,boundary-HOUR,stress)
    (ROOT/'inverse_hedge_result.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out['cases'],indent=2))


if __name__=='__main__':main()
