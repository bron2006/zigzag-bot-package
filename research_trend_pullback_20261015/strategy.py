"""Deterministic close-confirmed multi-timeframe intents; no model or orders."""
from bisect import bisect_right
from datetime import datetime,timezone
import math


def detect(h1,h4,*,signal_step=3600,context_step=14400):
    if signal_step not in (1800,3600,7200,28800) or context_step not in (7200,14400,28800,86400):
        raise ValueError('Unsupported research chart')
    if context_step<=signal_step:raise ValueError('Context must be slower than signal chart')
    ends=[b['ts']+context_step for b in h4]
    if any(a>=b for a,b in zip(ends,ends[1:])):raise ValueError('Unsorted/duplicate H4')
    if any(a['ts']>=b['ts'] for a,b in zip(h1,h1[1:])):raise ValueError('Unsorted/duplicate H1')
    out=[]
    for previous,current in zip(h1,h1[1:]):
        decision=current['ts']+signal_step;dt=datetime.fromtimestamp(decision,timezone.utc)
        if dt.weekday()>=5 or not 8*3600<=decision%86400<=15*3600 or decision%signal_step:continue
        if current['ts']-previous['ts']!=signal_step:continue
        k=bisect_right(ends,decision)-1
        if k<0 or decision-ends[k]>2*context_step:continue
        context=h4[k]
        values=[context.get(n) for n in ('EMA50','EMA200','ADX','Close')]
        values += [current.get(n) for n in ('ATR','EMA20')]+[previous.get('EMA20')]
        if any(v is None or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):continue
        if current['ATR']<=0 or context['ADX']<20:continue
        long=context['EMA50']>context['EMA200'] and context['Close']>context['EMA50']
        short=context['EMA50']<context['EMA200'] and context['Close']<context['EMA50']
        side=0
        if long and previous['Close']<previous['Open'] and previous['Low']<=previous['EMA20'] and current['Close']>current['Open'] and current['Close']>max(previous['High'],current['EMA20']):side=1
        if short and previous['Close']>previous['Open'] and previous['High']>=previous['EMA20'] and current['Close']<current['Open'] and current['Close']<min(previous['Low'],current['EMA20']):side=-1
        if side:
            stop=min(previous['Low'],current['Low'])-.1*current['ATR'] if side==1 else max(previous['High'],current['High'])+.1*current['ATR']
            out.append(dict(decision_ts=decision,entry_ts=decision+300,side=side,stop=stop,
                signal_close=current['Close'],atr=current['ATR'],momentum=1 if previous['Close']>=previous['Open'] else -1,
                context_closed_ts=ends[k]))
    return out
