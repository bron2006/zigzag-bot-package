"""H4 feasibility-at-decision and net-dollar learning, isolated research only."""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

HERE=Path(__file__).resolve().parent
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
h=module('feasible_higher','higher_timeframes.py');audit=module('feasible_ledger','higher_audit.py');wf=h.wf
NAMES=h.NAMES+['minimum_risk_fraction','minimum_notional_fraction']


def quantity(price,distance,cost,volume,balance=1000.):
    return audit.math.size_position(balance,price,distance,cost,minimum=volume['minVolume'],
        step=volume['stepVolume'],maximum=volume['maxVolume'],risk_fraction=.005,notional_cap=5)


def attainable(data,close,volume):
    out=data.copy();out['decision_close']=close.loc[out.index]
    out['minimum_risk_fraction']=volume['minVolume']*(1.5*out.ATR+.0004)/1000
    out['minimum_notional_fraction']=volume['minVolume']*out.decision_close/1000
    q=[quantity(float(r.decision_close),1.5*float(r.ATR),.0004,volume) for _,r in out.iterrows()]
    out['decision_units']=q
    return out.loc[out.decision_units.gt(0)].copy()


def dollar_label(result,cost,volume):
    if result['status']!='closed':return np.nan
    q=quantity(result['entry'],result['stop_distance'],cost,volume)
    # net_R is already risk-and-cost-normalized; reconstruct exact price payoff.
    return q*result['net_R']*(result['stop_distance']+cost)


def main():
    metadata_path=wf.ROOT/'research_schedule_audit_20261014'/'metadata.json'
    metadata=json.loads(metadata_path.read_text('utf-8'))
    symbol=next(s for s in metadata['symbols'] if s['name']=='EURUSD')['specification']
    volume={k:float(symbol[k])/100 for k in ('minVolume','stepVolume','maxVolume')}
    raw,hashes,_=wf.load();bt={int(r['ts']):r for r in raw.to_dict('records')}
    bars,_=h.aggregate(raw,14400);f=h.features(bars,14400);f=f.loc[h.eligible(f)]
    data=attainable(f,bars.Close,volume);labels={1:[],-1:[]}
    for _,r in data.iterrows():
        for side in (1,-1):
            o=h.simulate(bt,int(r.entry_ts),14400,side,1.5*float(r.ATR),.0004)
            labels[side].append(dollar_label(o,.0004,volume))
    y={side:pd.Series(values,index=data.index) for side,values in labels.items()}
    original={n:hashlib.sha256((wf.ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'FEASIBLE_PROTOCOL.md').read_bytes()).hexdigest(),
        metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),input_hashes=hashes,
        original_hashes=original,eligible_before=len(f),eligible_attainable=len(data),current_volume_assumptions=volume,
        folds=[],predictions=[],observations=[],summaries=[],projections={})
    for month in pd.date_range('2025-01-01','2026-10-01',freq='MS',tz='UTC'):
        begin=int(month.timestamp());end=min(wf.END,int((month+pd.offsets.MonthBegin()).timestamp()))
        train=data.loc[data.target_ts.lt(begin)&y[1].notna()&y[-1].notna()]
        test=data.loc[data.decision_ts.ge(begin)&data.decision_ts.lt(end)]
        if len(train)<200:raise ValueError('Insufficient attainable cohort')
        scaler=StandardScaler().fit(train[NAMES]);pred={}
        for side in (1,-1):
            model=lgb.LGBMRegressor(objective='regression',n_estimators=100,num_leaves=7,max_depth=3,
                learning_rate=.05,min_child_samples=50,random_state=42,n_jobs=2,
                deterministic=True,force_col_wise=True,verbosity=-1)
            model.fit(scaler.transform(train[NAMES]),y[side].loc[train.index])
            pred[side]=model.predict(scaler.transform(test[NAMES])) if len(test) else []
        sides=[h.action(b,s) for b,s in zip(pred[1],pred[-1])]
        fold=dict(month=month.strftime('%Y-%m'),train=len(train),train_max_target=int(train.target_ts.max()),
            test_begin=begin,forecasts=len(test),selected=sum(s!=0 for s in sides))
        assert fold['train_max_target']<begin
        report['folds'].append(fold);print(json.dumps(fold),flush=True)
        for (_,r),side,buy,sell in zip(test.iterrows(),sides,pred[1],pred[-1]):
            report['predictions'].append(dict(decision_ts=int(r.decision_ts),side=side,
                expected_buy_usd=float(buy),expected_sell_usd=float(sell),decision_units=float(r.decision_units)))
            if not side:continue
            for scenario,cost in [('base',.0002),('stress',.0004)]:
                o=h.simulate(bt,int(r.entry_ts),14400,side,1.5*float(r.ATR),cost)
                row=dict(decision_ts=int(r.decision_ts),entry_ts=int(r.entry_ts),month=fold['month'],
                    side=side,scenario=scenario,**o)
                if o['status']=='closed':
                    for name,control in [('buy',1),('sell',-1),('momentum',int(r.momentum) or 1)]:
                        c=h.simulate(bt,int(r.entry_ts),14400,control,1.5*float(r.ATR),cost)
                        row['excess_'+name]=o['net_R']-c['net_R'] if c['status']=='closed' else None
                report['observations'].append(row)
    checks=[]
    for scenario in ('base','stress'):
        rows=[r for r in report['observations'] if r['scenario']==scenario]
        for fold in report['folds']:
            report['summaries'].append(dict(scenario=scenario,month=fold['month'],**h.summary([r for r in rows if r['month']==fold['month']])))
        for year in (2025,2026):
            yr=[r for r in rows if r['month'].startswith(str(year))]
            known=[r for r in yr if r['status']=='closed' and all(r.get('excess_'+k) is not None for k in ('buy','sell','momentum'))]
            s=dict(year=year,scenario=scenario,**h.summary(yr),control_censored=sum(r['status']=='closed' for r in yr)-len(known),
                daily_R_ci=wf.bootstrap(yr,'net_R',year),excess_ci={k:wf.bootstrap(known,'excess_'+k,year) for k in ('buy','sell','momentum')})
            report['summaries'].append(s);print(json.dumps(s),flush=True)
            if scenario=='stress':checks.append(s)
        if any(r['status']!='closed' for r in rows):
            report['projections'][scenario]=dict(status='unknown_paths',cash_not_computed=True)
        else:
            report['projections'][scenario]=audit.ledger(rows,volume['minVolume'],volume['stepVolume'],volume['maxVolume'])
            print(json.dumps(dict(scenario=scenario,projection={k:v for k,v in report['projections'][scenario].items() if k!='trades'})),flush=True)
    late=checks[-1];cash=report['projections']['stress'].get('year_end_balances',{})
    report['gate']=bool(all(s['closed']>=50 and not s['unknown'] and not s['control_censored'] and s['sum_R']>0 for s in checks)
        and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['excess_ci'].values())
        and cash.get('2025',0)>1000 and cash.get('2026',0)>cash.get('2025',1000))
    for name,digest in original.items():assert hashlib.sha256((wf.ROOT/name).read_bytes()).hexdigest()==digest
    (HERE/'feasible_result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gate=report['gate'])),flush=True)


if __name__=='__main__':main()
