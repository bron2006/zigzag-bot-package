"""Independent Decimal reconstruction of all alternative-chart exits and cash."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import importlib.util

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('charts_audit_base',HERE/'run.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def main():
    report=json.loads((HERE/'charts_result.json').read_text('utf-8'))
    results={}
    for symbol,asset in report['assets'].items():
        raw,hashes,_=base.wf.load(symbol)
        assert hashes==asset['input_hashes']
        bars={int(r['ts']):r for r in raw.to_dict('records')}
        checked=0;error=0
        for name,arm in asset['arms'].items():
            assert [r['entry_ts'] for r in arm['scenarios']['base']['rows']]==[r['entry_ts'] for r in arm['scenarios']['stress']['rows']]
            for scenario,data in arm['scenarios'].items():
                cost=D('.0002' if scenario=='base' else '.0004')
                previous=-1;lookups={}
                for row in data['rows']:
                    assert row['status']=='closed' and row['entry_ts']>=previous
                    assert row['context_closed_ts']<=row['decision_ts']
                    assert row['entry_ts']==row['decision_ts']+300
                    side=D(row['side']);entry=D(str(bars[row['entry_ts']]['Open']))
                    distance=D(str(row['stop_distance']));stop=entry-side*distance
                    assert abs(stop-D(str(row['stop'])))<D('1e-12')
                    target=entry+side*2*distance;price=reason=None
                    for ts in range(row['entry_ts'],row['entry_ts']+14400,300):
                        b=bars[ts];o,hi,lo=[D(str(b[k])) for k in ('Open','High','Low')]
                        if side*(o-stop)<=0:price,reason=o,'gap_stop'
                        elif lo<=stop if side==1 else hi>=stop:price,reason=stop,'stop'
                        elif hi>=target if side==1 else lo<=target:price,reason=target,'target'
                        if price is not None:break
                    if price is None:price,reason=D(str(b['Close'])),'deadline'
                    assert ts+300==row['exit_ts'] and reason==row['reason']
                    assert abs(price-D(str(row['exit'])))<D('1e-12')
                    net=(side*(price-entry)-cost)/(distance+cost)
                    error=max(error,abs(float(net)-row['net_R']));assert error<1e-10
                    lookups[row['entry_ts']]=(side,entry,price)
                    previous=row['exit_ts'];checked+=1
                balance=D(1000)
                for trade in data['projection']['trades']:
                    side,entry,price=lookups[trade['entry_ts']]
                    pnl=D(str(trade['units']))*(side*(price-entry)-cost)
                    balance+=pnl
                    assert abs(float(pnl)-trade['pnl'])<1e-8
                    assert abs(float(balance)-trade['balance'])<1e-8
                assert abs(float(balance)-data['projection']['end_usd'])<1e-8
        results[symbol]=dict(replayed_scenario_rows=checked,max_R_error=error,cash_matches=True)
    for name,digest in report['original_hashes'].items():
        assert hashlib.sha256((HERE.parent/name).read_bytes()).hexdigest()==digest
    (HERE/'charts_audit.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results))


if __name__=='__main__':main()
