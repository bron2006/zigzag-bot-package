"""Offline audit of raw broker JSON, not a trading-strategy backtest."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def decode_bar(bar):
    # Protocol scale is fixed 100000; symbol digits only affect display precision.
    low = int(bar['low'])
    opened = low+int(bar.get('deltaOpen', 0))
    closed = low+int(bar.get('deltaClose', 0))
    high = low+int(bar.get('deltaHigh', 0))
    if min(low, opened, closed) <= 0 or high < max(opened, closed, low):
        raise ValueError('Invalid OHLC')
    return dict(Open=opened/100000, High=high/100000, Low=low/100000, Close=closed/100000,
                start_minute=int(bar['utcTimestampInMinutes']))


def inspect_history(history):
    decoded = sorted((decode_bar(bar) for bar in history['raw_trendbars']), key=lambda bar: bar['start_minute'])
    timestamps = [bar['start_minute'] for bar in decoded]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError('Duplicate daily timestamp')
    if not decoded:
        raise ValueError('Empty daily history')
    times = [datetime.fromtimestamp(t*60, tz=timezone.utc) for t in timestamps]
    specification = history['specification']
    result = dict(name=history['name'], bars=len(decoded), first=times[0].isoformat(), last=times[-1].isoformat(),
                  bar_start_utc_hours=sorted({time.hour for time in times}),
                  last_close=decoded[-1]['Close'],
                  maximum_gap_calendar_days=max((b-a).total_seconds()/86400 for a, b in zip(times, times[1:])),
                  gaps_over_five_days=[dict(from_start=a.isoformat(), to_start=b.isoformat(),
                                           calendar_days=(b-a).total_seconds()/86400)
                                      for a, b in zip(times, times[1:]) if (b-a).total_seconds() > 5*86400],
                  gaps_are_not_filled=True, historical_costs_available=False)
    if specification.get('swapCalculationType') == 'PIPS':
        pip = 10**(-int(specification['pipPosition']))
        # Sensitivity only. Neither realized annual fee nor historical broker costs.
        result['constant_current_long_swap_365_charge_days_per_notional'] = (
            float(specification['swapLong'])*pip*365/result['last_close'])
    return result


def main():
    root = Path(__file__).parent
    path = root/'broker_history_probe.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    result = dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  bar_price_divisor=100000, this_is_data_audit_not_strategy_test=True,
                  hypothetical_swap_365_charge_days_not_account_specific=True,
                  histories=[inspect_history(h) for h in raw['histories']])
    (root/'broker_history_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
