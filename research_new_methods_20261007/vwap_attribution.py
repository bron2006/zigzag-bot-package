"""Fixed offline methodology comparison, never imports bot/config/DB."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from replay_vwap import bands, replay, statistics
from validate_broker_probe import decode_bar

FOLDER=Path(__file__).parent

def hindsight(rows,index,entry,stop,fee):
    risk=entry-stop
    for row in rows[index+1:]:
        if row['Low']<=stop:
            return dict(status='filled',outcome='STOP',r=(-risk-fee)/risk)
        if row['Low']<=row['vwap']<=row['High']:
            return dict(status='filled',outcome='VWAP',r=(row['vwap']-entry-fee)/risk)
    return dict(status='filled',outcome='SESSION_END',r=(rows[-1]['Close']-entry-fee)/risk)

def event_index(rows,eligible_only):
    for i,row in enumerate(rows):
        if i<12 or not np.isfinite(row['lower']) or row['Low']>row['lower']:
            continue
        if eligible_only:
            if datetime.fromtimestamp(row['ts']+300,tz=timezone.utc).hour<12:
                continue
            return i
        return i if len(rows)-1-i<=48 else None
    return None

def main():
    records=[]
    manifest={}
    sessions_count=0
    symbols=json.loads((FOLDER/'vwap_intentions_inventory.json').read_text(encoding='utf-8'))['summary']['symbols']
    for symbol in sorted(symbols):
        path=FOLDER/'vwap_replay_m5'/f'{symbol}.json'
        manifest[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        data=json.loads(path.read_text(encoding='utf-8'))
        rows=[]
        for raw in data['raw_trendbars']:
            row=decode_bar(raw)
            row.update(ts=row['start_minute']*60,volume=int(raw['volume']))
            rows.append(row)
        rows.sort(key=lambda r:r['ts'])
        previous=None
        tr=[]
        grouped=defaultdict(list)
        for row in rows:
            value=row['High']-row['Low']
            if previous is not None:
                value=max(value,abs(row['High']-previous),abs(row['Low']-previous))
            tr.append(value)
            previous=row['Close']
            row['atr']=float(np.mean(tr[-14:])) if len(tr)>=14 else float('nan')
            dt=datetime.fromtimestamp(row['ts'],tz=timezone.utc)
            if dt.weekday()<5 and 8<=dt.hour<16:
                grouped[dt.date().isoformat()].append(row)
        for day,session in grouped.items():
            start=int(datetime.fromisoformat(day+'T08:00:00+00:00').timestamp())
            if [r['ts'] for r in session]!=list(range(start,start+8*3600,300)):
                continue
            sessions_count+=1
            vwap,upper,lower=bands(np.array([r['Close'] for r in session]),np.array([r['volume'] for r in session]))
            for row,v,l in zip(session,vwap,lower):
                row.update(vwap=float(v),lower=float(l))
            for eligible in (False,True):
                i=event_index(session,eligible)
                if i is None or i>=len(session)-1:
                    continue
                row=session[i]
                atr=row['atr']
                if not np.isfinite(atr) or row['vwap']<=row['lower']:
                    continue
                spread,fee=.20*atr,.02*atr
                low_entry=row['Low']+spread
                low_stop=low_entry-(row['vwap']-row['Low'])
                band_entry=row['lower']
                band_stop=band_entry-(row['vwap']-row['lower'])
                variants=['first_eligible_band'] if eligible else ['hindsight_low','prospective_low','prospective_band']
                for variant in variants:
                    if variant=='hindsight_low':
                        result=hindsight(session,i,low_entry,low_stop,fee)
                    else:
                        entry,stop=(low_entry,low_stop) if variant=='prospective_low' else (band_entry,band_stop)
                        result=replay(dict(limit=entry,stop=stop,timestamp=row['ts']+300),session,spread,fee)
                    records.append(dict(symbol=path.stem,day=day,variant=variant,event_start_ts=row['ts'],
                        event_known_ts=row['ts']+300,**result))
    summary={}
    for name in ('hindsight_low','prospective_low','prospective_band','first_eligible_band'):
        chosen=[r for r in records if r['variant']==name]
        summary[name]={label:statistics([r for r in chosen if label=='all' or
            (r['day']<'2026-09-14')==(label=='early')]) for label in ('all','early','late')}
        summary[name]['candidate_count']=len(chosen)
    output=dict(summary=summary,records=records,full_pair_day_sessions=sessions_count,
        history_sha256=manifest,protocol_sha256=hashlib.sha256((FOLDER/'VWAP_ATTRIBUTION_PROTOCOL.md').read_bytes()).hexdigest())
    (FOLDER/'vwap_attribution_results.json').write_text(json.dumps(output,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(summary=summary,full_pair_day_sessions=sessions_count),indent=2))

if __name__=='__main__':
    main()
