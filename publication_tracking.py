"""Bounded receipt retry queue. A crash without a receipt remains unconfirmed."""
from threading import Lock
import logging
import db

_lock = Lock()
_pending = {}


def remember(identifier, web, telegram):
    with _lock:
        if identifier not in _pending and len(_pending) >= 1000:
            logging.getLogger(__name__).error('Publication retry queue full; receipt remains unconfirmed id=%s', identifier)
            return False
        _pending[identifier] = (web, telegram)
    return True


def save(identifier, web, telegram):
    ok = db.save_signal_publication(identifier, web, telegram)
    if ok:
        with _lock:
            if _pending.get(identifier) == (web, telegram):
                _pending.pop(identifier, None)
    return ok


def flush_pending(limit=3):
    with _lock:
        items = list(_pending.items())[:limit]
    for identifier, (web, telegram) in items:
        try:
            if not save(identifier, web, telegram):
                break  # One unavailable DB must not spend the whole cycle retrying.
        except Exception:
            logging.getLogger(__name__).exception('Publication receipt retry failed id=%s', identifier)
            break
