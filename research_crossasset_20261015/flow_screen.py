"""Executed taker volume predictive study; no orders or execution simulator."""
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('crossasset_bootstrap',HERE/'screen.py')
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
ci=bootstrap.ci
START,END,SPLIT=1767225600,1791417600,1782864000


def load(asset):
    folder=HERE.parent/'research_ma1020_20261013'/'cache'
    manifest=json.loads((folder/f'{asset}USDT_complete.json').read_text('utf-8'))
    if not manifest['complete']:raise ValueError('Incomplete input')
    rows=[];hashes={}
    for page in manifest['pages']:
        path=folder/page['file'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=page['sha256']:raise ValueError('Input changed')
        hashes[path.name]=digest
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for r in json.load(stream):
                ts=int(r[0])//1000
                if START<=ts<END:
                    o,h,l,c,v,buy=map(float,[*r[1:6],r[9]])
                    if not np.isfinite([o,h,l,c,v,buy]).all() or not 0<l<=min(o,c)<=max(o,c)<=h or not 0<=buy<=v:
                        raise ValueError('Invalid OHLC/taker volume')
                    rows.append(dict(ts=ts,Open=o,Close=c,Volume=v,Buy=buy))
    rows.sort(key=lambda r:r['ts'])
    if [r['ts'] for r in rows]!=list(range(START,END,900)):raise ValueError('Missing/duplicate M15')
    return rows,hashes


def signals(bars):
    out=[];blocked=0
    for i in range(20,len(bars)):
        if i+2<blocked:continue
        b=bars[i];baseline=sum(r['Volume'] for r in bars[i-20:i])/20
        imbalance=2*b['Buy']/b['Volume']-1 if b['Volume'] else 0
        if baseline>0 and b['Volume']>=2*baseline and abs(imbalance)>=.30:
            out.append(dict(ts=b['ts']+1800,entry_index=i+2,exit_index=i+6,side=1 if imbalance>0 else -1))
            blocked=i+6
    return out


def outcome(intent,bars,side,cost):
    if intent['exit_index']>=len(bars):return dict(status='pending')
    gross=side*(bars[intent['exit_index']]['Open']/bars[intent['entry_index']]['Open']-1)
    return dict(status='closed',net=gross-cost-(.20/(365*24) if cost and side>0 else 0))


def main():
    report=dict(protocol_sha256=hashlib.sha256((HERE/'FLOW_PROTOCOL.md').read_bytes()).hexdigest(),
                phases=[],gates={},hashes={})
    for asset in ('BTC','ETH'):
        bars,hashes=load(asset);report['hashes'][asset]=hashes;intents=signals(bars);checks=[]
        for phase,begin,end in [('early',START,SPLIT),('late',SPLIT,END)]:
            for scenario,cost in [('gross',0),('base',.002),('stress',.003)]:
                rows=[(r,outcome(r,bars,r['side'],cost)) for r in intents if begin<=r['ts']<end]
                closed=[(r,o) for r,o in rows if o['status']=='closed'];v=np.array([o['net'] for r,o in closed])
                days=np.array([(r['ts']-begin)//86400 for r,o in closed],dtype=int);n_days=(end-begin+86399)//86400
                controls={}
                for control in ('opposite','long','short'):
                    delta=np.array([o['net']-outcome(r,bars,-r['side'] if control=='opposite' else 1 if control=='long' else -1,cost)['net'] for r,o in closed])
                    controls[control]=ci(delta,days,n_days)
                summary=dict(asset=asset,phase=phase,scenario=scenario,closed=len(v),
                    statuses=dict(Counter(o['status'] for r,o in rows)),
                    mean_bp=float(v.mean()*10000) if len(v) else None,wins=int((v>0).sum()),
                    adjusted_ci_bp=ci(v,days,n_days),control_improvement_ci_bp=controls)
                report['phases'].append(summary);print(json.dumps(summary),flush=True)
                if scenario=='stress':checks.append(summary)
        late=checks[-1]
        report['gates'][asset]=bool(all(r['mean_bp'] is not None and r['mean_bp']>0 for r in checks)
            and late['closed']>=100 and late['adjusted_ci_bp'][0]>0
            and all(c is not None and c[0]>0 for c in late['control_improvement_ci_bp'].values()))
    (HERE/'flow_result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'])))


if __name__=='__main__':main()
