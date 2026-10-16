"""Independent Decimal exit replay, cash and immutable input checks."""
from decimal import Decimal as D, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import run as research

def price(value):
    return D(str(value)).quantize(D('.000000000001'),rounding=ROUND_HALF_EVEN)

def main():
    report=json.loads((research.HERE/'result.json').read_text('utf-8'))
    assert hashlib.sha256((research.HERE/'PROTOCOL.md').read_bytes()).hexdigest()==report['protocol_sha256']
    checks={}
    for symbol,pair in report['pairs'].items():
        raw,hashes,_=research.wf.load(symbol);assert hashes==pair['input_hashes']
        bt={int(b['ts']):b for b in raw.to_dict('records')}
        assert research.fit_directions(bt)==pair['fit']
        count=0;max_error=0
        for scenario,arm in pair['scenarios'].items():
            cost=D('.0002') if scenario=='base' else D('.0004')
            previous_exit=-1
            for r in arm['rows']:
                if r['status']!='closed':continue
                assert r['entry_ts']>=previous_exit and r['entry_ts']==r['decision_ts']+300
                previous_exit=r['exit_ts'];side=D(r['side']);entry=price(bt[r['entry_ts']]['Open'])
                distance=price(r['stop_distance']);stop=entry-side*distance;target=entry+side*2*distance
                value=None
                for ts in range(r['entry_ts'],r['entry_ts']+14400,300):
                    b=bt[ts];o,hi,lo=[price(b[k]) for k in ('Open','High','Low')]
                    if side*(o-stop)<=0:value=o;reason='gap_stop';break
                    if (lo<=stop if side==1 else hi>=stop):value=stop;reason='stop';break
                    if (hi>=target if side==1 else lo<=target):value=target;reason='target';break
                if value is None:value=price(b['Close']);reason='deadline'
                error=abs(float((side*(value-entry)-cost)/(distance+cost))-r['net_R'])
                max_error=max(error,max_error);count+=1
                assert reason==r['reason'] and abs(float(value)-r['exit'])<1e-12 and error<1e-10
            prefix=arm['projection']['known_prefix'];balance=D('1000')
            by_entry={r['entry_ts']:r for r in arm['rows'] if r['status']=='closed'}
            for t in prefix['trades']:
                r=by_entry[t['entry_ts']];units=D(str(t['units']))
                pnl=units*(D(r['side'])*(D(str(r['exit']))-D(str(r['entry'])))-cost)
                balance+=pnl
                assert abs(float(pnl)-t['pnl'])<1e-10 and abs(float(balance)-t['balance'])<1e-9
            assert abs(float(balance)-prefix['end_usd'])<1e-9
        checks[symbol]=dict(replayed=count,max_R_error=max_error,cash_replayed=True,training_recomputed=True)
    for name,digest in report['original_hashes'].items():assert hashlib.sha256((research.ROOT/name).read_bytes()).hexdigest()==digest
    (research.HERE/'audit.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks))

if __name__=='__main__':main()
