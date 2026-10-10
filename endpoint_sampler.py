"""One bounded background sampler; never blocks cTrader's event loop on DB I/O."""
import logging
import threading
import time

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_targets = {}
_captured = {}
_thread = None


def register(outcome_id, pair, deadline):
    global _thread
    with _lock:
        _targets[outcome_id] = (pair, deadline)
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="signal-endpoint-sampler", daemon=True)
            _thread.start()


def unregister(outcome_id):
    with _lock:
        _targets.pop(outcome_id, None)
        _captured.pop(outcome_id, None)


def observe(pair, quote):
    """Capture the first full tick inside each registered window immediately.

    Memory only: safe on the price event loop; SQL remains in the worker.
    This also avoids losing a tick through per-second history downsampling.
    """
    with _lock:
        for outcome_id, (target_pair, deadline) in _targets.items():
            if target_pair == pair and deadline <= quote["ts"] <= deadline + 5:
                _captured.setdefault(outcome_id, dict(quote))


def captured(outcome_id):
    with _lock:
        quote = _captured.get(outcome_id)
        return dict(quote) if quote else None


def sample_once(state, save, now):
    with _lock:
        targets = list(_targets.items())
    # Capture ALL endpoints before potentially slow DB writes. Retain a captured
    # quote across retries even after the rolling price history has expired.
    for outcome_id, (pair, deadline) in targets:
        if now < deadline:
            continue
        with _lock:
            quote = _captured.get(outcome_id)
        if quote is None:
            quote = state.get_signal_endpoint_quote(pair, deadline, now, 5.0, full=True)
            if quote:
                with _lock:
                    _captured[outcome_id] = quote
    for outcome_id, (pair, deadline) in targets:
        with _lock:
            quote = _captured.get(outcome_id)
        saved = bool(quote and save(outcome_id, quote))
        if saved or (not quote and now > deadline + 600):
            with _lock:
                _targets.pop(outcome_id, None)
                _captured.pop(outcome_id, None)
            if not saved:
                logger.error("Endpoint sampler exhausted retention id=%s", outcome_id)


def _run():
    import db
    from state import app_state
    while True:
        try:
            sample_once(app_state, db.save_signal_endpoint, time.time())
        except Exception:
            logger.exception("Endpoint sampler failed; will retry")
        time.sleep(1)
