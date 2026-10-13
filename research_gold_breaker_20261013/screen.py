"""Frozen video interpretation on actual cached XAUUSD M1. No orders/DB."""
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from bisect import bisect_left
import hashlib
import importlib.util
import json
import math
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gold_source_audit',HERE/'audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
sys.path.insert(0,str(HERE.parent/'research_ny_h4_20261013'))
from compare import summarize

SETTINGS={'main':(.8,1.5),'sensitivity':(.7,1.)}


def anchor_events(bars,setting):
    hours,_=audit.hourly(bars);body,minrange=SETTINGS[setting]
    events=[];trs=[];previous=None
    for h in hours:
        if previous is None or h['ts']!=previous['ts']+3600:trs=[]
        span=h['High']-h['Low'];atr=sum(trs)/14 if len(trs)==14 else None
        if atr and span>0 and abs(h['Close']-h['Open'])/span>=body and span>=minrange*atr:
            events.append(dict(ts=h['ts']+3600,high=h['High'],low=h['Low'],anchor_ts=h['ts']))
        tr=max(span,abs(h['High']-previous['Close']),abs(h['Low']-previous['Close'])) if trs and previous else span
        trs=(trs+[tr])[-14:];previous=h
    return events


def detect(bars,setting='main'):
    events=anchor_events(bars,setting);index=0;anchor=None;side=0;sweep=None;pivots=[];segment=[];used=False;orders=[]
    def expire(ts):
        if orders and orders[-1]['expires'] is None:orders[-1]['expires']=ts
    for b in bars:
        if segment and b['ts']-segment[-1]['ts']!=60:
            expire(b['ts']);anchor=None;side=0;pivots=[];segment=[];used=False
        while index<len(events) and events[index]['ts']<=b['ts']:
            expire(events[index]['ts']);anchor=events[index];index+=1
            side=0;sweep=None;pivots=[];segment=[];used=False
        if anchor is None:continue
        segment.append(b);segment=segment[-3:]
        if used:continue
        if side==0:
            upper=b['High']>anchor['high'];lower=b['Low']<anchor['low']
            if upper and lower:used=True;pivots=[];continue
            if upper:side=-1;sweep=b['ts']
            elif lower:side=1;sweep=b['ts']
        if len(segment)==3:
            left,p,right=segment
            high=p['High']>left['High'] and p['High']>right['High']
            low=p['Low']<left['Low'] and p['Low']<right['Low']
            if high and low:pivots=[];continue
            if high or low:
                point=dict(kind='H' if high else 'L',price=p['High'] if high else p['Low'],ts=p['ts'])
                if pivots and pivots[-1]['kind']==point['kind']:
                    if (point['price']>pivots[-1]['price'] if high else point['price']<pivots[-1]['price']):pivots[-1]=point
                else:pivots.append(point);pivots=pivots[-3:]
        if not side or len(pivots)!=3:continue
        a,c,d=pivots
        correct=[p['kind'] for p in pivots]==(['H','L','H'] if side==-1 else ['L','H','L'])
        swept=(d['price']>a['price'] if side==-1 else d['price']<a['price']) and d['ts']>=sweep
        broken=b['Close']<c['price'] if side==-1 else b['Close']>c['price']
        if correct and swept and broken:
            stop=d['price']-side*.01;entry=c['price'];distance=side*(entry-stop)
            if distance<=0 or (b['High']>=stop if side==-1 else b['Low']<=stop):used=True;continue
            orders.append(dict(ts=b['ts']+60,side=side,entry=entry,stop=stop,target=entry+side*2*distance,
                anchor_ts=anchor['anchor_ts'],sweep_ts=sweep,pivots=pivots.copy(),expires=None,
                ny_date=datetime.fromtimestamp(b['ts'],timezone.utc).date().isoformat()))
            used=True
    return orders


def outcome(order,path,cost):
    filled=False;previous=None;entry=order['entry'];side=order['side'];stop=order['stop'];target=order['target'];distance=side*(entry-stop)
    for b in path:
        if previous is not None and b['ts']-previous!=60:return dict(status='unknown' if filled else 'cancelled',reason='path_gap')
        previous=b['ts']
        just_filled=False
        if not filled:
            if order['expires'] is not None and b['ts']>=order['expires']:return dict(status='cancelled',reason='anchor_replaced_or_gap')
            touched=b['Low']<=entry-.01 if side==1 else b['High']>=entry+.01
            if not touched:continue
            if side*(b['Open']-stop)<=0:return dict(status='cancelled',reason='open_through_stop')
            filled=True;just_filled=True
        stopped=b['Low']<=stop if side==1 else b['High']>=stop
        targeted=b['High']>=target if side==1 else b['Low']<=target
        if stopped:
            gap=not just_filled and side*(b['Open']-stop)<=0
            exit_=b['Open'] if gap else stop
            return dict(status='closed',reason='stop_gap' if gap else 'stop',net_R=(side*(exit_-entry)-cost)/(distance+cost),ambiguous=targeted,exit_ts=b['ts']+60)
        if targeted:
            if just_filled:return dict(status='unknown',reason='entry_target_same_bar_sequence')
            return dict(status='closed',reason='target',net_R=(2*distance-cost)/(distance+cost),ambiguous=False,exit_ts=b['ts']+60)
    return dict(status='unknown' if filled else 'pending',reason='coverage_end')


def main():
    bars,evidence=audit.load();times=[b['ts'] for b in bars]
    report=dict(protocol_sha256=hashlib.sha256((HERE/'TEST_PROTOCOL.md').read_bytes()).hexdigest(),source=evidence,
        exact_author_rules=False,real_orders=False,account_simulation=False,arms=[],gates={})
    for setting in SETTINGS:
        orders=detect(bars,setting);checks=[]
        for scenario,cost in [('base',.5),('stress',1.)]:
            rows=[]
            for o in orders:
                i=bisect_left(times,o['ts']);j=bisect_left(times,o['ts']+6*86400)
                path=bars[i:j]
                result=outcome(o,path,cost) if path and path[0]['ts']==o['ts'] else dict(status='unknown',reason='missing_first_active_bar')
                rows.append(dict(intent=o,**result))
            for phase in ('early','late'):
                chosen=[r for r in rows if (r['intent']['ts']<1782864000)==(phase=='early')]
                row=dict(setting=setting,scenario=scenario,phase=phase,**summarize(chosen))
                # Existing helper uses36cells, conservative for8 here; retain
                # and explicitly label actual correction rather than misstate it.
                row['ci_correction_cells']=36
                row['reasons']=dict(Counter(r['reason'] for r in chosen))
                report['arms'].append(row);print(json.dumps(row),flush=True)
                if scenario=='stress':checks.append(row)
        report['gates'][setting]=all(r['mean_net_R'] is not None and r['mean_net_R']>0 and r['simultaneous_95_ci'] and r['simultaneous_95_ci'][0]>0 and not r['statuses'].get('unknown') for r in checks) and checks[-1]['closed']>=100
    (HERE/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(gates=report['gates'])),flush=True)


if __name__=='__main__':main()
