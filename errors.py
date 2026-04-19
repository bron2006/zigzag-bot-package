# errors.py
import logging
import time
import functools
import threading
import traceback

from locales import t

logger = logging.getLogger("errors")


class ZigZagError(Exception):
    def __init__(self, message: str, *, recoverable: bool = True, alert: bool = False):
        super().__init__(message)
        self.recoverable = recoverable
        self.alert = alert

class CTraderError(ZigZagError):
    def __init__(self, message: str, *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable, alert=not recoverable)

class SpotEventError(CTraderError):
    def __init__(self, message: str, symbol_id: int = None):
        super().__init__(message, recoverable=True)
        self.symbol_id = symbol_id

class ReconnectError(CTraderError):
    def __init__(self, message: str, attempts: int = 0):
        super().__init__(message, recoverable=False)
        self.attempts = attempts

class SignalError(ZigZagError):
    def __init__(self, message: str, *, pair: str = None, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable, alert=False)
        self.pair = pair

class TelegramError(ZigZagError):
    def __init__(self, message: str, *, recoverable: bool = True):
        super().__init__(message, recoverable=recoverable, alert=True)

class ConfigError(ZigZagError):
    def __init__(self, message: str):
        super().__init__(message, recoverable=False, alert=True)

class StaleDataError(ZigZagError):
    def __init__(self, message: str, *, pair: str = None, age_seconds: float = None):
        super().__init__(message, recoverable=True, alert=False)
        self.pair = pair
        self.age_seconds = age_seconds


class _ErrorRegistry:
    def __init__(self):
        self._lock     = threading.Lock()
        self._counts   : dict = {}
        self._last_err : dict = {}
        self._alerted  : dict = {}

    def record_error(self, context: str, threshold: int = 10, window: float = 60.0) -> int:
        with self._lock:
            now  = time.time()
            last = self._last_err.get(context, 0)
            if now - last > window:
                self._counts[context] = 0
            self._counts[context]   = self._counts.get(context, 0) + 1
            self._last_err[context] = now
            return self._counts[context]

    def record_success(self, context: str) -> None:
        with self._lock:
            prev = self._counts.get(context, 0)
            if prev > 0:
                logger.info(t("ops_recovered_after_errors", "en", context=context, count=prev))
            self._counts[context] = 0

    def should_alert(self, context: str, cooldown: float = 300.0) -> bool:
        with self._lock:
            now  = time.time()
            last = self._alerted.get(context, 0)
            if now - last >= cooldown:
                self._alerted[context] = now
                return True
            return False

    def get_count(self, context: str) -> int:
        with self._lock:
            return self._counts.get(context, 0)


_registry = _ErrorRegistry()


def _alert(text: str, alert_key: str = None) -> None:
    try:
        from notifier import notify_admin
        notify_admin(text, alert_key=alert_key)
    except ImportError:
        logger.warning(t("ops_notifier_unavailable", "en", text=text))
    except Exception:
        logger.exception(t("ops_alert_send_failed", "en"))


def _check_threshold(context, count, threshold, alert_cooldown, on_threshold):
    if count < threshold:
        return
    msg = t(
        "ops_threshold_reached",
        "en",
        context=context,
        count=count,
        action=t("ops_starting_recovery", "en") if on_threshold else t("ops_attention_required", "en"),
    )
    logger.error(msg)
    if _registry.should_alert(f"{context}_threshold", alert_cooldown):
        _alert(msg, alert_key=f"{context}_threshold")
    if on_threshold:
        try:
            on_threshold()
        except Exception:
            logger.exception(t("ops_threshold_callback_failed", "en", context=context))


def safe_twisted(
    context: str,
    *,
    threshold: int        = 10,
    window: float         = 60.0,
    alert_cooldown: float = 300.0,
    on_threshold          = None,
    reraise: bool         = False,
):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                _registry.record_success(context)
                return result
            except ZigZagError as e:
                count = _registry.record_error(context, threshold, window)
                logger.error(
                    f"[{context}] {type(e).__name__}: {e} "
                    f"({t('ops_consecutive', 'en')}: {count}, recoverable: {e.recoverable})\n"
                    + traceback.format_exc()
                )
                if e.alert and _registry.should_alert(context, alert_cooldown):
                    _alert(f"⚠️ [{context}] {type(e).__name__}: {e}",
                           alert_key=f"{context}_{type(e).__name__}")
                if not e.recoverable and _registry.should_alert(f"{context}_fatal", alert_cooldown):
                    _alert(t("ops_fatal_manual", "en", context=context, error=e), alert_key=f"{context}_fatal")
                _check_threshold(context, count, threshold, alert_cooldown, on_threshold)
                if reraise:
                    raise
            except Exception as e:
                count = _registry.record_error(context, threshold, window)
                logger.exception(
                    f"[{context}] {t('ops_unexpected', 'en')} {type(e).__name__}: {e} "
                    f"({t('ops_consecutive', 'en')}: {count}/{threshold})"
                )
                _check_threshold(context, count, threshold, alert_cooldown, on_threshold)
                if reraise:
                    raise
        return wrapper
    return decorator


def safe_call(
    context: str,
    *,
    threshold: int        = 5,
    window: float         = 120.0,
    alert_cooldown: float = 300.0,
    on_threshold          = None,
    default               = None,
):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                _registry.record_success(context)
                return result
            except ZigZagError as e:
                count = _registry.record_error(context, threshold, window)
                logger.error(f"[{context}] {type(e).__name__}: {e} ({t('ops_consecutive', 'en')}: {count})")
                if e.alert and _registry.should_alert(context, alert_cooldown):
                    _alert(f"⚠️ [{context}] {e}", alert_key=context)
                _check_threshold(context, count, threshold, alert_cooldown, on_threshold)
                return default
            except Exception as e:
                count = _registry.record_error(context, threshold, window)
                logger.exception(
                    f"[{context}] {t('ops_unexpected', 'en')} {type(e).__name__}: {e} "
                    f"({t('ops_consecutive', 'en')}: {count}/{threshold})"
                )
                _check_threshold(context, count, threshold, alert_cooldown, on_threshold)
                return default
        return wrapper
    return decorator


def get_error_stats() -> dict:
    with _registry._lock:
        return {
            ctx: {"consecutive_errors": count}
            for ctx, count in _registry._counts.items()
        }
