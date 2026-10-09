"""Three fixed causal rules, chronological lock, no production imports/orders."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from validate_broker_probe import decode_bar
from fetch_comparative_history import CACHE,START,END,SYMBOLS

FOLDER=Path(__file__).parent
RULES=('trend','breakout','reversion')
SPLIT=int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp())


def load_history(symbol):
    manifest=json.loads((CACHE/(symbol+'_complete.json')).read_text(encoding='utf-8'))
    if not manifest['complete'] or manifest['start_ms']!=START or manifest['end_exclusive_ms']!=END:
        raise ValueError('Invalid complete-history manifest')
    unique={};hashes={}
    for name in manifest['pages']:
        path=CACHE/name
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path,'rt',encoding='utf-8') as stream:data=json.load(stream)
        for raw in data['raw_trendbars']:
            row=decode_bar(raw);ts=row.pop('start_minute')*60
            if START<=ts*1000<END:
                row['ts']=ts
                if ts in unique and row!=unique[ts]:raise ValueError('Conflicting duplicate bar')
                unique[ts]=row
    frame=pd.DataFrame([unique[t] for t in sorted(unique)])
    if frame.empty or frame.ts.duplicated().any() or not frame.ts.is_monotonic_increasing:
        raise ValueError('Invalid history')
    return frame,hashes


def indicators(bars):
    groups=bars.ts.diff().ne(300).cumsum()
    frames=[]
    for _,group in bars.groupby(groups):
        out=pd.DataFrame(index=group.index)
        prev=group.Close.shift(1)
        tr=pd.concat([group.High-group.Low,(group.High-prev).abs(),(group.Low-prev).abs()],axis=1).max(axis=1)
        out['atr']=tr.rolling(14,min_periods=14).mean()
        out['fast']=group.Close.ewm(span=10,adjust=False).mean()
        out['slow']=group.Close.ewm(span=50,adjust=False).mean()
        out['upper']=group.High.rolling(20,min_periods=20).max().shift(1)
        out['lower']=group.Low.rolling(20,min_periods=20).min().shift(1)
        out['mean']=group.Close.rolling(20,min_periods=20).mean().shift(1)
        out.iloc[:59]=np.nan
        frames.append(out)
    return pd.concat(frames).sort_index()


def directions(bars,features):
    atr=features.atr
    valid=np.isfinite(features).all(axis=1)&atr.gt(0)
    trend=np.where((features.fast-features.slow>=atr)&(bars.Close>features.fast),1,
            np.where((features.fast-features.slow<=-atr)&(bars.Close<features.fast),-1,0))
    breakout=np.where(bars.Close>features.upper,1,np.where(bars.Close<features.lower,-1,0))
    reversion=np.where(bars.Close-features['mean']>=2*atr,-1,
                np.where(bars.Close-features['mean']<=-2*atr,1,0))
    return {name:np.where(valid,values,0) for name,values in zip(RULES,(trend,breakout,reversion),strict=True)}


def collect(bars,symbol,phase):
    feature=indicators(bars);signals=directions(bars,feature)
    session=(bars.ts%86400>=8*3600)&(bars.ts%86400<16*3600)
    records=[];excluded=Counter();valid_days=[]
    for day,group in bars.loc[session].groupby(bars.ts//86400):
        start=int(day)*86400
        if phase=='early' and start>=SPLIT:continue
        if phase=='final' and start<SPLIT:continue
        date=datetime.fromtimestamp(start,timezone.utc).date().isoformat()
        if group.ts.tolist()!=list(range(start+8*3600,start+16*3600,300)):
            excluded['incomplete_sessions']+=1;continue
        valid_days.append(date)
        for rule in RULES:
            eligible=[int(i) for i in group.index if signals[rule][i]!=0 and bars.ts.iloc[i]<=start+16*3600-900]
            if not eligible:excluded['no_signal_'+rule]+=1;continue
            index=eligible[0]
            if index+2>=len(bars) or bars.ts.iloc[index:index+3].tolist()!=[int(bars.ts.iloc[index])+j*300 for j in range(3)]:
                excluded['missing_entry_exit_'+rule]+=1;continue
            # First eligible is never replaced if its modeled endpoint is missing.
            atr=float(feature.atr.iloc[index]);direction=int(signals[rule][index])
            entry=float(bars.Open.iloc[index+2]);exit_price=float(bars.Close.iloc[index+2])
            pip=.01 if symbol=='USDJPY' else .0001
            base=max(.22*atr,2*pip)/atr;stress=max(.44*atr,4*pip)/atr
            move=(exit_price-entry)/atr
            sign=int(np.sign(exit_price-entry))
            records.append({'day':date,'symbol':symbol,'rule':rule,'direction':direction,
                'signal_ts':int(bars.ts.iloc[index])+300,'entry_ts':int(bars.ts.iloc[index+2]),
                'exit_ts':int(bars.ts.iloc[index+2])+300,'entry':entry,'exit':exit_price,'atr':atr,
                'base_cost_atr':base,'stress_cost_atr':stress,'gross_atr':direction*move,
                'base_net_atr':direction*move-base,'stress_net_atr':direction*move-stress,
                'opposite_stress_atr':-direction*move-stress,
                'always_buy_stress_atr':move-stress,'always_sell_stress_atr':-move-stress,
                'binary80':0. if sign==0 else (.8 if sign*direction>0 else -1.),
                'opposite_binary80':0. if sign==0 else (.8 if sign*direction<0 else -1.),
                'always_buy_binary80':0. if sign==0 else (.8 if sign>0 else -1.),
                'always_sell_binary80':0. if sign==0 else (.8 if sign<0 else -1.),
                'price_sign':sign})
    return records,{'full_session_dates':valid_days,'exclusions':dict(excluded)}


def block_ci(records,key,day_axis,subtract=None):
    if len(day_axis)<10 or not records:return None
    sums=np.zeros(len(day_axis));counts=np.zeros(len(day_axis));lookup={day:i for i,day in enumerate(day_axis)}
    for row in records:
        idx=lookup[row['day']];sums[idx]+=row[key]-(row[subtract] if subtract else 0.);counts[idx]+=1
    rng=np.random.default_rng(20261009);blocks=(len(day_axis)+9)//10
    starts=rng.integers(0,len(day_axis),size=(4000,blocks))
    idx=((starts[:,:,None]+np.arange(10))%len(day_axis)).reshape(4000,-1)[:,:len(day_axis)]
    denominators=counts[idx].sum(axis=1);valid=denominators>0
    samples=sums[idx].sum(axis=1)[valid]/denominators[valid]
    return np.quantile(samples,[.05/6,1-.05/6]).tolist()


def summarize(records,day_axis):
    result={'trades':len(records),'days':len({r['day'] for r in records}),
        'decided':sum(r['price_sign']!=0 for r in records),'ties_assumed_refund':sum(r['price_sign']==0 for r in records),
        'buy':sum(r['direction']==1 for r in records)}
    if not records:return result
    result['winrate_proxy']=sum(r['price_sign']*r['direction']>0 for r in records)/result['decided'] if result['decided'] else None
    for key in ('gross_atr','base_net_atr','stress_net_atr','binary80','opposite_stress_atr','opposite_binary80'):
        result[key]={'mean':float(np.mean([r[key] for r in records])),
                     'adjusted_block_ci':block_ci(records,key,day_axis)}
    result['paired_advantage']={}
    for key,bases in [('stress_net_atr',('always_buy_stress_atr','always_sell_stress_atr')),
                     ('binary80',('always_buy_binary80','always_sell_binary80'))]:
        result['paired_advantage'][key]={base:block_ci(records,key,day_axis,base) for base in bases}
    result['binary_payout_scenarios']={}
    for payout in (.7,.8,.9):
        result['binary_payout_scenarios'][str(payout)]=float(np.mean([
            0. if r['price_sign']==0 else (payout if r['price_sign']*r['direction']>0 else -1.) for r in records]))
    result['per_pair']={s:{'trades':len(part),'stress_mean_atr':float(np.mean([r['stress_net_atr'] for r in part])) if part else None,
        'binary80_mean':float(np.mean([r['binary80'] for r in part])) if part else None}
        for s in SYMBOLS for part in [[r for r in records if r['symbol']==s]]}
    return result


def gate(early,final,key):
    if final['decided']<300 or final['days']<100 or key not in early or key not in final:return False
    interval=final[key]['adjusted_block_ci']
    expected={'always_buy_stress_atr','always_sell_stress_atr'} if key=='stress_net_atr' else {'always_buy_binary80','always_sell_binary80'}
    baselines=final.get('paired_advantage',{}).get(key,{})
    if set(baselines)!=expected or set(final.get('per_pair',{}))!=set(SYMBOLS):return False
    return bool(early[key]['mean']>0 and interval and interval[0]>0
        and all(bounds and bounds[0]>0 for bounds in baselines.values())
        and sum((p['stress_mean_atr'] if key=='stress_net_atr' else p['binary80_mean']) is not None
            and (p['stress_mean_atr'] if key=='stress_net_atr' else p['binary80_mean'])>0
            for p in final['per_pair'].values())>=2)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['early','final'],required=True)
    args=parser.parse_args()
    signatures={name:hashlib.sha256((FOLDER/name).read_bytes()).hexdigest()
                for name in ('COMPARATIVE_PROTOCOL.md','comparative_screen.py')}
    early_path=FOLDER/'comparative_early_v1.json'
    early=None
    if args.phase=='final':
        early=json.loads(early_path.read_text(encoding='utf-8'))
        if early['signatures']!=signatures:raise ValueError('Rule/protocol changed after early phase')
    records=[];coverage={};hashes={}
    for symbol in SYMBOLS:
        bars,source_hashes=load_history(symbol)
        measured,info=collect(bars,symbol,args.phase);records+=measured
        coverage[symbol]={'bars':len(bars),**info};hashes.update(source_hashes)
    if early and early['cache_hashes']!=hashes:raise ValueError('Input history changed after early phase')
    day_axis=sorted({day for info in coverage.values() for day in info['full_session_dates']})
    summaries={rule:summarize([r for r in records if r['rule']==rule],day_axis) for rule in RULES}
    report={'phase':args.phase,'signatures':signatures,'cache_hashes':hashes,'rules':summaries,
        'coverage':coverage,'records':records,'prospective_OOS':False,'actual_execution':False,'orders':0}
    if early:
        report['gates']={rule:{'forex_quote_validation_candidate':gate(early['rules'][rule],summaries[rule],'stress_net_atr'),
                              'binary_venue_validation_candidate':gate(early['rules'][rule],summaries[rule],'binary80')} for rule in RULES}
    path=early_path if args.phase=='early' else FOLDER/'comparative_final_v1.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'phase':args.phase,'rules':summaries,'gates':report.get('gates'),
        'sessions':{s:len(info['full_session_dates']) for s,info in coverage.items()}},indent=2),flush=True)


if __name__=='__main__':main()
