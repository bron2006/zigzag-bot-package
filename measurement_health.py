"""Process-local diagnostics, explicitly NOT durable historical totals."""
from collections import Counter
from datetime import datetime, timezone
from threading import Lock

_lock = Lock()
_counts = Counter()
_started = datetime.now(timezone.utc).isoformat()


def count(reason):
    with _lock:
        _counts[reason] += 1


def snapshot():
    with _lock:
        return dict(since=_started, counters=dict(_counts), durable=False)
