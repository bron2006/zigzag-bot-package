"""Independent arithmetic reference; public GET data only, no app/broker imports."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import numpy as np
import pandas as pd

ROOT=Path(__file__).parent
CACHE=ROOT/'external_reference_cache'
URLS={'industry':'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/48_Industry_Portfolios_daily_CSV.zip',
      'factor':'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip'}


def fetch():
    import requests
    CACHE.mkdir(exist_ok=True)
    for name,url in URLS.items():
        path=CACHE/(name+'.gz')
        if path.exists():continue
        response=requests.get(url,timeout=(10,30));response.raise_for_status()
        raw=response.content
        if len(raw)>40_000_000:raise ValueError('Oversized download')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files=[f for f in archive.infolist() if f.filename.lower().endswith('.csv')]
            if len(files)!=1 or files[0].file_size>70_000_000:raise ValueError('Unexpected ZIP payload')
            data=archive.read(files[0]).decode('utf-8-sig')
        with gzip.open(path,'xt',encoding='utf-8') as stream:stream.write(data)
        print(json.dumps({'dataset':name,'received_bytes':len(raw),'source':url}),flush=True)


def parse_block(text,columns):
    # Some upstream CRCRLF exports produce an empty line between every CSV row.
    lines=[line for line in text.splitlines() if line.strip()]
    start=next(i for i,line in enumerate(lines) if re.match(r'^\s*\d{8},',line))
    header=lines[start-1];data=[]
    for line in lines[start:]:
        if not re.match(r'^\s*\d{8},',line):break
        data.append(line)
    frame=pd.read_csv(io.StringIO('\n'.join([header]+data)),index_col=0)
    frame.columns=frame.columns.str.strip()
    if frame.shape[1]!=columns:raise ValueError('Unexpected dataset columns')
    frame.index=pd.to_datetime(frame.index.astype(str),format='%Y%m%d')
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:raise ValueError('Invalid dates')
    frame=frame.astype(float)
    return frame.mask(frame.isin([-99.99,-999.]))/100


def load():
    with gzip.open(CACHE/'industry.gz','rt',encoding='utf-8') as stream:industry=parse_block(stream.read(),48)
    with gzip.open(CACHE/'factor.gz','rt',encoding='utf-8') as stream:factor=parse_block(stream.read(),4)
    industry=industry.loc['1926-07-01':'2026-08-31']
    if not industry.index.isin(factor.index).all():raise ValueError('Missing factor dates')
    factor=factor.reindex(industry.index)
    if factor[['RF','Mkt-RF']].isna().any().any():raise ValueError('Missing market or cash return')
    if (industry.lt(-1)&industry.notna()).any().any():raise ValueError('Impossible industry return')
    return industry,factor


def weights(returns):
    price=(1+returns.fillna(0)).cumprod()
    movement=price.diff().abs()
    upper=np.minimum(price.rolling(20).max(),price.ewm(span=20,adjust=False).mean()+2.8*movement.rolling(20,min_periods=19).mean())
    lower=np.maximum(price.rolling(40).min(),price.ewm(span=40,adjust=False).mean()-2.8*movement.rolling(40,min_periods=39).mean())
    vol=returns.rolling(20).std(ddof=0)
    p=price.to_numpy();u=upper.to_numpy();l=lower.to_numpy();v=vol.to_numpy();r=returns.to_numpy()
    state=np.zeros(returns.shape[1],dtype=bool);trail=np.full(returns.shape[1],np.nan)
    output=np.zeros_like(r)
    for t in range(1,len(returns)):
        valid=np.isfinite(r[t])&np.isfinite(u[t])&np.isfinite(l[t])&np.isfinite(v[t])&(v[t]>0)
        opened=~state&valid&(p[t]>=u[t-1])&(u[t-1]>l[t-1])
        active=state&valid&(p[t]>np.maximum(trail,l[t]))
        next_trail=np.full_like(trail,np.nan)
        next_trail[opened]=l[t,opened]
        next_trail[active]=np.maximum(trail[active],l[t,active])
        state=opened|active;trail=next_trail
        available=np.isfinite(r[t]).sum()
        if not available:raise ValueError('No available industry')
        w=np.zeros_like(trail);w[state]=np.minimum(.20,.02/v[t,state]/available)
        if w.sum()>2:w*=2/w.sum()
        output[t]=w
    return pd.DataFrame(output,index=returns.index,columns=returns.columns)


def calculate(returns,factors,w):
    held=w.shift(1).fillna(0)
    rf=factors.RF
    result=pd.DataFrame(index=returns.index)
    result['strategy']=(held*returns.fillna(0)).sum(axis=1)+(1-held.sum(axis=1))*rf
    result['market']=factors['Mkt-RF']+rf
    result['equal_industries']=returns.mean(axis=1)
    result['exposure']=held.sum(axis=1)
    # End-of-day drift before new allocation, excluding turnover fees.
    drift=held*(1+returns.fillna(0)).div(1+result.strategy,axis=0)
    result['one_side_turnover']=(w-drift).abs().sum(axis=1)
    result['rf']=rf
    if not np.isfinite(result).all().all() or (result.strategy<=-1).any():raise ValueError('Invalid NAV')
    return result


def describe(frame):
    days=len(frame);years=(frame.index[-1]-frame.index[0]).days/365.25
    out={'observed_days':days,'first':str(frame.index[0].date()),'last':str(frame.index[-1].date()),
         'mean_exposure':float(frame.exposure.mean()),'max_exposure':float(frame.exposure.max()),
         'mean_annual_one_side_turnover':float(frame.one_side_turnover.sum()/years)}
    for key in ('strategy','market','equal_industries'):
        r=frame[key];equity=(1+r).cumprod();peak=np.maximum.accumulate(np.r_[1.,equity])
        excess=r-frame.rf
        out[key]={'cagr':float(equity.iloc[-1]**(1/years)-1),
            'annual_volatility':float(r.std(ddof=1)*np.sqrt(252)),
            'sharpe_excess_rf':float(excess.mean()/excess.std(ddof=1)*np.sqrt(252)),
            'max_close_drawdown':float((np.r_[1.,equity]/peak-1).min())}
    return out


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fetch',action='store_true');parser.add_argument('--fetch-worker',action='store_true')
    parser.add_argument('--phase',choices=['reference','contemporary'],default='reference');args=parser.parse_args()
    if args.fetch_worker:fetch();return
    if args.fetch:
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--fetch-worker'],timeout=90,check=True);return
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (CACHE/'industry.gz',CACHE/'factor.gz')}
    signatures={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('EXTERNAL_REFERENCE_PROTOCOL.md','external_reference.py')}
    reference_path=ROOT/'external_reference_result.json'
    if args.phase=='contemporary':
        previous=json.loads(reference_path.read_text())
        if previous['cache_hashes']!=hashes or previous['signatures']!=signatures:raise ValueError('Reference changed')
    industry,factor=load()
    if args.phase=='reference':industry=industry.loc[:'2024-03-31'];factor=factor.reindex(industry.index)
    w=weights(industry);result=calculate(industry,factor,w)
    if args.phase=='contemporary':result=result.loc['2024-04-01':]
    report={'phase':args.phase,'cache_hashes':hashes,'signatures':signatures,'summary':describe(result),
        'missing_industry_cells':int(industry.isna().sum().sum()),'actual_execution':False,'orders':0,
        'tutorial_arithmetic_only':True,'exact_current_paper_replication':False,'production_allowed':False,
        'years':{str(year):describe(group) for year,group in result.groupby(result.index.year) if len(group)>1}}
    path=reference_path if args.phase=='reference' else ROOT/'external_reference_contemporary.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='years'},indent=2))


if __name__=='__main__':main()
