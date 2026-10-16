"""Decimal replay and chronology/artifact checks, independent stop arithmetic."""
from decimal import Decimal as D
import hashlib
import json
import run as wf


def main():
    raw,_,_=wf.load();by_ts={int(r['ts']):r for r in raw.to_dict('records')}
    data=wf.dataset(wf.m15(raw),by_ts);feature={int(r.decision_ts):r for _,r in data.iterrows()}
    summaries=[]
    for name in ('result.json','result_normalized.json'):
        p=json.loads((wf.HERE/name).read_text('utf-8'));n=0;max_error=0
        assert len(p['folds'])==22
        assert all(f['train_max_target']<f['test_begin'] for f in p['folds'])
        assert all(hashlib.sha256((wf.ROOT/k).read_bytes()).hexdigest()==v for k,v in p['original_hashes'].items())
        for r in p['observations']:
            if r['status']!='closed':continue
            t=r['decision_ts']+300;path=[by_ts[t+j*300] for j in range(3)]
            side=D(r['side']);entry=D(str(path[0]['Open']));distance=D(str(1.5*float(feature[r['decision_ts']].ATR)))
            cost=D('.0002') if r['scenario']=='base' else D('.0004')
            stop=entry-side*distance;target=entry+side*2*distance;exit_=D(str(path[-1]['Close']))
            for b in path:
                o,h,l=[D(str(b[k])) for k in ('Open','High','Low')]
                if side*(o-stop)<=0:exit_=o;break
                if (l<=stop if side==1 else h>=stop):exit_=stop;break
                if (h>=target if side==1 else l<=target):exit_=target;break
            value=float((side*(exit_-entry)-cost)/(distance+cost))
            max_error=max(max_error,abs(value-r['net_R']));n+=1
        assert max_error<1e-10
        summary=dict(file=name,scenario_observations=n,max_error=max_error,fold_purges=22,original_hashes_unchanged=True)
        summaries.append(summary);print(json.dumps(summary))
    (wf.HERE/'audit.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')


if __name__=='__main__':main()
