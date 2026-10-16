"""Independent Decimal path/size/cash audit and gross-cost attribution."""
from decimal import Decimal as D, ROUND_FLOOR, ROUND_HALF_EVEN
from pathlib import Path
import importlib.util
import json
import hashlib

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fix_audit_candidate',HERE/'run.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def exact(value):
    return D(str(value)).quantize(D('.000000000001'),rounding=ROUND_HALF_EVEN)

def replay_exact(bt,entry_ts,side,distance,cost):
    """Independent path replay, not calling production or repaired simulator."""
    first=bt.get(entry_ts)
    if first is None:return dict(status='unknown')
    entry=exact(first['Open']);dist=exact(distance);side=D(side)
    stop=entry-side*dist;target=entry+side*2*dist;exit_=None
    for ts in range(entry_ts,entry_ts+3600,300):
        bar=bt.get(ts)
        if bar is None:return dict(status='unknown')
        op,hi,lo=[exact(bar[k]) for k in ('Open','High','Low')]
        stop_hit=lo<=stop if side==1 else hi>=stop
        target_hit=hi>=target if side==1 else lo<=target
        if side*(op-stop)<=0:exit_=op;reason='gap_stop';break
        if stop_hit:exit_=stop;reason='stop';break
        if target_hit:exit_=target;reason='target';break
    if exit_ is None:exit_=exact(bar['Close']);reason='deadline'
    return dict(status='closed',exit=exit_,entry=entry,distance=dist,reason=reason,
                exit_ts=ts+300,ambiguous=bool(stop_hit and target_hit),
                net_R=(side*(exit_-entry)-cost)/(dist+cost))

def main():
    result=json.loads((HERE/'result.json').read_text('utf-8'));audit={};maximum_error=0;observations=0;controls=0
    assert hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest()==result['protocol_sha256']
    for symbol,arm in result['arms'].items():
        raw,hashes,_=r.h.wf.load(symbol);assert hashes==arm['input_hashes']
        bt={int(b['ts']):b for b in raw.to_dict('records')};audit[symbol]={}
        for scenario,data in arm['scenarios'].items():
            cost=D('.0002') if scenario=='base' else D('.0004')
            balance=D(1000);cashgross=D(0);cashcost=D(0);taken=skips=0;years={};unit={}
            for row in data['rows']:
                if row['status']!='closed':raise ValueError('Unknown outcome cannot become zero')
                side=D(row['side']);entry=exact(bt[row['entry_ts']]['Open']);stop=exact(row['stop'])
                dist=exact(side*(entry-stop))
                outcome=replay_exact(bt,row['entry_ts'],row['side'],dist,cost)
                assert outcome['status']=='closed'
                exit_=outcome['exit'];netR=outcome['net_R']
                assert outcome['reason']==row['reason'] and abs(float(exit_)-row['exit'])<1e-12
                assert outcome['exit_ts']==row['exit_ts'] and outcome['ambiguous']==row['ambiguous']
                assert abs(float(dist)-row['stop_distance'])<1e-12
                for name,control_side in [('buy',1),('sell',-1),('momentum',row['momentum'])]:
                    control=replay_exact(bt,row['entry_ts'],control_side,dist,cost);controls+=1
                    if control['status']=='unknown':assert row['excess_'+name] is None
                    else:
                        error=abs(float(netR-control['net_R'])-row['excess_'+name])
                        maximum_error=max(maximum_error,error);assert error<1e-10
                gross=side*(exit_-entry)
                maximum_error=max(maximum_error,abs(float(netR)-row['net_R']));observations+=1
                year=row['month'][:4];unit.setdefault(year,dict(count=0,gross_R=0.,cost_R=0.,net_R=0.))
                unit[year]['count']+=1;unit[year]['gross_R']+=float(gross/(dist+cost))
                unit[year]['cost_R']+=float(cost/(dist+cost));unit[year]['net_R']+=float(netR)
                if year<'2025':continue
                vol=arm['volume'];minimum=D(str(vol['minVolume']));step=D(str(vol['stepVolume']));maximum=D(str(vol['maxVolume']))
                units=min(balance*D('.005')/(dist+cost),balance*5/entry,maximum)
                units=(units/step).to_integral_value(rounding=ROUND_FLOOR)*step
                yd=years.setdefault(year,dict(taken=0,minimum_size_skips=0,gross_usd=0.,cost_usd=0.))
                if units<minimum:
                    skips+=1;yd['minimum_size_skips']+=1;continue
                grossusd=units*gross;fee=units*cost;balance+=grossusd-fee
                cashgross+=grossusd;cashcost+=fee;taken+=1
                yd['taken']+=1;yd['gross_usd']+=float(grossusd);yd['cost_usd']+=float(fee)
                saved=data['projection']['trades'][taken-1]
                assert abs(saved['units']-float(units))<1e-9
                assert abs(saved['balance']-float(balance))<1e-8
            assert abs(float(balance)-data['projection']['end_usd'])<1e-8
            assert taken==data['projection']['taken'] and skips==data['projection']['minimum_size_skips']
            audit[symbol][scenario]=dict(end_usd=float(balance),taken=taken,minimum_size_skips=skips,
                gross_usd=float(cashgross),cost_usd=float(cashcost),years=years,unit_R=unit)
    for name,digest in result['original_hashes'].items():assert hashlib.sha256((r.ROOT/name).read_bytes()).hexdigest()==digest
    assert maximum_error<1e-10
    out=dict(observations=observations,control_replays=controls,max_R_error=maximum_error,arms=audit)
    (HERE/'audit.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out),flush=True)

if __name__=='__main__':main()
