"""Offline integrity audit of actual XAUUSD M1, NOT strategy/PnL results."""
from collections import defaultdict,Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'research_new_methods_20261007'))
from validate_broker_probe import decode_bar


def load():
    folder=HERE/'cache';manifest=json.loads((folder/'complete.json').read_text(encoding='utf-8'))
    if not manifest['complete'] or not manifest['confirmed_demo'] or manifest['symbol']!='XAUUSD' or manifest['period']!='M1':raise ValueError('Wrong history contract')
    bars={};duplicates=0;outside=0
    for page in manifest['pages']:
        file=folder/page['file']
        if hashlib.sha256(file.read_bytes()).hexdigest()!=page['sha256']:raise ValueError('Immutable history hash mismatch')
        with gzip.open(file,'rt',encoding='utf-8') as stream:data=json.load(stream)
        if data['period']!='M1' or data['start_ms']!=manifest['start_ms']:raise ValueError('Page contract mismatch')
        for raw in data['bars']:
            b=decode_bar(raw);ts=b.pop('start_minute')*60;b['ts']=ts
            if not manifest['start_ms']<=ts*1000<manifest['end_exclusive_ms']:outside+=1;continue
            if ts in bars:
                if bars[ts]!=b:raise ValueError('Conflicting duplicate')
                duplicates+=1
            bars[ts]=b
    ordered=[bars[ts] for ts in sorted(bars)]
    if not ordered:raise ValueError('No bounded history')
    return ordered,dict(pages=len(manifest['pages']),same_duplicates=duplicates,outside_requested_window=outside,
        manifest_sha256=hashlib.sha256((folder/'complete.json').read_bytes()).hexdigest())


def hourly(bars):
    groups=defaultdict(list);result=[];incomplete=0
    for b in bars:groups[b['ts']//3600].append(b)
    for h,g in sorted(groups.items()):
        start=h*3600
        if [b['ts'] for b in g]!=list(range(start,start+3600,60)):
            incomplete+=1;continue
        result.append(dict(ts=start,Open=g[0]['Open'],Close=g[-1]['Close'],High=max(b['High'] for b in g),Low=min(b['Low'] for b in g)))
    return result,incomplete


def main():
    bars,evidence=load();hours,incomplete=hourly(bars)
    gaps=[b['ts']-a['ts'] for a,b in zip(bars,bars[1:]) if b['ts']-a['ts']!=60]
    report=dict(**evidence,bars=len(bars),first_utc=datetime.fromtimestamp(bars[0]['ts'],timezone.utc).isoformat(),
        last_utc=datetime.fromtimestamp(bars[-1]['ts'],timezone.utc).isoformat(),complete_H1=len(hours),incomplete_H1_excluded=incomplete,
        M1_gap_intervals=len(gaps),gap_lengths_seconds=dict(Counter(gaps)),gaps_not_filled=True,
        exact_strategy_definition_confirmed=False,backtest_run=False,real_orders=False)
    (HERE/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
