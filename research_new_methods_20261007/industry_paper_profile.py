"""One documented-paper source profile, not optimization or executable PNL."""
import hashlib
import json
import numpy as np
import pandas as pd
from external_reference import ROOT,CACHE,load,calculate,describe


def paper_weights(returns):
    price=(1+returns.fillna(0)).cumprod();change=price.diff().abs()
    upper=np.minimum(price.rolling(20).max(),price.ewm(span=20,adjust=False).mean()+2.8*change.rolling(20,min_periods=19).mean())
    lower=np.maximum(price.rolling(40).min(),price.ewm(span=40,adjust=False).mean()-2.8*change.rolling(40,min_periods=39).mean())
    vol=returns.rolling(14).std(ddof=0)
    p,u,l,v,r=[f.to_numpy() for f in (price,upper,lower,vol,returns)]
    state=np.zeros(r.shape[1],dtype=bool);trail=np.full(r.shape[1],np.nan);out=np.zeros_like(r)
    for t in range(1,len(r)):
        good=np.isfinite(r[t])&np.isfinite(u[t])&np.isfinite(l[t])&np.isfinite(v[t])&(v[t]>0)
        opened=~state&good&(p[t]>=u[t-1])&(u[t-1]>l[t-1])
        continued=state&good&(p[t]>np.maximum(trail,l[t]))
        next_trail=np.full_like(trail,np.nan)
        next_trail[opened]=l[t,opened];next_trail[continued]=np.maximum(trail[continued],l[t,continued])
        state=opened|continued;trail=next_trail
        available=np.isfinite(r[t]).sum()
        if not available:raise ValueError('No observed industries')
        w=np.zeros(r.shape[1]);w[state]=.015/v[t,state]/available
        if w.sum()>2:w*=2/w.sum()
        out[t]=w
    return pd.DataFrame(out,index=returns.index,columns=returns.columns)


def main():
    r,f=load();w=paper_weights(r);out=calculate(r,f,w)
    report={'reference':describe(out.loc[:'2024-03-31']),
        'contemporary_not_blind':describe(out.loc['2024-04-01':]),'orders':0,'production_allowed':False,
        'exact_paper_replication':False,'std_divisor_unresolved':True,'costs_actual_fills_unknown':True,
        'signatures':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('PAPER_PROFILE_PROTOCOL.md','industry_paper_profile.py','external_reference.py')},
        'cache_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (CACHE/'industry.gz',CACHE/'factor.gz')}}
    (ROOT/'industry_paper_profile_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
