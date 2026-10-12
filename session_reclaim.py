"""Previous-session failed break; closed-bar levels, no trained model/orders."""
import math


def setup(bar,previous_high,previous_low,atr):
    vals=[bar[k] for k in ('Open','High','Low','Close')]+[previous_high,previous_low,atr]
    if not all(math.isfinite(v) and v>0 for v in vals) or previous_high<=previous_low:
        raise ValueError('invalid_setup_data')
    o,h,l,c=(bar[k] for k in ('Open','High','Low','Close'))
    if not l<=min(o,c)<=max(o,c)<=h: raise ValueError('invalid_ohlc')
    # Double sweep is ambiguous; no choosing whichever side later wins.
    if h>previous_high and l<previous_low: return None
    if h>previous_high and previous_low<c<previous_high and c<o:
        return dict(direction=-1,stop=h+.1*atr,target=(previous_high+previous_low)/2)
    if l<previous_low and previous_low<c<previous_high and c>o:
        return dict(direction=1,stop=l-.1*atr,target=(previous_high+previous_low)/2)
    return None


def entry_terms(intent,price,cost):
    if intent is None: return None
    side=intent['direction']
    if not math.isfinite(price) or price<=0 or cost<0 or not math.isfinite(cost):
        raise ValueError('invalid_entry_price')
    risk=side*(price-intent['stop'])
    reward=side*(intent['target']-price)
    # Net target/planned loss after fixed conditional all-in price cost.
    if risk<=0 or reward<=cost or (reward-cost)/(risk+cost)<1.5:
        return None
    return dict(direction=side,risk=risk,target_multiple=reward/risk,
                stop=intent['stop'],target=intent['target'])
