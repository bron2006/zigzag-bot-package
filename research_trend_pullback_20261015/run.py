"""Costed fixed-rule screen; no production config/models/DB/broker imports."""
from collections import Counter
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
h=module('pullback_history',ROOT/'research_walkforward_20261015'/'higher_timeframes.py')
ledger=module('pullback_ledger',ROOT/'research_walkforward_20261015'/'higher_audit.py')
strategy=module('pullback_rule',HERE/'strategy.py');wf=h.wf


def prepared(raw,step):
    bars,partial=h.aggregate(raw,step);f=h.features(bars,step);out=bars.loc[f.index].copy()
    out['ATR']=f.ATR;out['ADX']=f.ADX
    out['EMA50']=out.Close-f.EMA50_DIST*f.ATR;out['EMA200']=out.Close-f.EMA200_DIST*f.ATR
    ema=pd.Series(np.nan,index=bars.index)
    for _,g in bars.groupby(bars.ts.diff().gt(7*86400).cumsum()):
        if len(g)>=20:ema.loc[g.index]=wf.pandas_ta.ema(g.Close,length=20)
    out['EMA20']=ema.loc[out.index]
    return out.to_dict('records'),partial


def replay(intents,by_ts,volume,cost):
    rows=[];blocked=-1;skips=Counter()
    for intent in intents:
        if intent['entry_ts']<blocked:skips['position_open']+=1;continue
        risk=intent['side']*(intent['signal_close']-intent['stop'])
        if risk<4*.0004:skips['decision_risk_cost']+=1;continue
        if not ledger.math.size_position(1000,intent['signal_close'],risk,.0004,
                minimum=volume['minVolume'],step=volume['stepVolume'],maximum=volume['maxVolume']):
            skips['decision_minimum_size']+=1;continue
        first=by_ts.get(intent['entry_ts'])
        if first is None:
            rows.append(dict(**intent,status='unknown',reason='missing_entry',month=pd.Timestamp(intent['decision_ts'],unit='s',tz='UTC').strftime('%Y-%m')));break
        distance=intent['side']*(first['Open']-intent['stop'])
        if distance<4*.0004:skips['entry_gap_geometry_or_cost']+=1;continue
        if not ledger.math.size_position(1000,first['Open'],distance,.0004,
                minimum=volume['minVolume'],step=volume['stepVolume'],maximum=volume['maxVolume']):
            skips['entry_gap_minimum_size']+=1;continue
        outcome=h.simulate(by_ts,intent['entry_ts'],14400,intent['side'],distance,cost)
        row=dict(**intent,**outcome,month=pd.Timestamp(intent['decision_ts'],unit='s',tz='UTC').strftime('%Y-%m'))
        if outcome['status']=='closed':
            blocked=outcome['exit_ts']
            for name,side in [('buy',1),('sell',-1),('momentum',intent['momentum'])]:
                c=h.simulate(by_ts,intent['entry_ts'],14400,side,distance,cost)
                row['excess_'+name]=outcome['net_R']-c['net_R'] if c['status']=='closed' else None
        rows.append(row)
        if outcome['status']=='unknown':break
    return rows,dict(skips)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--symbol',choices=['EURUSD','GBPUSD'],default='EURUSD');args=parser.parse_args()
    raw,hashes,duplicates=wf.load(args.symbol);by_ts={int(r['ts']):r for r in raw.to_dict('records')}
    h1,p1=prepared(raw,3600);h4,p4=prepared(raw,14400);intents=strategy.detect(h1,h4)
    metadata=json.loads((ROOT/'research_schedule_audit_20261014'/'metadata.json').read_text('utf-8'))
    s=next(x for x in metadata['symbols'] if x['name']==args.symbol)['specification']
    volume={k:float(s[k])/100 for k in ('minVolume','stepVolume','maxVolume')}
    originals={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
        input_hashes=hashes,duplicates=duplicates,original_hashes=originals,intents=intents,
        partial_h1=p1,partial_h4=p4,scenarios={},gate=False,symbol=args.symbol)
    if args.symbol=='GBPUSD':report['transfer_protocol_sha256']=hashlib.sha256((HERE/'GBP_PROTOCOL.md').read_bytes()).hexdigest()
    checks=[]
    for scenario,cost in [('base',.0002),('stress',.0004)]:
        rows,skips=replay(intents,by_ts,volume,cost);summaries=[]
        for month in pd.date_range('2024-01-01','2026-10-01',freq='MS',tz='UTC'):
            label=month.strftime('%Y-%m');summaries.append(dict(month=label,**h.summary([r for r in rows if r['month']==label])))
        for year in (2024,2025,2026):
            selected=[r for r in rows if r['month'].startswith(str(year))]
            complete=[r for r in selected if r['status']=='closed' and all(r.get('excess_'+k) is not None for k in ('buy','sell','momentum'))]
            summary=dict(year=year,**h.summary(selected),daily_R_ci=wf.bootstrap(selected,'net_R',year),
                control_censored=sum(r['status']=='closed' for r in selected)-len(complete),
                excess_ci={k:wf.bootstrap(complete,'excess_'+k,year) for k in ('buy','sell','momentum')})
            summaries.append(summary);print(json.dumps(dict(scenario=scenario,**summary)),flush=True)
            if scenario=='stress' and year in (2025,2026):checks.append(summary)
        projected=[dict(r,scenario=scenario) for r in rows if r['month']>='2025-01']
        projection=ledger.ledger(projected,volume['minVolume'],volume['stepVolume'],volume['maxVolume']) if all(r['status']=='closed' for r in projected) else dict(status='unknown_paths')
        report['scenarios'][scenario]=dict(rows=rows,skips=skips,summaries=summaries,projection=projection)
        print(json.dumps(dict(scenario=scenario,raw_intents=len(intents),skips=skips,
            projection={k:v for k,v in projection.items() if k!='trades'})),flush=True)
    cash=report['scenarios']['stress']['projection'].get('year_end_balances',{});late=checks[-1]
    report['gate']=bool(all(s['closed']>=50 and not s['unknown'] and not s['control_censored'] and s['sum_R']>0 for s in checks)
        and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['excess_ci'].values())
        and cash.get('2025',0)>1000 and cash.get('2026',0)>cash.get('2025',1000))
    for name,digest in originals.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    name='result.json' if args.symbol=='EURUSD' else 'result_GBPUSD.json'
    (HERE/name).write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gate=report['gate'])),flush=True)


if __name__=='__main__':main()
