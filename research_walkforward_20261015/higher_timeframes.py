"""True H1/H4 monthly payoff research on cached broker M5; never execution."""
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
spec=importlib.util.spec_from_file_location('higher_walkforward_base',HERE/'run.py')
wf=importlib.util.module_from_spec(spec);spec.loader.exec_module(wf)
NAMES=wf.NORMALIZED_NAMES+['ret1','ret4','body_ratio','range_rel','atr_ratio','hour_sin','hour_cos','london','new_york','cost_risk']


def aggregate(raw,step):
    if step not in (1800,3600,7200,14400,28800,86400):raise ValueError('Unsupported timeframe')
    rows=[];partial=0
    for bucket,g in raw.groupby(raw.ts//step):
        start=int(bucket)*step
        if g.ts.tolist()!=list(range(start,start+step,300)):
            partial+=1;continue
        rows.append(dict(ts=start,Open=float(g.Open.iloc[0]),High=float(g.High.max()),
                         Low=float(g.Low.min()),Close=float(g.Close.iloc[-1])))
    return pd.DataFrame(rows),partial


def features(bars,step):
    parts=[]
    for _,g in bars.groupby(bars.ts.diff().gt(7*86400).cumsum()):
        if len(g)<200:continue
        close=g.Close;atr=wf.pandas_ta.atr(high=g.High,low=g.Low,close=close,length=14)
        ema50=wf.pandas_ta.ema(close,length=50);ema200=wf.pandas_ta.ema(close,length=200)
        f=pd.DataFrame(index=g.index)
        f['ATR']=atr;f['ATR_REL']=atr/close
        f['ADX']=wf.pandas_ta.adx(high=g.High,low=g.Low,close=close,length=14)['ADX_14']
        f['RSI']=wf.pandas_ta.rsi(close,length=14)
        f['EMA50_DIST']=(close-ema50)/atr;f['EMA200_DIST']=(close-ema200)/atr
        f['ret1']=np.log(close/close.shift(1));f['ret4']=np.log(close/close.shift(4))
        f['body_ratio']=(close-g.Open)/(g.High-g.Low).replace(0,np.nan)
        f['range_rel']=(g.High-g.Low)/close;f['atr_ratio']=atr/atr.shift(1).rolling(48,min_periods=48).median()
        f['decision_ts']=g.ts+step;f['entry_ts']=f.decision_ts+300;f['target_ts']=f.entry_ts+step
        hour=(f.decision_ts%86400)/3600
        f['hour_sin']=np.sin(hour*2*np.pi/24);f['hour_cos']=np.cos(hour*2*np.pi/24)
        s=[wf.session(int(t)) for t in f.decision_ts]
        f['london']=[float(x in ('london','overlap')) for x in s]
        f['new_york']=[float(x in ('new_york','overlap')) for x in s]
        f['cost_risk']=.0004/(1.5*atr);f['momentum']=np.sign(close-g.Open)
        f.iloc[:199]=np.nan;parts.append(f)
    if not parts:return pd.DataFrame(columns=NAMES+['ATR','decision_ts','entry_ts','target_ts','momentum'])
    out=pd.concat(parts).sort_index()
    return out.loc[np.isfinite(out[NAMES]).all(axis=1)&out.ATR.gt(0)].copy()


def eligible(data):
    weekday=pd.to_datetime(data.decision_ts,unit='s',utc=True).dt.weekday.lt(5)
    day=data.decision_ts//86400
    return weekday & ((data.decision_ts%86400)>=3600) & (data.target_ts<=day*86400+20*3600)


def simulate(by_ts,entry_ts,step,side,distance,cost):
    if side not in (-1,1) or distance<=0 or cost<0 or step not in (3600,14400):raise ValueError('Invalid simulation terms')
    first=by_ts.get(entry_ts)
    if first is None:return dict(status='unknown',reason='missing_entry')
    entry=first['Open'];stop=entry-side*distance;target=entry+side*2*distance
    for ts in range(entry_ts,entry_ts+step,300):
        b=by_ts.get(ts)
        if b is None:return dict(status='unknown',reason='path_gap')
        gap=side*(b['Open']-stop)<=0
        hit=b['Low']<=stop if side==1 else b['High']>=stop
        tp=b['High']>=target if side==1 else b['Low']<=target
        if gap or hit or tp:
            price=b['Open'] if gap else stop if hit else target
            return dict(status='closed',reason='gap_stop' if gap else 'stop' if hit else 'target',
                net_R=(side*(price-entry)-cost)/(distance+cost),ambiguous=bool(hit and tp),exit_ts=ts+300,
                entry=entry,exit=price,stop_distance=distance)
    return dict(status='closed',reason='deadline',net_R=(side*(b['Close']-entry)-cost)/(distance+cost),
                ambiguous=False,exit_ts=entry_ts+step,entry=entry,exit=b['Close'],stop_distance=distance)


def action(buy,sell):
    if not np.isfinite([buy,sell]).all():raise ValueError('Nonfinite prediction')
    return 0 if max(buy,sell)<=0 else 1 if buy>=sell else -1


def outcomes(data,by_ts,step):
    out={1:[],-1:[]}
    for _,r in data.iterrows():
        for side in (1,-1):out[side].append(simulate(by_ts,int(r.entry_ts),step,side,1.5*float(r.ATR),.0004).get('net_R',np.nan))
    return {side:pd.Series(values,index=data.index) for side,values in out.items()}


def summary(rows):
    known=[r for r in rows if r['status']=='closed'];v=np.array([r['net_R'] for r in known])
    gain=v[v>0].sum();loss=-v[v<0].sum()
    return dict(selected=len(rows),closed=len(known),unknown=len(rows)-len(known),wins=int((v>0).sum()),
        sum_R=float(v.sum()),mean_R=float(v.mean()) if len(v) else None,
        profit_factor=float(gain/loss) if loss else None,ambiguous=sum(r['ambiguous'] for r in known),
        reasons={reason:sum(r['reason']==reason for r in rows) for reason in sorted({r['reason'] for r in rows})})


def main():
    raw,hashes,duplicates=wf.load();by_ts={int(r['ts']):r for r in raw.to_dict('records')}
    originals={n:hashlib.sha256((wf.ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'HIGHER_PROTOCOL.md').read_bytes()).hexdigest(),
        input_hashes=hashes,duplicates=duplicates,original_hashes=originals,arms={})
    for tf,step in [('H1',3600),('H4',14400)]:
        bars,partial=aggregate(raw,step);all_data=features(bars,step);data=all_data.loc[eligible(all_data)].copy()
        y=outcomes(data,by_ts,step)
        arm=dict(complete_bars=len(bars),partial_buckets=partial,feature_rows=len(all_data),
            eligible_rows=len(data),known_both_labels=int((y[1].notna()&y[-1].notna()).sum()),
            folds=[],predictions=[],observations=[],summaries=[])
        print(json.dumps(dict(tf=tf,**{k:v for k,v in arm.items() if not isinstance(v,list)})),flush=True)
        for month in pd.date_range('2025-01-01','2026-10-01',freq='MS',tz='UTC'):
            begin=int(month.timestamp());end=min(wf.END,int((month+pd.offsets.MonthBegin()).timestamp()))
            train=data.loc[data.target_ts.lt(begin)&y[1].notna()&y[-1].notna()]
            test=data.loc[data.decision_ts.ge(begin)&data.decision_ts.lt(end)]
            if len(train)<300:raise ValueError('Insufficient training '+tf)
            scaler=StandardScaler().fit(train[NAMES]);pred={}
            for side in (1,-1):
                model=lgb.LGBMRegressor(objective='regression',n_estimators=100,num_leaves=7,max_depth=3,
                    learning_rate=.05,min_child_samples=50,random_state=42,n_jobs=2,
                    deterministic=True,force_col_wise=True,verbosity=-1)
                model.fit(scaler.transform(train[NAMES]),y[side].loc[train.index])
                pred[side]=model.predict(scaler.transform(test[NAMES])) if len(test) else []
            sides=[action(b,s) for b,s in zip(pred[1],pred[-1])]
            fold=dict(month=month.strftime('%Y-%m'),train=len(train),train_max_target=int(train.target_ts.max()),
                test_begin=begin,forecasts=len(test),selected=sum(s!=0 for s in sides))
            if fold['train_max_target']>=begin:raise ValueError('Target leakage')
            arm['folds'].append(fold);print(json.dumps(dict(tf=tf,**fold)),flush=True)
            for (_,r),side,buy,sell in zip(test.iterrows(),sides,pred[1],pred[-1]):
                arm['predictions'].append(dict(decision_ts=int(r.decision_ts),side=side,
                    expected_buy_R=float(buy),expected_sell_R=float(sell)))
                if not side:continue
                for scenario,cost in [('base',.0002),('stress',.0004)]:
                    o=simulate(by_ts,int(r.entry_ts),step,side,1.5*float(r.ATR),cost)
                    row=dict(decision_ts=int(r.decision_ts),entry_ts=int(r.entry_ts),planned_target_ts=int(r.target_ts),
                        month=fold['month'],side=side,scenario=scenario,**o)
                    if o['status']=='closed':
                        for name,control in [('buy',1),('sell',-1),('momentum',int(r.momentum) or 1)]:
                            result=simulate(by_ts,int(r.entry_ts),step,control,1.5*float(r.ATR),cost)
                            row['excess_'+name]=o['net_R']-result['net_R'] if result['status']=='closed' else None
                    arm['observations'].append(row)
        checks=[]
        for scenario in ('base','stress'):
            rows=[r for r in arm['observations'] if r['scenario']==scenario]
            for fold in arm['folds']:
                arm['summaries'].append(dict(scenario=scenario,month=fold['month'],**summary([r for r in rows if r['month']==fold['month']])))
            for year in (2025,2026):
                yr=[r for r in rows if r['month'].startswith(str(year))]
                # A control can remain censored even if actual selected side closed early.
                complete=[r for r in yr if r['status']=='closed' and all(r.get('excess_'+k) is not None for k in ('buy','sell','momentum'))]
                s=dict(year=year,scenario=scenario,**summary(yr),daily_R_ci=wf.bootstrap(yr,'net_R',year),
                    control_complete=len(complete),control_censored=sum(r['status']=='closed' for r in yr)-len(complete),
                    excess_ci={k:wf.bootstrap(complete,'excess_'+k,year) for k in ('buy','sell','momentum')})
                arm['summaries'].append(s);print(json.dumps(dict(tf=tf,**s)),flush=True)
                if scenario=='stress':checks.append(s)
        late=checks[-1]
        arm['gate']=bool(all(s['closed']>=50 and s['unknown']==0 and s['control_censored']==0 and s['sum_R']>0 for s in checks)
            and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['excess_ci'].values()))
        report['arms'][tf]=arm
    for name,digest in originals.items():
        if hashlib.sha256((wf.ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Original artifact changed')
    (HERE/'higher_result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({tf:arm['gate'] for tf,arm in report['arms'].items()}),flush=True)


if __name__=='__main__':main()
