"""First half-hour predicts last half-hour, fixed offline paper diagnostic."""
import math


def evaluate(lookup,times,previous_close):
    """Only first6 completed bars determine direction; last6 evaluate it.

    Missing future data is unknown, NOT grounds to remove the signal.
    Intent known10:00NY, fixed entry15:30NY, exit16:00NY. No price-target
    optimization or current-day highs in signal. No actual orders/fills.
    """
    if len(times)!=78 or any(b-a!=300 for a,b in zip(times,times[1:])):
        raise ValueError('invalid_session_axis')
    if previous_close is None or any(t not in lookup for t in times[:6]):
        return dict(status='unknown',reason='missing_signal_data')
    first_close=float(lookup[times[5]]['Close'])
    if not all(math.isfinite(p) and p>0 for p in (previous_close,first_close)):
        raise ValueError('invalid_signal_price')
    direction=1 if first_close>previous_close else -1 if first_close<previous_close else 0
    if not direction: return dict(status='skipped',reason='flat_first_half_hour')
    if any(t not in lookup for t in times[72:]):
        return dict(status='unknown',reason='missing_exit_path',direction=direction)
    entry,exit_=float(lookup[times[72]]['Open']),float(lookup[times[77]]['Close'])
    if not all(math.isfinite(p) and p>0 for p in (entry,exit_)):
        raise ValueError('invalid_endpoint_price')
    return dict(status='measured',direction=direction,entry=entry,exit=exit_,
                signal_ts=times[5]+300,entry_ts=times[72],expiry_ts=times[77]+300)
