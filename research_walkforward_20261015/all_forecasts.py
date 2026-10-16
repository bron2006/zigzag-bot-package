"""All forecasts diagnostic; no strategy activation, calibration fit or thresholds."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import importlib.util
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('walkforward_research_base',HERE/'run.py')
wf=importlib.util.module_from_spec(spec);spec.loader.exec_module(wf)


def diagnostics(rows):
    known=[r for r in rows if r['move'] is not None]
    decided=[r for r in known if r['move']!=0]
    if not decided:return dict(forecasts=len(rows),nonflat=0,flat=len(known),unknown=len(rows)-len(known))
    p=np.array([r['p_up'] for r in decided]);y=np.array([r['move']>0 for r in decided],dtype=int)
    prior=np.array([r['prior_up'] for r in decided]);pred=p>=.5
    q=np.clip(p,1e-12,1-1e-12);q0=np.clip(prior,1e-12,1-1e-12)
    correct=(pred==y).astype(float);brier=(p-y)**2;baseline_brier=(prior-y)**2
    bins=[]
    for i in range(10):
        mask=(p>=i/10)&((p<(i+1)/10) if i<9 else (p<=1))
        bins.append(dict(lo=i/10,hi=(i+1)/10,n=int(mask.sum()),
                         mean_p_up=float(p[mask].mean()) if mask.any() else None,
                         actual_up=float(y[mask].mean()) if mask.any() else None))
    return dict(forecasts=len(rows),nonflat=len(decided),flat=len(known)-len(decided),unknown=len(rows)-len(known),
        accuracy=float(correct.mean()),past_majority_accuracy=float(((prior>=.5)==y).mean()),
        always_up_accuracy=float(y.mean()),always_down_accuracy=float(1-y.mean()),
        auc=float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
        brier=float(brier.mean()),prior_brier=float(baseline_brier.mean()),constant50_brier=.25,
        brier_improvement=float((baseline_brier-brier).mean()),
        logloss=float(-(y*np.log(q)+(1-y)*np.log(1-q)).mean()),
        prior_logloss=float(-(y*np.log(q0)+(1-y)*np.log(1-q0)).mean()),
        probability_range=[float(p.min()),float(p.max())],
        probability_quantiles=np.quantile(p,[.01,.1,.5,.9,.99]).tolist(),calibration_bins=bins)


def paired_values(rows):
    decided=[r for r in rows if r['move'] is not None and r['move']!=0]
    p=np.array([r['p_up'] for r in decided]);y=np.array([r['move']>0 for r in decided],dtype=int)
    prior=np.array([r['prior_up'] for r in decided]);correct=((p>=.5)==y).astype(float)
    return decided,dict(brier=(prior-y)**2-(p-y)**2,
        accuracy_majority=correct-((prior>=.5)==y),accuracy_up=correct-y,accuracy_down=correct-(1-y))


def interval(rows,year):
    decided,values=paired_values(rows)
    if not decided:return {k:None for k in values}
    begin=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp())
    end=min(wf.END,int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()));days=(end-begin+86399)//86400
    offsets=np.array([(r['decision_ts']-begin)//86400 for r in decided],dtype=int)
    if (offsets<0).any() or (offsets>=days).any():raise ValueError('Wrong bootstrap year')
    counts=np.bincount(offsets,minlength=days);rng=np.random.default_rng(20261015)
    starts=rng.integers(0,days,(10000,(days+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%days).reshape(10000,-1)[:,:days]
    ns=counts[idx].sum(axis=1);result={}
    for name,v in values.items():
        sums=np.bincount(offsets,weights=v,minlength=days)
        means=sums[idx].sum(axis=1)[ns>0]/ns[ns>0]
        result[name]=np.quantile(means,[.025/64,1-.025/64]).tolist()
    return result


def row_for(r,p,prior,month):
    return dict(decision_ts=int(r.decision_ts),target_ts=int(r.target_ts),month=month,
        move=float(r.move) if r.known_path else None,p_up=float(p),prior_up=float(prior),
        adx=float(r.ADX),session=wf.session(int(r.decision_ts)),
        high_gate_side=1 if int(p*100)>75 else -1 if int(p*100)<25 else 0)


def main():
    raw,hashes,duplicates=wf.load();by_ts={int(r['ts']):r for r in raw.to_dict('records')}
    data=wf.dataset(wf.m15(raw),by_ts)
    originals={n:hashlib.sha256((wf.ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'ALL_FORECASTS_PROTOCOL.md').read_bytes()).hexdigest(),
        hashes=hashes,duplicates=duplicates,original_hashes=originals,variants={},no_trading_changes=True)
    for variant,names,old_file in [('raw',wf.NAMES,'result.json'),('normalized',wf.NORMALIZED_NAMES,'result_normalized.json')]:
        old=json.loads((HERE/old_file).read_text('utf-8'));before=hashlib.sha256((HERE/old_file).read_bytes()).hexdigest()
        forecasts=[];folds=[]
        for month in pd.date_range('2025-01-01','2026-10-01',freq='MS',tz='UTC'):
            begin=int(month.timestamp());end=min(wf.END,int((month+pd.offsets.MonthBegin()).timestamp()))
            train=data.loc[wf.train_mask(data,begin)];test=data.loc[data.decision_ts.ge(begin)&data.decision_ts.lt(end)]
            prior=float(train.move.gt(0).mean());scaler=wf.StandardScaler().fit(train[names])
            model=wf.lgb.LGBMClassifier(n_estimators=100,num_leaves=31,learning_rate=.1,min_child_samples=20,
                random_state=42,n_jobs=2,deterministic=True,force_col_wise=True,verbosity=-1)
            model.fit(scaler.transform(train[names]),train.move.gt(0).astype(int))
            if not np.array_equal(model.classes_,[0,1]):raise ValueError('Class contract')
            probabilities=model.predict_proba(scaler.transform(test[names]))[:,1] if len(test) else []
            current=[row_for(r,p,prior,month.strftime('%Y-%m')) for (_,r),p in zip(test.iterrows(),probabilities)]
            fold=dict(month=month.strftime('%Y-%m'),train=len(train),max_train_target=int(train.target_ts.max()),
                test_begin=begin,prior_up=prior,**diagnostics(current))
            if fold['max_train_target']>=begin:raise ValueError('Target leakage')
            forecasts.extend(current);folds.append(fold)
            print(json.dumps(dict(variant=variant,month=fold['month'],forecasts=len(current))),flush=True)
        actual={r['decision_ts']:r['p_up'] for r in forecasts if r['high_gate_side']}
        expected={r['decision_ts']:r['p_up'] for r in old['observations'] if r['scenario']=='base'}
        if actual.keys()!=expected.keys() or any(abs(actual[t]-expected[t])>1e-12 for t in actual):raise ValueError('Refit mismatch')
        if [r['train'] for r in folds]!=[r['train'] for r in old['folds']]:raise ValueError('Training cohort changed')
        years=[]
        for year in (2025,2026):
            rows=[r for r in forecasts if r['month'].startswith(str(year))]
            result=dict(year=year,**diagnostics(rows),paired_adjusted_ci=interval(rows,year),
                high_gate_kept=sum(bool(r['high_gate_side']) for r in rows),
                adx_groups={label:diagnostics([r for r in rows if (r['adx']>=20)==condition]) for label,condition in [('lt20',False),('ge20',True)]},
                sessions={s:diagnostics([r for r in rows if r['session']==s]) for s in ('london','new_york','overlap','asia_or_offhours')})
            years.append(result)
            print(json.dumps(dict(variant=variant,**{k:v for k,v in result.items() if k not in ('sessions','adx_groups','calibration_bins')})),flush=True)
        positive=all(y['nonflat']>=1000 and y['auc'] is not None and y['auc']>.5 and
            all(v is not None and v[0]>0 for v in y['paired_adjusted_ci'].values()) for y in years)
        report['variants'][variant]=dict(forecasts=forecasts,folds=folds,years=years,
            positive_information_evidence=positive,reproduced_selected=len(actual))
        if hashlib.sha256((HERE/old_file).read_bytes()).hexdigest()!=before:raise ValueError('Old outcome file changed')
    for name,digest in originals.items():
        if hashlib.sha256((wf.ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Original artifact changed')
    (HERE/'all_forecasts_result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v['positive_information_evidence'] for k,v in report['variants'].items()}),flush=True)


if __name__=='__main__':main()
