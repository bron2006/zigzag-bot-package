"""Pure daily rules: shared by historical tests and local paper decisions."""
import math

DAY = 86400000
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
RULES = ('donchian55_20', 'momentum365')
VERSION = 'local-trend-v1'


def validate(rows):
    if not rows:
        raise ValueError('Empty daily history')
    previous = None
    for row in rows:
        ts = row[0]
        if not isinstance(ts, int) or ts % DAY or (previous is not None and ts-previous != DAY):
            raise ValueError('Daily history missing, unordered or duplicated')
        o,h,l,c = map(float,row[1:5])
        if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('Invalid daily OHLC')
        previous=ts


def decisions(rows, rule):
    validate(rows)
    if rule not in RULES:
        raise ValueError('Unknown fixed rule')
    closes=[float(r[4]) for r in rows]
    highs=[float(r[2]) for r in rows]
    lows=[float(r[3]) for r in rows]
    state=0
    result=[]
    for i,c in enumerate(closes):
        if rule=='momentum365':
            state=int(i>=365 and c>closes[i-365])
        elif i>=55:
            if c>max(highs[i-55:i]): state=1
            elif c<min(lows[i-20:i]): state=0
        result.append(state)
    return result


def execution_positions(rows,rule):
    desired=decisions(rows,rule)
    return [0,0]+desired[:-2] if len(rows)>=2 else [0]*len(rows)


def latest_decision(rows,rule,now_ms):
    validate(rows)
    today=now_ms//DAY*DAY
    completed=[r for r in rows if r[0]+DAY<=now_ms]
    if len(completed)<367 or completed[-1][0]!=today-DAY:
        raise ValueError('Latest completed day missing or insufficient warmup')
    # At today start, delayed signal is from day before yesterday.
    desired=decisions(completed,rule)
    return dict(day=today,signal_day=completed[-2][0],desired=desired[-2],rule=rule,version=VERSION)
