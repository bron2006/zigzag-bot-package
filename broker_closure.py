"""Pure fail-closed weekly schedule proof. No missing prices are synthesized."""
from datetime import datetime
from functools import lru_cache
import json
from zoneinfo import ZoneInfo


def closure_predicate(metadata):
    if not metadata:return None
    try:
        tz=metadata['scheduleTimeZone'];ZoneInfo(tz)
        intervals=tuple((i['startSecond'],i['endSecond']) for i in metadata['schedule'])
        if any(type(a) is not int or type(b) is not int for a,b in intervals):return None
        if not intervals or any(not 0<=a<b<=604800 for a,b in intervals):return None
        key=json.dumps(dict(tz=tz,intervals=intervals),sort_keys=True)
    except (KeyError,ValueError,TypeError):return None
    return lambda start,end:fully_closed(start,end,key)


@lru_cache(maxsize=8192)
def fully_closed(start,end,key):
    if not isinstance(start,int) or not isinstance(end,int) or not 0<end-start<=7*86400:return False
    config=json.loads(key);tz=ZoneInfo(config['tz']);intervals=config['intervals']
    # Exact second-by-second proof, cached by actual UTC interval + schedule.
    # A partially open missing bar MUST remain unknown; no sparse sampling.
    for ts in range(start,end):
        local=datetime.fromtimestamp(ts,tz)
        second=((local.weekday()+1)%7)*86400+local.hour*3600+local.minute*60+local.second
        if any(a<=second<b for a,b in intervals):return False
    return True
