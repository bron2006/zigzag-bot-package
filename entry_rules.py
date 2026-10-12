"""Causal completed-bar paper entry rules. No broker orders or application imports."""
import math

VERSION = 'entry-comparison-v1'
POLICIES = ('immediate', 'delay_one_bar', 'pullback_confirm')
PERIOD = 300


def choose_entry(bars, signal_index, direction, atr, policy):
    """Signal exists at bar close. Entry is a SUBSEQUENT open, not that close.

    Fixed research policy: pullback .25ATR, invalidation .75ATR, no-chase
    .5ATR, at most 3 subsequent completed bars. Uses closes only: OHLC
    touch order is not inferred. Return explicit skip/gap/unresolved states.
    """
    if policy not in POLICIES or direction not in (-1, 1):
        raise ValueError('invalid_policy_or_direction')
    if not math.isfinite(atr) or atr <= 0:
        raise ValueError('invalid_atr')
    anchor = float(bars[signal_index]['Close'])
    if not math.isfinite(anchor) or anchor <= 0:
        raise ValueError('invalid_anchor')

    def next_open(index):
        if index >= len(bars):
            return dict(status='unresolved', reason='missing_entry_bar')
        if int(bars[index]['ts']) != int(bars[signal_index]['ts']) + (index-signal_index)*PERIOD:
            return dict(status='unknown', reason='data_gap')
        price = float(bars[index]['Open'])
        if not math.isfinite(price) or price <= 0:
            raise ValueError('invalid_open')
        if policy == 'pullback_confirm':
            move = direction*(price-anchor)/atr
            if move <= -.75 or move >= .5:
                return dict(status='skipped', reason='gap_outside_entry_zone',decision_ts=int(bars[index]['ts']))
        return dict(status='entered', index=index, price=price, ts=int(bars[index]['ts']),decision_ts=int(bars[index]['ts']))

    if policy == 'immediate':
        return next_open(signal_index+1)
    if policy == 'delay_one_bar':
        # Verify the intervening bar too; never bridge a missing interval.
        if signal_index+1 >= len(bars):
            return dict(status='unresolved', reason='missing_wait_bar')
        if int(bars[signal_index+1]['ts']) != int(bars[signal_index]['ts'])+PERIOD:
            return dict(status='unknown', reason='data_gap')
        return next_open(signal_index+2)
    touched = False
    previous = anchor
    for offset in range(1, 4):
        index = signal_index+offset
        if index >= len(bars):
            return dict(status='unresolved', reason='missing_wait_bar')
        bar = bars[index]
        if int(bar['ts']) != int(bars[signal_index]['ts'])+offset*PERIOD:
            return dict(status='unknown', reason='data_gap')
        close, open_ = float(bar['Close']), float(bar['Open'])
        if not all(math.isfinite(p) and p > 0 for p in (close, open_)):
            raise ValueError('invalid_bar')
        move = direction*(close-anchor)/atr
        if move <= -.75:
            return dict(status='skipped', reason='idea_invalidated',decision_ts=int(bar['ts'])+PERIOD)
        if move >= .5:
            return dict(status='skipped', reason='price_ran_away',decision_ts=int(bar['ts'])+PERIOD)
        if touched and direction*(close-open_) > 0 and direction*(close-previous) > 0 and move <= 0:
            return next_open(index+1)
        if move <= -.25:
            touched = True
        previous = close
    return dict(status='skipped', reason='confirmation_timeout',decision_ts=int(bars[signal_index+3]['ts'])+PERIOD)


def settle(bars, entry, direction):
    """15 minutes FROM ENTRY. Direction-only hypothetical 80% payout."""
    if entry['status'] != 'entered':
        return dict(entry)
    index = entry['index']
    for offset in range(3):
        target = index+offset
        if target >= len(bars) or int(bars[target]['ts']) != entry['ts']+offset*PERIOD:
            return dict(status='unknown', reason='missing_expiry_path')
    exit_ = float(bars[index+2]['Close'])
    if not math.isfinite(exit_) or exit_ <= 0:
        raise ValueError('invalid_exit')
    change = direction*(exit_-entry['price'])
    status = 'win' if change > 0 else 'loss' if change < 0 else 'refund'
    return dict(entry, status=status, exit=exit_, expiry_ts=entry['ts']+900,
                unit_pnl=.8 if status == 'win' else -1 if status == 'loss' else 0)
