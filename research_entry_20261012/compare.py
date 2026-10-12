"""Offline fixed entry comparison. Never imports bot/config/db or sends orders."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import warnings

import joblib
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'research_new_methods_20261007'))
from entry_rules import POLICIES, choose_entry, settle
from model_contract_probe import feature_function, load_bars


def describe(results):
    counts=Counter(r['status'] for r in results)
    pnl=sum(r.get('unit_pnl',0) for r in results)
    decided=counts['win']+counts['loss']
    unknown=counts['unknown']+counts['unresolved']
    return dict(intents=len(results),counts=dict(counts),
                accuracy=counts['win']/decided if decided else None,
                conditional_flat_10_balance=1000+10*pnl,
                unit_pnl=pnl,unit_pnl_bounds=[pnl-unknown,pnl+.8*unknown],
                mean_per_intent=pnl/len(results) if results else None,
                missing=unknown)


def main():
    model=joblib.load(ROOT/'lgbm_model.pkl')
    scaler=joblib.load(ROOT/'lgbm_scaler.pkl')
    features=feature_function()
    report=dict(retrospective=True,production_activated=False,proven_edge=False,
                full_live_strategy=False,executable=False,
                protocol_sha256=hashlib.sha256(Path(__file__).with_name('PROTOCOL.md').read_bytes()).hexdigest(),
                model_sha256=hashlib.sha256((ROOT/'lgbm_model.pkl').read_bytes()).hexdigest(),
                arms=[])
    for symbol in ('EURUSD','GBPCHF','AUDJPY'):
        frame=load_bars(symbol)
        records=frame.to_dict('records')
        matrix,indices,atrs=[],[],[]
        for i in range(299,len(frame)):
            window=frame.iloc[i-299:i+1]
            if not np.all(np.diff(window.ts.to_numpy())==300):
                continue
            feature=features(window)
            if feature is None: raise ValueError('feature_failure')
            previous=window.Close.shift(1)
            tr=pd.concat([window.High-window.Low,(window.High-previous).abs(),
                          (window.Low-previous).abs()],axis=1).max(axis=1)
            atr=float(tr.tail(14).mean())
            if not np.isfinite(atr) or atr<=0: raise ValueError('atr_failure')
            matrix.append(feature.iloc[0].to_numpy())
            indices.append(i)
            atrs.append(atr)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',FutureWarning)
            probabilities=model.predict_proba(scaler.transform(pd.DataFrame(matrix,
                                              columns=['ATR','ADX','RSI','EMA50','EMA200'])))[:,list(model.classes_).index(1)]
        arms={p:[] for p in POLICIES}
        months={p:defaultdict(list) for p in POLICIES}
        last=-float('inf')
        for i,atr,prob in zip(indices,atrs,probabilities):
            score=int(prob*100)
            direction=-1 if score>75 else 1 if score<25 else 0
            ts=int(records[i]['ts'])+300
            if not direction or ts-last<1800: continue
            last=ts  # Common intents independent of arm outcomes/future availability.
            month=datetime.fromtimestamp(ts,timezone.utc).strftime('%Y-%m')
            for policy in POLICIES:
                result=settle(records,choose_entry(records,i,direction,atr,policy),direction)
                arms[policy].append(result)
                months[policy][month].append(result)
        for policy in POLICIES:
            row=dict(symbol=symbol,policy=policy,**describe(arms[policy]),
                     months={m:describe(r) for m,r in sorted(months[policy].items())})
            report['arms'].append(row)
            print(json.dumps(row),flush=True)
    Path(__file__).with_name('result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__': main()
