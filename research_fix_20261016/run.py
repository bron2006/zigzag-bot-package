"""Isolated London fixing reversal screen; never execution/config/DB."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import importlib.util
import hashlib
import json
from collections import Counter

HERE=Path(__file__).resolve().parent; ROOT=HERE.parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
h=module('fix_higher',ROOT/'research_walkforward_20261015'/'higher_timeframes.py')
cash=module('fix_cash',ROOT/'research_walkforward_20261015'/'higher_audit.py')
stable=module('fix_stable_price',ROOT/'research_dispatch_20261016'/'price_replay.py')
LONDON=ZoneInfo('Europe/London')

def fixing_timestamp(day):
    return int(datetime.combine(day,time(16),tzinfo=LONDON).timestamp())

def detect(by_ts):
    dates=sorted({datetime.fromtimestamp(t,timezone.utc).astimezone(LONDON).date() for t in by_ts})
    intents=[];skips=Counter()
    for day in dates:
        if day.weekday()>=5:continue
        fix=fixing_timestamp(day)
        bars=[by_ts.get(t) for t in range(fix-3600,fix+300,300)]
        if any(b is None for b in bars):skips['incomplete_signal_window']+=1;continue
        hour=bars[:-1];confirm=bars[-1]
        span=max(b['High'] for b in hour)-min(b['Low'] for b in hour)
        movement=hour[-1]['Close']-hour[0]['Open']
        if span<=0 or abs(movement)<.5*span or not movement:
            skips['no_hour_impulse']+=1;continue
        side=-1 if movement>0 else 1
        if side*(confirm['Close']-confirm['Open'])<=0 or side*(confirm['Close']-hour[-1]['Close'])<=0:
            skips['no_closed_reversal']+=1;continue
        stop=min(b['Low'] for b in bars)-.1*span if side==1 else max(b['High'] for b in bars)+.1*span
        intents.append(dict(decision_ts=fix+300,entry_ts=fix+600,side=side,
            stop=stop,signal_close=confirm['Close'],momentum=-side,month=day.strftime('%Y-%m')))
    return intents,dict(skips)

def replay(intents,by_ts,cost):
    rows=[];skips=Counter()
    for intent in intents:
        first=by_ts.get(intent['entry_ts'])
        if first is None:
            rows.append(dict(**intent,status='unknown',reason='missing_entry'));break
        distance=intent['side']*(first['Open']-intent['stop'])
        if distance<=0:skips['entry_beyond_stop']+=1;continue
        result=stable.simulate(by_ts,intent['entry_ts'],3600,intent['side'],distance,cost)
        row=dict(**intent,**result)
        if result['status']=='closed':
            for name,side in [('buy',1),('sell',-1),('momentum',intent['momentum'])]:
                control=stable.simulate(by_ts,intent['entry_ts'],3600,side,distance,cost)
                row['excess_'+name]=result['net_R']-control['net_R'] if control['status']=='closed' else None
        rows.append(row)
        if result['status']!='closed':break
    return rows,dict(skips)

def main():
    original={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('lgbm_model.pkl','lgbm_scaler.pkl')}
    metadata=json.loads((ROOT/'research_schedule_audit_20261014'/'metadata.json').read_text('utf-8'))
    report=dict(protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),original_hashes=original,
                metadata_fetched_utc=metadata['fetched_utc'],arms={})
    report['numerical_repair_sha256']=hashlib.sha256((HERE/'NUMERICAL_REPAIR.md').read_bytes()).hexdigest()
    report['stable_simulator_sha256']=hashlib.sha256((ROOT/'research_dispatch_20261016'/'price_replay.py').read_bytes()).hexdigest()
    for symbol in ('EURUSD','GBPUSD'):
        raw,hashes,duplicates=h.wf.load(symbol);by_ts={int(r['ts']):r for r in raw.to_dict('records')}
        intents,detect_skips=detect(by_ts)
        spec=next(s for s in metadata['symbols'] if s['name']==symbol)['specification']
        volume={k:float(spec[k])/100 for k in ('minVolume','stepVolume','maxVolume')}
        arm=dict(input_hashes=hashes,duplicates=duplicates,intents=intents,detect_skips=detect_skips,volume=volume,scenarios={})
        checks=[]
        for scenario,cost in [('base',.0002),('stress',.0004)]:
            rows,skips=replay(intents,by_ts,cost);summaries=[]
            for year in (2024,2025,2026):
                yr=[r for r in rows if r['month'].startswith(str(year))]
                complete=[r for r in yr if r['status']=='closed' and all(r.get('excess_'+k) is not None for k in ('buy','sell','momentum'))]
                summary=dict(year=year,**h.summary(yr),control_censored=sum(r['status']=='closed' for r in yr)-len(complete),
                    daily_R_ci=h.wf.bootstrap(yr,'net_R',year),
                    excess_ci={k:h.wf.bootstrap(complete,'excess_'+k,year) for k in ('buy','sell','momentum')})
                summaries.append(summary)
                print(json.dumps(dict(symbol=symbol,scenario=scenario,**summary)),flush=True)
                if scenario=='stress' and year in (2025,2026):checks.append(summary)
            projected=[dict(r,scenario=scenario) for r in rows if r['month']>='2025-01']
            projection=cash.ledger(projected,volume['minVolume'],volume['stepVolume'],volume['maxVolume']) if all(r['status']=='closed' for r in projected) else dict(status='unknown_paths')
            arm['scenarios'][scenario]=dict(rows=rows,skips=skips,summaries=summaries,projection=projection)
            print(json.dumps(dict(symbol=symbol,scenario=scenario,projection={k:v for k,v in projection.items() if k!='trades'})),flush=True)
        years=arm['scenarios']['stress']['projection'].get('year_end_balances',{});late=checks[-1]
        arm['gate']=bool(all(s['closed']>=50 and s['unknown']==0 and not s['control_censored'] and s['sum_R']>0 for s in checks)
            and late['daily_R_ci'][0]>0 and all(v[0]>0 for v in late['excess_ci'].values())
            and years.get('2025',0)>1000 and years.get('2026',0)>years.get('2025',1000))
        report['arms'][symbol]=arm
    report['gate']=all(a['gate'] for a in report['arms'].values())
    for n,digest in original.items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==digest
    (HERE/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(gate=report['gate'])),flush=True)

if __name__=='__main__':main()
