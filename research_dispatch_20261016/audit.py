"""Independent Decimal exit/control/cash audit of both agent reports."""
from decimal import Decimal as D, ROUND_FLOOR
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dispatch_cache_loader',ROOT/'research_walkforward_20261015/run.py')
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)


def outcome(bars,entry_ts,horizon,side,distance,cost):
    first=bars.get(entry_ts)
    if first is None:return None
    entry=D(str(first['Open']));side=D(side)
    stop=entry-side*distance;target=entry+side*2*distance
    for ts in range(entry_ts,entry_ts+horizon,300):
        bar=bars.get(ts)
        if bar is None:return None
        op,high,low=[D(str(bar[k])) for k in ('Open','High','Low')]
        if side*(op-stop)<=0:price,reason=op,'gap_stop'
        elif low<=stop if side==1 else high>=stop:price,reason=stop,'stop'
        elif high>=target if side==1 else low<=target:price,reason=target,'target'
        else:continue
        return price,reason,ts+300,(side*(price-entry)-cost)/(distance+cost)
    price=D(str(bar['Close']))
    return price,'deadline',entry_ts+horizon,(side*(price-entry)-cost)/(distance+cost)


def cash(rows,volume,cost,projection):
    balance=D(1000);taken=skipped=0
    for row in sorted(rows,key=lambda r:r['entry_ts']):
        if row['status']!='closed':raise ValueError('Cannot validate full account with unknown trades')
        if balance<=0:break
        # Production-free sizing uses float cash as its interface. Preserve that
        # boundary while independently reconstructing the formula and rounding.
        budget_cash=D(str(float(balance)))
        entry=D(str(row['entry']));distance=D(str(row['stop_distance']))
        minimum,step,maximum=[D(str(volume[k])) for k in ('minVolume','stepVolume','maxVolume')]
        raw=min(budget_cash*D('.005')/(distance+cost),budget_cash*5/entry,maximum)
        units=(raw/step).to_integral_value(rounding=ROUND_FLOOR)*step
        if units<minimum:skipped+=1;continue
        pnl=units*(D(row['side'])*(D(str(row['exit']))-entry)-cost)
        balance+=pnl;trade=projection['trades'][taken];taken+=1
        assert trade['entry_ts']==row['entry_ts']
        assert abs(units-D(str(trade['units'])))<D('1e-8')
        assert abs(pnl-D(str(trade['pnl'])))<D('1e-8')
        assert abs(balance-D(str(trade['balance'])))<D('1e-8')
    assert taken==projection['taken'] and skipped==projection['minimum_size_skips']
    assert abs(balance-D(str(projection['end_usd'])))<D('1e-8')
    return taken


def main():
    reports={name:json.loads((ROOT/name/'result.json').read_text('utf-8')) for name in
             ('research_fix_20261016','research_alternative_20261016')}
    output={name:dict(exits=0,control_exits=0,funded_trades=0,max_R_error=0) for name in reports}
    for symbol in ('EURUSD','GBPUSD'):
        raw,hashes,_=loader.load(symbol)
        bars={int(b['ts']):b for b in raw.to_dict('records')}
        for name,report in reports.items():
            pair=report.get('arms',report.get('pairs'))[symbol]
            assert hashes==pair['input_hashes']
            horizon=3600 if name=='research_fix_20261016' else 14400
            controls=('buy','sell','momentum') if horizon==3600 else ('buy','sell','opposite')
            for scenario,cost in [('base',D('.0002')),('stress',D('.0004'))]:
                data=pair['scenarios'][scenario];previous=-1
                for row in data['rows']:
                    assert row['entry_ts']==row['decision_ts']+300
                    assert row['entry_ts']>=previous
                    if row['status']!='closed':
                        assert row is data['rows'][-1], 'Research must stop after an unknown outcome'
                        assert outcome(bars,row['entry_ts'],horizon,row['side'],D(str(row['stop_distance'])).quantize(D('1e-12')),cost) is None
                        continue
                    distance=D(str(row['stop_distance']))
                    price,reason,exit_ts,net=outcome(bars,row['entry_ts'],horizon,row['side'],distance,cost)
                    assert reason==row['reason'] and exit_ts==row['exit_ts']
                    assert abs(price-D(str(row['exit'])))<D('1e-12')
                    error=abs(float(net)-row['net_R']);assert error<1e-10
                    output[name]['max_R_error']=max(output[name]['max_R_error'],error)
                    output[name]['exits']+=1;previous=exit_ts
                    for control in controls:
                        side=1 if control=='buy' else -1 if control=='sell' else row['momentum'] if control=='momentum' else -row['side']
                        result=outcome(bars,row['entry_ts'],horizon,side,distance,cost)
                        if result is None:assert row['excess_'+control] is None
                        else:
                            assert abs(float(net-result[-1])-row['excess_'+control])<1e-10
                            output[name]['control_exits']+=1
                projected=[r for r in data['rows'] if r['month']>='2025-01']
                if all(r['status']=='closed' for r in projected):
                    output[name]['funded_trades']+=cash(projected,pair['volume'],cost,data['projection'])
                else:
                    assert data['projection']['status']=='unknown_paths'
                    assert data['projection']['not_full_period_balance'] is True
                    output[name]['funded_trades']+=cash([r for r in projected if r['status']=='closed'],
                        pair['volume'],cost,data['projection']['known_prefix'])
                for summary in data['summaries']:
                    rows=[r for r in data['rows'] if r['month'].startswith(str(summary['year']))]
                    known=[r for r in rows if r['status']=='closed']
                    assert summary['closed']==len(known) and summary['unknown']==len(rows)-len(known)
                    assert abs(summary['sum_R']-sum(r['net_R'] for r in known))<1e-8
    for name,report in reports.items():
        assert hashlib.sha256((ROOT/name/'PROTOCOL.md').read_bytes()).hexdigest()==report['protocol_sha256']
        for filename,digest in report['original_hashes'].items():
            assert filename in ('lgbm_model.pkl','lgbm_scaler.pkl')
            assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==digest
    (ROOT/'research_dispatch_20261016/audit_result.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output))


if __name__=='__main__':main()
