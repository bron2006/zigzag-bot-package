"""Decimal replay and conditional USD projection; not the real paper account."""
from decimal import Decimal as D
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('higher_audit_base',HERE/'higher_timeframes.py')
research=importlib.util.module_from_spec(spec);spec.loader.exec_module(research)
wf=research.wf
spec2=importlib.util.spec_from_file_location('pure_cfd_math',wf.ROOT/'paper_cfd.py')
math=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(math)


def ledger(rows,minimum,step,maximum):
    balance=D('1000');peak=balance;dd=D(0);taken=skipped=0;trades=[];years={};last_exit=-1
    for r in sorted(rows,key=lambda r:r['entry_ts']):
        if r['status']!='closed':raise ValueError('Unknown path forbids full cash projection')
        if balance<=0:break
        cost=.0002 if r['scenario']=='base' else .0004
        units=math.size_position(float(balance),r['entry'],r['stop_distance'],cost,
            minimum=minimum,step=step,maximum=maximum,risk_fraction=.005,notional_cap=5)
        year=r['month'][:4]
        if not units:
            skipped+=1;years[year]=float(balance);continue
        if r['entry_ts']<last_exit:raise ValueError('Overlapping ledger positions')
        last_exit=r['exit_ts']
        pnl=D(str(units))*(D(r['side'])*(D(str(r['exit']))-D(str(r['entry'])))-D(str(cost)))
        balance+=pnl;peak=max(peak,balance);dd=max(dd,(peak-balance)/peak);taken+=1
        trades.append(dict(entry_ts=r['entry_ts'],year=year,units=units,pnl=float(pnl),balance=float(balance)))
        years[year]=float(balance)
    return dict(start_usd=1000.,end_usd=float(balance),net_usd=float(balance-D('1000')),
        taken=taken,minimum_size_skips=skipped,closed_balance_drawdown_percent=float(dd*100),
        year_end_balances=years,trades=trades)


def main():
    source=HERE/'higher_result.json';before=hashlib.sha256(source.read_bytes()).hexdigest()
    result=json.loads(source.read_text('utf-8'));raw,hashes,_=wf.load()
    if hashes!=result['input_hashes']:raise ValueError('Input hashes changed')
    bt={int(r['ts']):r for r in raw.to_dict('records')}
    metadata=json.loads((wf.ROOT/'research_schedule_audit_20261014'/'metadata.json').read_text('utf-8'))
    symbol=next(r for r in metadata['symbols'] if r['name']=='EURUSD')['specification']
    volume={key:float(symbol[key])/100 for key in ('minVolume','stepVolume','maxVolume')}
    audit=dict(metadata_fetched_utc=metadata['fetched_utc'],current_volume_assumptions=volume,
               models_unchanged=True,arm_results={},protocol_sha256=hashlib.sha256((HERE/'HIGHER_LEDGER_PROTOCOL.md').read_bytes()).hexdigest())
    for tf,arm in result['arms'].items():
        step=3600 if tf=='H1' else 14400;n=0;maxerror=0
        assert len(arm['folds'])==22 and all(f['train_max_target']<f['test_begin'] for f in arm['folds'])
        for r in arm['observations']:
            if r['status']!='closed':continue
            side=D(r['side']);entry=D(str(bt[r['entry_ts']]['Open']));distance=D(str(r['stop_distance']))
            stop=entry-side*distance;target=entry+side*2*distance
            cost=D('.0002') if r['scenario']=='base' else D('.0004');exit_=None;reason=None
            for ts in range(r['entry_ts'],r['entry_ts']+step,300):
                b=bt.get(ts)
                if b is None:raise ValueError('Replay reaches missing path before recorded exit')
                o,h,l=[D(str(b[k])) for k in ('Open','High','Low')]
                if side*(o-stop)<=0:exit_=o;reason='gap_stop';break
                if (l<=stop if side==1 else h>=stop):exit_=stop;reason='stop';break
                if (h>=target if side==1 else l<=target):exit_=target;reason='target';break
            if exit_ is None:exit_=D(str(b['Close']));reason='deadline'
            value=float((side*(exit_-entry)-cost)/(distance+cost))
            maxerror=max(maxerror,abs(value-r['net_R']));n+=1
            if reason!=r['reason'] or abs(float(exit_)-r['exit'])>1e-12:raise ValueError('Exit replay mismatch')
        if maxerror>1e-10:raise ValueError('NetR replay mismatch')
        projections={}
        for scenario in ('base','stress'):
            rows=[r for r in arm['observations'] if r['scenario']==scenario]
            projections[scenario]=ledger(rows,volume['minVolume'],volume['stepVolume'],volume['maxVolume'])
        audit['arm_results'][tf]=dict(scenario_observations=n,max_R_error=maxerror,fold_purges=22,projections=projections)
        print(json.dumps(dict(tf=tf,replayed=n,max_R_error=maxerror,
            projections={k:{a:b for a,b in v.items() if a!='trades'} for k,v in projections.items()})),flush=True)
    for name,digest in result['original_hashes'].items():
        if hashlib.sha256((wf.ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Original artifact changed')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    (HERE/'higher_audit.json').write_text(json.dumps(audit,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':main()
