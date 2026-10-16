"""Decimal research-only replay, stable derived prices to 12 decimals.

The 12-place quantum removes binary subtraction residue far below M5 quote
resolution. It is NOT broker tick snapping or an executable order-price model.
Old study artifacts/shared simulators are not changed by this isolated repair.
"""
from decimal import Decimal as D, ROUND_HALF_EVEN

QUANTUM=D('0.000000000001')


def price(value):
    out=D(str(value))
    if not out.is_finite():raise ValueError('Nonfinite price')
    return out.quantize(QUANTUM,rounding=ROUND_HALF_EVEN)


def simulate(by_ts,entry_ts,step,side,distance,cost):
    if side not in (-1,1) or step not in (3600,14400):raise ValueError('Invalid research simulation terms')
    distance=price(distance);fee=D(str(cost))
    if distance<=0 or not fee.is_finite() or fee<0:raise ValueError('Invalid risk or cost')
    first=by_ts.get(entry_ts)
    if first is None:return dict(status='unknown',reason='missing_entry')
    entry=price(first['Open']);stop=entry-side*distance;target=entry+side*2*distance
    if min(entry,stop,target)<=0:raise ValueError('Invalid price geometry')
    for ts in range(entry_ts,entry_ts+step,300):
        bar=by_ts.get(ts)
        if bar is None:return dict(status='unknown',reason='path_gap')
        op,high,low,close=[price(bar[k]) for k in ('Open','High','Low','Close')]
        if not 0<low<=min(op,close)<=max(op,close)<=high:raise ValueError('Invalid OHLC')
        gap=side*(op-stop)<=0
        hit=low<=stop if side==1 else high>=stop
        take=high>=target if side==1 else low<=target
        if gap or hit or take:
            exit_=op if gap else stop if hit else target
            return dict(status='closed',reason='gap_stop' if gap else 'stop' if hit else 'target',
                net_R=float((side*(exit_-entry)-fee)/(distance+fee)),ambiguous=bool(hit and take),
                exit_ts=ts+300,entry=float(entry),exit=float(exit_),stop_distance=float(distance))
    return dict(status='closed',reason='deadline',net_R=float((side*(close-entry)-fee)/(distance+fee)),
                ambiguous=False,exit_ts=entry_ts+step,entry=float(entry),exit=float(close),stop_distance=float(distance))
