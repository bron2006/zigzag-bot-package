"""Fixed alternative chart scales, same entry family/holding/cost assumptions."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('chart_base',HERE/'run.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
SCALES=(('M30_H2',1800,7200),('H2_H8',7200,28800),('H8_D1',28800,86400))


def main():
    metadata_path=HERE.parent/'research_schedule_audit_20261014'/'metadata.json'
    metadata=json.loads(metadata_path.read_text('utf-8'))
    originals={n:hashlib.sha256((HERE.parent/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    report=dict(protocol_sha256=hashlib.sha256((HERE/'CHART_PROTOCOL.md').read_bytes()).hexdigest(),
                metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                original_hashes=originals,assets={})
    for symbol,source in [('EURUSD','result.json'),('GBPUSD','result_GBPUSD.json')]:
        raw,hashes,_=base.wf.load(symbol)
        by_ts={int(r['ts']):r for r in raw.to_dict('records')}
        terms=next(s for s in metadata['symbols'] if s['name']==symbol)['specification']
        volume={k:float(terms[k])/100 for k in ('minVolume','stepVolume','maxVolume')}
        prepared={}
        for step in (1800,3600,7200,14400,28800,86400):
            prepared[step]=base.prepared(raw,step)
            print(json.dumps(dict(symbol=symbol,prepared_step=step,indicator_bars=len(prepared[step][0]),partial_buckets=prepared[step][1])),flush=True)
        old=json.loads((HERE/source).read_text('utf-8'))
        assert hashes==old['input_hashes']
        assert base.strategy.detect(prepared[3600][0],prepared[14400][0])==old['intents']
        asset=dict(input_hashes=hashes,default_intents_unchanged=True,arms={})
        for name,signal,context in SCALES:
            intents=base.strategy.detect(prepared[signal][0],prepared[context][0],signal_step=signal,context_step=context)
            arm=dict(intents=intents,scenarios={})
            stress_checks=[]
            for scenario,cost in [('base',.0002),('stress',.0004)]:
                rows,skips=base.replay(intents,by_ts,volume,cost)
                summaries=[]
                for year in (2024,2025,2026):
                    subset=[r for r in rows if r['month'].startswith(str(year))]
                    complete=[r for r in subset if r['status']=='closed' and all(r.get('excess_'+k) is not None for k in ('buy','sell','momentum'))]
                    summary=dict(year=year,**base.h.summary(subset),daily_R_ci=base.wf.bootstrap(subset,'net_R',year),
                        control_censored=sum(r['status']=='closed' for r in subset)-len(complete),
                        excess_ci={k:base.wf.bootstrap(complete,'excess_'+k,year) for k in ('buy','sell','momentum')})
                    summaries.append(summary)
                    if scenario=='stress' and year in (2025,2026):stress_checks.append(summary)
                projected=[dict(r,scenario=scenario) for r in rows if r['month']>='2025-01']
                projection=base.ledger.ledger(projected,volume['minVolume'],volume['stepVolume'],volume['maxVolume']) if all(r['status']=='closed' for r in projected) else dict(status='unknown_paths')
                arm['scenarios'][scenario]=dict(rows=rows,skips=skips,summaries=summaries,projection=projection)
                print(json.dumps(dict(symbol=symbol,chart=name,scenario=scenario,raw_intents=len(intents),
                    counts=[s['closed'] for s in summaries],unknown=[s['unknown'] for s in summaries],
                    sums_R=[s['sum_R'] for s in summaries],
                    cash={k:v for k,v in projection.items() if k!='trades'},skips=skips)),flush=True)
            late=stress_checks[-1];cash=arm['scenarios']['stress']['projection'].get('year_end_balances',{})
            arm['gate']=bool(all(s['closed']>=50 and not s['unknown'] and not s['control_censored'] and s['sum_R']>0 for s in stress_checks)
                and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['excess_ci'].values())
                and cash.get('2025',0)>1000 and cash.get('2026',0)>cash.get('2025',1000))
            asset['arms'][name]=arm
            print(json.dumps(dict(symbol=symbol,chart=name,gate=arm['gate'])),flush=True)
        report['assets'][symbol]=asset
    for name,digest in originals.items():assert hashlib.sha256((HERE.parent/name).read_bytes()).hexdigest()==digest
    (HERE/'charts_result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':main()
