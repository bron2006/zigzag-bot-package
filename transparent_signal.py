"""Explicit completed-M5-bar breakout intents; research, never orders."""
import math

VERSION = 'transparent-breakout-v1'
RULES = ('breakout', 'trend_pullback', 'band_reentry')


def generate(bars, rule='breakout'):
    """Trend + prior20bar breakout + directional body >= .25ATR14.

    Prior range excludes current bar; EMA50 slopes over5bars. Gaps reset
    all state. Thresholds are fixed, not optimized by outcome. No model.
    """
    if rule not in RULES:
        raise ValueError('invalid_rule')
    segment=[]
    emas=[]
    fast=[]
    true_ranges=[]
    result=[]
    previous_ts=None
    for bar in bars:
        ts=bar['ts']
        if not isinstance(ts,int) or (previous_ts is not None and ts<=previous_ts):
            raise ValueError('invalid_time_order')
        o,h,l,c=(float(bar[k]) for k in ('Open','High','Low','Close'))
        if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('invalid_ohlc')
        if previous_ts is not None and ts-previous_ts!=300:
            segment,emas,fast,true_ranges=[],[],[],[]
        previous=segment[-1]['Close'] if segment else c
        true_ranges.append(max(h-l,abs(h-previous),abs(l-previous)))
        ema=c if not emas else emas[-1]+2/51*(c-emas[-1])
        emas.append(ema)
        fast.append(c if not fast else fast[-1]+2/21*(c-fast[-1]))
        intent=dict(direction=0,ts=ts+300,reason='warmup')
        if len(segment)>=69:
            atr=sum(true_ranges[-14:])/14
            upper=max(b['High'] for b in segment[-20:])
            lower=min(b['Low'] for b in segment[-20:])
            direction=0
            if atr>0:
                if rule=='breakout':
                    if c>upper and c>ema and ema>emas[-6] and c-o>=.25*atr:
                        direction=1
                    elif c<lower and c<ema and ema<emas[-6] and o-c>=.25*atr:
                        direction=-1
                elif rule=='trend_pullback':
                    if fast[-1]>ema and ema>emas[-6] and previous<=fast[-2] and c>fast[-1] and c-o>=.25*atr:
                        direction=1
                    elif fast[-1]<ema and ema<emas[-6] and previous>=fast[-2] and c<fast[-1] and o-c>=.25*atr:
                        direction=-1
                else:
                    # Prior20 close distribution; current bar cannot move its bands.
                    closes=[b['Close'] for b in segment[-20:]]
                    mean=sum(closes)/20
                    sd=(sum((p-mean)**2 for p in closes)/20)**.5
                    if sd>0 and previous<mean-2*sd and c>mean-2*sd and c-o>=.25*atr:
                        direction=1
                    elif sd>0 and previous>mean+2*sd and c<mean+2*sd and o-c>=.25*atr:
                        direction=-1
            intent.update(direction=direction,reason=rule if direction else 'no_setup',
                          atr=atr,level=upper if direction==1 else lower if direction==-1 else None)
        result.append(intent)
        segment.append(dict(Close=c,High=h,Low=l))
        segment=segment[-70:]
        emas=emas[-70:]
        fast=fast[-70:]
        true_ranges=true_ranges[-14:]
        previous_ts=ts
    return result
