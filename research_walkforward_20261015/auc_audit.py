"""Day-block uncertainty for ranking information, no model fits/trading."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
END=1791417600


def weighted_auc(y,p,weights):
    _,inv=np.unique(p,return_inverse=True)
    positives=np.bincount(inv,weights=weights*y)
    negatives=np.bincount(inv,weights=weights*(1-y))
    den=positives.sum()*negatives.sum()
    if den==0:return None
    return float(np.sum(positives*(np.cumsum(negatives)-.5*negatives))/den)


def estimate(rows,year):
    rows=[r for r in rows if r['month'].startswith(str(year)) and r['move'] is not None and r['move']!=0]
    p=np.array([r['p_up'] for r in rows]);y=np.array([r['move']>0 for r in rows],dtype=float)
    begin=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp())
    end=min(END,int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()));days=(end-begin+86399)//86400
    offsets=np.array([(r['decision_ts']-begin)//86400 for r in rows],dtype=int)
    # Group scores once; each bootstrap uses resampled calendar-day multiplicity.
    _,inv=np.unique(p,return_inverse=True);rng=np.random.default_rng(20261015)
    starts=rng.integers(0,days,(10000,(days+9)//10))
    idx=((starts[:,:,None]+np.arange(10))%days).reshape(10000,-1)[:,:days]
    outcomes=[]
    for draw in idx:
        weights=np.bincount(draw,minlength=days)[offsets]
        pos=np.bincount(inv,weights=weights*y);neg=np.bincount(inv,weights=weights*(1-y))
        den=pos.sum()*neg.sum()
        if den:outcomes.append(float(np.sum(pos*(np.cumsum(neg)-.5*neg))/den))
    return dict(year=year,nonflat=len(rows),auc=weighted_auc(y,p,np.ones(len(y))),
                adjusted_ci=np.quantile(outcomes,[.025/64,1-.025/64]).tolist(),draws=len(outcomes))


def main():
    source=HERE/'all_forecasts_result.json';before=hashlib.sha256(source.read_bytes()).hexdigest()
    raw=json.loads(source.read_text('utf-8'));result={}
    for name,variant in raw['variants'].items():
        result[name]=[estimate(variant['forecasts'],year) for year in (2025,2026)]
        print(json.dumps(dict(variant=name,years=result[name])),flush=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    (HERE/'all_forecasts_auc.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
