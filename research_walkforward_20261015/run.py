"""Monthly five-feature LightGBM research; no application/config/DB imports."""
from collections import Counter
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import lightgbm as lgb
import numpy as np
import pandas as pd
import pandas_ta
from sklearn.preprocessing import StandardScaler

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
NAMES=['ATR','ADX','RSI','EMA50','EMA200']
NORMALIZED_NAMES=['ATR_REL','ADX','RSI','EMA50_DIST','EMA200_DIST']
START=1704067200;END=1791417600


def load(symbol='EURUSD'):
    if symbol not in ('EURUSD','GBPUSD'):
        raise ValueError('Only verified USD-quoted research pairs supported')
    folder=ROOT/'research_new_methods_20261007'/'comparative_m5'
    manifest=json.loads((folder/(symbol+'_complete.json')).read_text('utf-8'))
    if not manifest['complete']:raise ValueError('Incomplete history')
    unique={};hashes={};duplicates=0
    for name in manifest['pages']:
        path=folder/name;hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path,'rt',encoding='utf-8') as stream:raw=json.load(stream)
        for r in raw['raw_trendbars']:
            ts=int(r['utcTimestampInMinutes'])*60
            if not START<=ts<END:continue
            low=int(r['low']);b=dict(ts=ts,Low=low/1e5,Open=(low+int(r['deltaOpen']))/1e5,
                High=(low+int(r['deltaHigh']))/1e5,Close=(low+int(r['deltaClose']))/1e5)
            o,h,l,c=[b[k] for k in ('Open','High','Low','Close')]
            if not np.isfinite([o,h,l,c]).all() or not 0<l<=min(o,c)<=max(o,c)<=h:raise ValueError('Invalid OHLC')
            if ts in unique:
                if b!=unique[ts]:raise ValueError('Conflicting duplicate')
                duplicates+=1
            unique[ts]=b
    return pd.DataFrame([unique[t] for t in sorted(unique)]),hashes,duplicates


def m15(bars):
    rows=[]
    for bucket,g in bars.groupby(bars.ts//900):
        start=int(bucket)*900
        if g.ts.tolist()==[start,start+300,start+600]:
            rows.append(dict(ts=start,Open=g.Open.iloc[0],High=g.High.max(),Low=g.Low.min(),Close=g.Close.iloc[-1]))
    return pd.DataFrame(rows)


def features(bars):
    parts=[]
    for _,g in bars.groupby(bars.ts.diff().ne(900).cumsum()):
        out=pd.DataFrame(np.nan,index=g.index,columns=NAMES)
        if len(g)>=200:
            out['ATR']=pandas_ta.atr(high=g.High,low=g.Low,close=g.Close,length=14)
            out['ADX']=pandas_ta.adx(high=g.High,low=g.Low,close=g.Close,length=14)['ADX_14']
            out['RSI']=pandas_ta.rsi(g.Close,length=14)
            out['EMA50']=pandas_ta.ema(g.Close,length=50)
            out['EMA200']=pandas_ta.ema(g.Close,length=200)
            out.iloc[:199]=np.nan
        parts.append(out)
    return pd.concat(parts).sort_index()


def dataset(bars,by_ts):
    x=features(bars);x['decision_ts']=bars.ts+900;x['entry_ts']=x.decision_ts+300;x['target_ts']=x.entry_ts+900
    x['ATR_REL']=x.ATR/bars.Close
    x['EMA50_DIST']=(bars.Close-x.EMA50)/x.ATR
    x['EMA200_DIST']=(bars.Close-x.EMA200)/x.ATR
    moves=[];known=[]
    for t in x.entry_ts:
        path=[by_ts.get(int(t)+j*300) for j in range(3)]
        valid=all(b is not None for b in path);known.append(valid)
        moves.append(path[-1]['Close']-path[0]['Open'] if valid else np.nan)
    x['move']=moves;x['known_path']=known;x['momentum']=np.sign(bars.Close-bars.Open)
    return x.loc[np.isfinite(x[NAMES]).all(axis=1)&x.ATR.gt(0)].copy()


def train_mask(data,boundary):
    return data.known_path&data.move.ne(0)&data.target_ts.lt(boundary)


def simulate(path,side,distance,cost):
    if len(path)!=3 or any(b is None for b in path):return dict(status='unknown')
    if any(b['ts']-a['ts']!=300 for a,b in zip(path,path[1:])):return dict(status='unknown')
    entry=path[0]['Open'];stop=entry-side*distance;target=entry+side*2*distance
    for b in path:
        gap=side*(b['Open']-stop)<=0;hit=b['Low']<=stop if side==1 else b['High']>=stop
        tp=b['High']>=target if side==1 else b['Low']<=target
        if gap or hit or tp:
            exit_=b['Open'] if gap else stop if hit else target
            return dict(status='closed',net_R=(side*(exit_-entry)-cost)/(distance+cost),
                        reason='gap_stop' if gap else 'stop' if hit else 'target',ambiguous=bool(hit and tp))
    return dict(status='closed',net_R=(side*(path[-1]['Close']-entry)-cost)/(distance+cost),reason='deadline',ambiguous=False)


def session(ts):
    dt=datetime.fromtimestamp(ts,timezone.utc)
    london=8<=dt.astimezone(ZoneInfo('Europe/London')).hour<17
    ny=8<=dt.astimezone(ZoneInfo('America/New_York')).hour<17
    return 'overlap' if london and ny else 'london' if london else 'new_york' if ny else 'asia_or_offhours'


def bootstrap(rows,key,year):
    begin=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp());end=min(END,int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()))
    days=(end-begin+86399)//86400;daily=np.zeros(days)
    for r in rows:
        if begin<=r['decision_ts']<end and r['status']=='closed':daily[(r['decision_ts']-begin)//86400]+=r[key]
    rng=np.random.default_rng(20261015);starts=rng.integers(0,days,(10000,(days+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%days).reshape(10000,-1)[:,:days]
    return np.quantile(daily[idx].mean(axis=1),[.025/64,1-.025/64]).tolist()


def summarize(rows):
    known=[r for r in rows if r['status']=='closed'];v=np.array([r['net_R'] for r in known]);nonflat=[r for r in known if r['move']!=0]
    gain=v[v>0].sum();loss=-v[v<0].sum()
    return dict(selected=len(rows),closed=len(known),unknown=len(rows)-len(known),
        direction_correct=sum(r['side']*r['move']>0 for r in nonflat),direction_decided=len(nonflat),
        binary80_proxy_mean=float(np.mean([.8 if r['side']*r['move']>0 else -1 if r['move'] else 0 for r in known])) if known else None,
        sum_R=float(v.sum()),mean_R=float(v.mean()) if len(v) else None,profit_factor=float(gain/loss) if loss else None,
        wins=int((v>0).sum()),ambiguous=sum(r['ambiguous'] for r in known))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--normalized',action='store_true');args=parser.parse_args()
    names=NORMALIZED_NAMES if args.normalized else NAMES
    raw,hashes,duplicates=load();by_ts={int(r['ts']):r for r in raw.to_dict('records')};bars=m15(raw);data=dataset(bars,by_ts)
    original={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),hashes=hashes,
        original_hashes=original,raw_bars=len(raw),m15_bars=len(bars),feature_rows=len(data),duplicates=duplicates,
        preprocessing='causal_segment_not_production_rolling300',folds=[],summaries=[],gates={})
    report['model_features']=names
    if args.normalized:report['amendment_sha256']=hashlib.sha256((HERE/'NORMALIZED_PROTOCOL.md').read_bytes()).hexdigest()
    observations=[]
    for month in pd.date_range('2025-01-01','2026-10-01',freq='MS',tz='UTC'):
        begin=int(month.timestamp());end=min(END,int((month+pd.offsets.MonthBegin()).timestamp()))
        train=data.loc[train_mask(data,begin)];test=data.loc[data.decision_ts.ge(begin)&data.decision_ts.lt(end)].copy()
        if len(train)<1000:raise ValueError('Insufficient training')
        scaler=StandardScaler().fit(train[names])
        model=lgb.LGBMClassifier(n_estimators=100,num_leaves=31,learning_rate=.1,min_child_samples=20,
            random_state=42,n_jobs=2,deterministic=True,force_col_wise=True,verbosity=-1)
        model.fit(scaler.transform(train[names]),train.move.gt(0).astype(int))
        if not np.array_equal(model.classes_,[0,1]):raise ValueError('Class contract')
        p=model.predict_proba(scaler.transform(test[names]))[:,1] if len(test) else np.array([])
        scores=(p*100).astype(int);sides=np.where(scores>75,1,np.where(scores<25,-1,0))
        fold=dict(month=month.strftime('%Y-%m'),train=len(train),train_max_target=int(train.target_ts.max()),
                  test_begin=begin,test_rows=len(test),selected=int((sides!=0).sum()))
        report['folds'].append(fold);print(json.dumps(fold),flush=True)
        for (_,r),side,prob in zip(test.iterrows(),sides,p):
            if not side:continue
            path=[by_ts.get(int(r.entry_ts)+j*300) for j in range(3)]
            for scenario,cost in [('base',.0002),('stress',.0004)]:
                o=simulate(path,int(side),1.5*float(r.ATR),cost)
                row=dict(decision_ts=int(r.decision_ts),month=fold['month'],adx=float(r.ADX),side=int(side),p_up=float(prob),
                         move=float(r.move) if r.known_path else None,scenario=scenario,session=session(int(r.decision_ts)),**o)
                if o['status']=='closed':
                    for name,control in [('buy',1),('sell',-1),('momentum',int(r.momentum) or 1)]:
                        row['excess_'+name]=o['net_R']-simulate(path,control,1.5*float(r.ATR),cost)['net_R']
                observations.append(row)
    report['observations']=observations
    for policy in ('all','adx20'):
        rows=[r for r in observations if policy=='all' or r['adx']>=20]
        for scenario in ('base','stress'):
            rs=[r for r in rows if r['scenario']==scenario]
            for fold in report['folds']:
                report['summaries'].append(dict(policy=policy,scenario=scenario,month=fold['month'],**summarize([r for r in rs if r['month']==fold['month']])))
            checks=[]
            for year in (2025,2026):
                ys=[r for r in rs if r['month'].startswith(str(year))]
                summary=dict(policy=policy,scenario=scenario,year=year,**summarize(ys),daily_R_ci=bootstrap(ys,'net_R',year),
                    control_excess_ci={k:bootstrap(ys,'excess_'+k,year) for k in ('buy','sell','momentum')},
                    sessions={s:summarize([r for r in ys if r['session']==s]) for s in ('london','new_york','overlap','asia_or_offhours')})
                report['summaries'].append(summary);print(json.dumps({k:v for k,v in summary.items() if k!='sessions'}),flush=True)
                if scenario=='stress':checks.append(summary)
            if scenario=='stress':
                late=checks[-1];report['gates'][policy]=bool(all(r['closed']>=100 and r['unknown']==0 and r['sum_R']>0 for r in checks)
                    and late['closed']>=200 and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['control_excess_ci'].values()))
    # Common-day difference includes zero on filtered-out events, not different trade means.
    stress=[r for r in observations if r['scenario']=='stress']
    diff=[dict(r,difference=-r['net_R'] if r['adx']<20 else 0) if r['status']=='closed' else r for r in stress]
    report['adx_daily_difference_ci2026']=bootstrap(diff,'difference',2026)
    report['gates']['adx20']=report['gates']['adx20'] and report['adx_daily_difference_ci2026'][0]>0
    for name,digest in original.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Original artifact changed')
    (HERE/('result_normalized.json' if args.normalized else 'result.json')).write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'],adx_daily_difference_ci2026=report['adx_daily_difference_ci2026'])),flush=True)


if __name__=='__main__':main()
