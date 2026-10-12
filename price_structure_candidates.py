"""Causal H1 FX price structure candidates. No model, credentials or orders."""
import math

RULES=('channel24','failed24','compression')


def generate(hours,rule):
    if rule not in RULES: raise ValueError('unknown_rule')
    history=[];trs=[];previous=None;compression=None;used=set();out=[]
    for b in hours:
        ts=b['ts'];o,h,l,c=[b[k] for k in ('Open','High','Low','Close')]
        if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('invalid_OHLC')
        if previous is not None and ts<=previous['ts']: raise ValueError('unordered_hours')
        if previous is None or ts-previous['ts']!=3600:
            history=[];trs=[];compression=None
        tr=max(h-l,abs(h-previous['Close']),abs(l-previous['Close'])) if history else h-l
        trs.append(tr);trs=trs[-14:]
        atr=sum(trs)/14 if len(trs)==14 else None
        day=ts//86400;hour=(ts%86400)//3600
        if compression and compression['day']!=day:compression=None
        if hour==7 and atr and h-l<=.75*atr:
            compression=dict(day=day,high=h,low=l)
        decision=ts+3600
        if len(history)==24 and atr and atr>0 and 9<=hour+1<=15 and day not in used:
            high=max(x['High'] for x in history);low=min(x['Low'] for x in history)
            side=0;stop=None;target=None
            if rule=='channel24':side=1 if c>high else -1 if c<low else 0
            elif rule=='failed24':
                if l<low and low<c<high and c>o:side=1;stop=l-.1*atr;target=(low+high)/2
                elif h>high and low<c<high and c<o:side=-1;stop=h+.1*atr;target=(low+high)/2
            elif compression:
                side=1 if c>compression['high'] else -1 if c<compression['low'] else 0
            if side:
                used.add(day)
                out.append(dict(ts=decision,day=day,side=side,atr=atr,stop=stop,target=target,rule=rule))
        history.append(b);history=history[-24:];previous=b
    return out
