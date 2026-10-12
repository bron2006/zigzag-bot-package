"""Owner-defined NY 00:00..04:00 range, M5 CLOSE break then CLOSE reclaim.

No model, broker, account or orders. Range/stop extremes include wicks;
only confirmations use closes. All timestamps are UTC seconds.
"""
from collections import defaultdict
from datetime import datetime,time,timedelta,timezone
import math
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
RULE='ny_h4_close_reclaim_v1'


def bounds(day):
    start=datetime.combine(day,time(0),NY)
    end=datetime.combine(day,time(4),NY)
    midnight=datetime.combine(day+timedelta(days=1),time(0),NY)
    return int(start.timestamp()),int(end.timestamp()),int(midnight.timestamp())


def detect(bars):
    """One first completed setup per pair/NY day. Incomplete days fail closed."""
    groups=defaultdict(list);previous=-float('inf')
    for b in bars:
        ts=b['ts'];values=[b[k] for k in ('Open','High','Low','Close')]
        if not isinstance(ts,(int,float)) or not math.isfinite(ts) or ts%300 or ts<=previous:
            raise ValueError('invalid_bar_order_or_time')
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in values) or not b['Low']<=min(b['Open'],b['Close'])<=max(b['Open'],b['Close'])<=b['High']:
            raise ValueError('invalid_OHLC')
        groups[datetime.fromtimestamp(ts,NY).date()].append(b);previous=ts
    intents=[];states=[]
    for day,group in sorted(groups.items()):
        start,end,midnight=bounds(day)
        state=dict(ny_date=day.isoformat(),range_start=start,range_end=end,
                   status='forming_range',rule=RULE,high=None,low=None)
        anchor=[b for b in group if start<=b['ts']<end]
        if [b['ts'] for b in anchor]!=list(range(start,end,300)):
            if group[-1]['ts']+300>=end:state['status']='incomplete_range'
            states.append(state);continue
        high=max(b['High'] for b in anchor);low=min(b['Low'] for b in anchor)
        state.update(high=high,low=low,status='waiting_breakout')
        if high<=low:
            state['status']='invalid_flat_range';states.append(state);continue
        side=0;extreme=None;breakout=None;expected=end
        for b in group:
            if b['ts']<end:continue
            if b['ts']!=expected:
                state['status']='post_range_data_gap';break
            expected=b['ts']+300
            if not side:
                if b['Close']<low:side=1;extreme=b['Low']
                elif b['Close']>high:side=-1;extreme=b['High']
                else:continue
                breakout=b['ts']+300
                state.update(status='waiting_return',side=side,breakout_ts=breakout,stop=extreme)
                continue
            extreme=min(extreme,b['Low']) if side==1 else max(extreme,b['High'])
            state['stop']=extreme
            returned=b['Close']>low if side==1 else b['Close']<high
            if returned and b['ts']+300<midnight:
                intent=dict(rule=RULE,ts=b['ts']+300,day=start//86400,ny_date=day.isoformat(),
                    side=side,stop=extreme,target=None,target_multiple=2.,
                    breakout_ts=breakout,return_close=b['Close'],
                    range_high=high,range_low=low,range_start=start,range_end=end,
                    exit_policy='stop_or_target_no_forced_time_exit')
                intents.append(intent)
                state.update(status='setup_complete',entry_ts=intent['ts'])
                break
        states.append(state)
    return dict(intents=intents,states=states)
