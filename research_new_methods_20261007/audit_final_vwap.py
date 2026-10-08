"""Independent accounting and timestamp checks on final replay, no network."""
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path

def main():
    path=Path(__file__).parent/'vwap_tick_results.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data['summary']['all_processed'] and data['offline_recomputed_after_synthetic_tests']
    records=data['records']
    expected=data['summary']['total_orders']
    assert len(records)==expected*2
    mappings={}
    for stress in (1,2):
        chosen=[r for r in records if r['stress']==stress]
        mapping={(r['day'],r['symbol']):r for r in chosen}
        assert len(mapping)==len(chosen)==expected
        mappings[stress]=mapping
        filled=[r for r in chosen if r['status']=='filled']
        summary=data['summary']['scenarios'][str(stress)]['all']
        assert dict(Counter(r['status'] for r in chosen))==summary['statuses']
        assert summary['filled']==len(filled)
        if filled:
            total=math.fsum(r['r'] for r in filled)
            gains=math.fsum(r['r'] for r in filled if r['r']>0)
            losses=-math.fsum(r['r'] for r in filled if r['r']<0)
            assert math.isclose(total,summary['total_r'],abs_tol=1e-10)
            assert math.isclose(total/len(filled),summary['mean_r'],abs_tol=1e-12)
            assert math.isclose(gains/losses,summary['pf'],abs_tol=1e-12)
        for r in filled:
            end=int(datetime.fromisoformat(r['day']+'T16:00:00+00:00').timestamp()*1000)
            assert (r['signal_ts']+1)*1000<=r['fill_ms']<=r['exit_ms']<=end
            assert r['limit']>r['stop'] and math.isfinite(r['r'])
            if r['outcome']=='STOP':
                assert r['r']<0
    for key,base in mappings[1].items():
        stress=mappings[2][key]
        assert base['status']==stress['status']
        if base['status']=='filled':
            assert base['fill_ms']==stress['fill_ms'] and base['exit_ms']==stress['exit_ms']
            assert stress['r']<=base['r']
    assert sum(d['unique_intentions'] for d in data['days'])==expected
    assert sum(d['filled'] for d in data['days'])==data['summary']['scenarios']['1']['all']['filled']
    print('PASS: independent counts, uniqueness, PF, R, timestamps, stress monotonicity and daily reconciliation')

if __name__=='__main__':
    main()
