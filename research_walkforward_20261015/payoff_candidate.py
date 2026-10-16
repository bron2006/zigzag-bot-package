"""Conditional payoff learning, never an executor or account ledger."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('payoff_walkforward_base',HERE/'run.py')
wf=importlib.util.module_from_spec(spec);spec.loader.exec_module(wf)
EXTRA=['ret1','ret4','body_ratio','range_rel','atr_ratio','hour_sin','hour_cos','london','new_york','cost_risk']
NAMES=wf.NORMALIZED_NAMES+EXTRA


def enrich(bars,data):
    out=data.copy();extra=pd.DataFrame(index=bars.index)
    for _,g in bars.groupby(bars.ts.diff().ne(900).cumsum()):
        close=g.Close
        extra.loc[g.index,'ret1']=np.log(close/close.shift(1))
        extra.loc[g.index,'ret4']=np.log(close/close.shift(4))
        if len(g)>=200:
            atr=wf.pandas_ta.atr(high=g.High,low=g.Low,close=g.Close,length=14)
            extra.loc[g.index,'atr_ratio']=atr/atr.shift(1).rolling(48,min_periods=48).median()
    extra['body_ratio']=(bars.Close-bars.Open)/(bars.High-bars.Low).replace(0,np.nan)
    extra['range_rel']=(bars.High-bars.Low)/bars.Close
    for name in ('ret1','ret4','atr_ratio','body_ratio','range_rel'):out[name]=extra.loc[out.index,name]
    hours=(out.decision_ts%86400)/3600
    out['hour_sin']=np.sin(hours*2*np.pi/24);out['hour_cos']=np.cos(hours*2*np.pi/24)
    sessions=[wf.session(int(t)) for t in out.decision_ts]
    out['london']=[float(s in ('london','overlap')) for s in sessions]
    out['new_york']=[float(s in ('new_york','overlap')) for s in sessions]
    out['cost_risk']=.0004/(1.5*out.ATR)
    return out.loc[np.isfinite(out[NAMES]).all(axis=1)].copy()


def action(buy,sell):
    if not np.isfinite([buy,sell]).all():raise ValueError('Invalid predicted return')
    if max(buy,sell)<=0:return 0
    return 1 if buy>=sell else -1


def labels(data,by_ts):
    y={1:[], -1:[]}
    for _,r in data.iterrows():
        path=[by_ts.get(int(r.entry_ts)+j*300) for j in range(3)]
        for side in (1,-1):
            result=wf.simulate(path,side,1.5*float(r.ATR),.0004)
            y[side].append(result.get('net_R',np.nan))
    return {side:pd.Series(values,index=data.index) for side,values in y.items()}


def main():
    raw,hashes,duplicates=wf.load();by_ts={int(r['ts']):r for r in raw.to_dict('records')}
    bars=wf.m15(raw);data=enrich(bars,wf.dataset(bars,by_ts));targets=labels(data,by_ts)
    originals={n:hashlib.sha256((wf.ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PAYOFF_PROTOCOL.md').read_bytes()).hexdigest(),
        features=NAMES,feature_rows=len(data),hashes=hashes,duplicates=duplicates,original_hashes=originals,
        folds=[],predictions=[],observations=[],summaries=[])
    for month in pd.date_range('2025-01-01','2026-10-01',freq='MS',tz='UTC'):
        begin=int(month.timestamp());end=min(wf.END,int((month+pd.offsets.MonthBegin()).timestamp()))
        train=data.loc[data.target_ts.lt(begin)&targets[1].notna()&targets[-1].notna()]
        test=data.loc[data.decision_ts.ge(begin)&data.decision_ts.lt(end)]
        if len(train)<1000:raise ValueError('Insufficient training')
        scaler=StandardScaler().fit(train[NAMES]);predictions={}
        for side in (1,-1):
            model=lgb.LGBMRegressor(objective='regression',n_estimators=100,num_leaves=7,max_depth=3,
                learning_rate=.05,min_child_samples=200,random_state=42,n_jobs=2,
                deterministic=True,force_col_wise=True,verbosity=-1)
            model.fit(scaler.transform(train[NAMES]),targets[side].loc[train.index])
            predictions[side]=model.predict(scaler.transform(test[NAMES])) if len(test) else []
        sides=[action(b,s) for b,s in zip(predictions[1],predictions[-1])]
        fold=dict(month=month.strftime('%Y-%m'),train=len(train),max_train_target=int(train.target_ts.max()),
            test_begin=begin,forecasts=len(test),selected=sum(s!=0 for s in sides),
            train_mean_buy=float(targets[1].loc[train.index].mean()),train_mean_sell=float(targets[-1].loc[train.index].mean()))
        if fold['max_train_target']>=begin:raise ValueError('Target leakage')
        report['folds'].append(fold);print(json.dumps(fold),flush=True)
        for (_,r),side,buy,sell in zip(test.iterrows(),sides,predictions[1],predictions[-1]):
            report['predictions'].append(dict(decision_ts=int(r.decision_ts),expected_buy_R=float(buy),expected_sell_R=float(sell),side=side))
            if not side:continue
            path=[by_ts.get(int(r.entry_ts)+j*300) for j in range(3)]
            for scenario,cost in [('base',.0002),('stress',.0004)]:
                o=wf.simulate(path,side,1.5*float(r.ATR),cost)
                row=dict(decision_ts=int(r.decision_ts),month=fold['month'],side=side,
                    move=float(r.move) if r.known_path else None,scenario=scenario,session=wf.session(int(r.decision_ts)),**o)
                if o['status']=='closed':
                    for name,control in [('buy',1),('sell',-1),('momentum',int(r.momentum) or 1)]:
                        row['excess_'+name]=o['net_R']-wf.simulate(path,control,1.5*float(r.ATR),cost)['net_R']
                report['observations'].append(row)
    checks=[]
    for scenario in ('base','stress'):
        rows=[r for r in report['observations'] if r['scenario']==scenario]
        for fold in report['folds']:
            report['summaries'].append(dict(scenario=scenario,month=fold['month'],**wf.summarize([r for r in rows if r['month']==fold['month']])))
        for year in (2025,2026):
            yr=[r for r in rows if r['month'].startswith(str(year))]
            summary=dict(year=year,scenario=scenario,**wf.summarize(yr),daily_R_ci=wf.bootstrap(yr,'net_R',year),
                excess_ci={k:wf.bootstrap(yr,'excess_'+k,year) for k in ('buy','sell','momentum')})
            report['summaries'].append(summary);print(json.dumps(summary),flush=True)
            if scenario=='stress':checks.append(summary)
    late=checks[-1]
    report['gate']=bool(all(r['closed']>=100 and r['unknown']==0 and r['sum_R']>0 for r in checks)
        and late['closed']>=200 and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['excess_ci'].values()))
    for name,digest in originals.items():
        if hashlib.sha256((wf.ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Original artifact changed')
    (HERE/'payoff_result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gate=report['gate'])),flush=True)


if __name__=='__main__':main()
