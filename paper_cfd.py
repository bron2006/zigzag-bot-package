"""Pure USD-quoted CFD paper math. No SDK, credentials, DB or order submission."""
from decimal import Decimal, ROUND_FLOOR
import math


def size_position(balance, entry, stop_distance, cost, *, minimum, step, maximum,
                  risk_fraction=.005, notional_cap=5, quote_currency='USD'):
    """Units, not lots/API hundredths. USD account AND USD quote required.

    Budget includes assumed round-trip price cost; NOT a guaranteed loss cap:
    adverse gaps/slippage can exceed it. Notional cap is not a margin model.
    """
    if quote_currency!='USD': raise ValueError('currency_conversion_required')
    vals=(balance,entry,stop_distance,minimum,step,maximum,risk_fraction,notional_cap)
    if not all(math.isfinite(v) and v>0 for v in vals) or not math.isfinite(cost) or cost<0:
        raise ValueError('invalid_sizing_terms')
    if risk_fraction>1 or minimum>maximum: raise ValueError('invalid_risk_or_size_limits')
    d=lambda x:Decimal(str(x))
    raw=min(d(balance)*d(risk_fraction)/(d(stop_distance)+d(cost)),
            d(balance)*d(notional_cap)/d(entry),d(maximum))
    units=(raw/d(step)).to_integral_value(rounding=ROUND_FLOOR)*d(step)
    return float(units) if units>=d(minimum) else 0.


def simulate_stop_trade(bars,index,direction,stop_distance,target_multiple=1.5,*,gap_is_closed=None):
    """Caller passes only session remainder; flat at session end, NOT15min expiry.

    OHLC conditional replay: stop-first if both touched, adverse stop gaps at
    open, favorable target gaps at target only. Not proof of ASK-side execution.
    """
    if direction not in (-1,1) or not 0<=index<len(bars): raise ValueError('invalid_entry')
    if not math.isfinite(stop_distance) or stop_distance<=0 or not math.isfinite(target_multiple) or target_multiple<=0:
        raise ValueError('invalid_stop_target')
    entry=float(bars[index]['Open'])
    stop,target=entry-direction*stop_distance,entry+direction*target_multiple*stop_distance
    if min(entry,stop,target)<=0: raise ValueError('invalid_price_geometry')
    previous_ts=None;closures=0
    for i in range(index,len(bars)):
        b=bars[i]
        ts=b['ts']
        if previous_ts is not None and ts-previous_ts!=300:
            if ts>previous_ts+300 and gap_is_closed is not None and gap_is_closed(previous_ts+300,ts):closures+=1
            else:return dict(status='unknown',reason='path_gap',entry=entry,stop=stop,target=target)
        o,h,l,c=(float(b[k]) for k in ('Open','High','Low','Close'))
        if not all(math.isfinite(p) and p>0 for p in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('invalid_ohlc')
        stopped=direction*(o-stop)<=0 or (l<=stop if direction==1 else h>=stop)
        targeted=h>=target if direction==1 else l<=target
        if stopped or targeted:
            gap=direction*(o-stop)<=0
            exit_=o if gap else stop if stopped else target
            reason='stop_gap' if gap else 'stop' if stopped else 'target'
            return dict(status='closed',reason=reason,entry=entry,stop=stop,target=target,
                        exit=exit_,direction=direction,gross_points=direction*(exit_-entry),
                        exit_ts=ts+300,entry_ts=bars[index]['ts'],ambiguous=stopped and targeted,
                        scheduled_closure_gaps=closures)
        previous_ts=ts
    exit_=float(bars[-1]['Close'])
    return dict(status='closed',reason='session_end',entry=entry,stop=stop,target=target,
                exit=exit_,direction=direction,gross_points=direction*(exit_-entry),
                entry_ts=bars[index]['ts'],exit_ts=bars[-1]['ts']+300,ambiguous=False,
                scheduled_closure_gaps=closures)


def net_usd(units,gross_points,cost):
    """USDquoted unit payoff ONLY; explicit hypothetical ALL-IN price cost."""
    if not all(math.isfinite(v) for v in (units,gross_points,cost)) or units<0 or cost<0:
        raise ValueError('invalid_pnl')
    return (Decimal(str(units))*(Decimal(str(gross_points))-Decimal(str(cost)))).quantize(Decimal('.01'))
