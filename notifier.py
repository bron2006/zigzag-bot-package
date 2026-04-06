# notifier.py
import logging
import time
import threading
import requests as _requests

from state import app_state

logger = logging.getLogger("notifier")

_SEND_FAIL_THRESHOLD = 5
_ALERT_COOLDOWN      = 300.0
_TG_API_URL          = "https://api.telegram.org/bot{token}/sendMessage"

_lock             = threading.Lock()
_send_fail_count  = 0
_last_alert_times : dict = {}


def _get_bot_token() -> str:
    try:
        from config import TELEGRAM_BOT_TOKEN
        return TELEGRAM_BOT_TOKEN or ""
    except Exception:
        return ""

def _get_admin_chat_id():
    try:
        from config import get_chat_id
        return get_chat_id()
    except Exception:
        return None

def _cooldown_ok(key: str) -> bool:
    with _lock:
        last = _last_alert_times.get(key, 0)
        if time.time() - last >= _ALERT_COOLDOWN:
            _last_alert_times[key] = time.time()
            return True
        return False

def _http_fallback(chat_id, text: str) -> bool:
    token = _get_bot_token()
    if not token or not chat_id:
        return False
    try:
        url  = _TG_API_URL.format(token=token)
        resp = _requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        if resp.ok:
            logger.info("HTTP fallback: повідомлення надіслано.")
            return True
        logger.warning(f"HTTP fallback failed: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception:
        logger.exception("HTTP fallback exception")
        return False


def send_signal(chat_id, text: str, parse_mode: str = "Markdown", reply_markup=None) -> bool:
    global _send_fail_count
    if not chat_id:
        logger.warning("send_signal: chat_id порожній, пропускаємо.")
        return False

    if app_state.updater:
        try:
            kwargs = dict(chat_id=chat_id, text=text, parse_mode=parse_mode)
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            app_state.updater.bot.send_message(**kwargs)
            with _lock:
                if _send_fail_count > 0:
                    logger.info(f"send_message відновлено (було {_send_fail_count} помилок)")
                _send_fail_count = 0
            return True
        except Exception as e:
            with _lock:
                _send_fail_count += 1
                current_fails = _send_fail_count
            logger.error(f"send_message failed ({current_fails}/{_SEND_FAIL_THRESHOLD}): {e}")
            if current_fails >= _SEND_FAIL_THRESHOLD:
                _on_send_threshold_reached(current_fails)
    else:
        logger.warning("send_signal: app_state.updater is None")
    return False


def notify_admin(text: str, alert_key: str = None) -> bool:
    if alert_key and not _cooldown_ok(alert_key):
        logger.debug(f"notify_admin пропущено (cooldown): {alert_key}")
        return False
    chat_id = _get_admin_chat_id()
    if not chat_id:
        logger.warning("notify_admin: chat_id адміна не налаштований.")
        return False
    if app_state.updater:
        try:
            app_state.updater.bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            logger.warning(f"notify_admin через updater failed: {e}. HTTP fallback...")
    return _http_fallback(chat_id, text)


def notify_bot_started() -> None:
    notify_admin("✅ ZigZag Bot запущено і готовий до роботи.", alert_key="bot_started")

def notify_bot_failed(reason: str) -> None:
    chat_id = _get_admin_chat_id()
    msg = f"🛑 ZigZag Bot: Telegram updater не запустився!\n\nПричина: {reason}"
    logger.critical(msg)
    _http_fallback(chat_id, msg)


def _on_send_threshold_reached(fail_count: int) -> None:
    global _send_fail_count
    if not _cooldown_ok("send_fail_threshold"):
        return
    msg = (
        f"🚨 ZigZag Bot: {fail_count} помилок send_message підряд.\n"
        "Спробую перезапустити polling..."
    )
    logger.error(msg)
    _http_fallback(_get_admin_chat_id(), msg)
    _restart_polling()
    with _lock:
        _send_fail_count = 0


def _restart_polling() -> None:
    logger.warning("Перезапуск Telegram bot polling...")
    if app_state.updater:
        try:
            app_state.updater.stop()
        except Exception:
            logger.exception("Не вдалося зупинити старий updater")
        app_state.updater = None
    time.sleep(3)
    try:
        from bot import start_telegram_bot
        start_telegram_bot()
        _http_fallback(_get_admin_chat_id(), "✅ ZigZag Bot: Telegram polling перезапущено.")
    except Exception:
        logger.exception("Не вдалося перезапустити Telegram bot")
        _http_fallback(
            _get_admin_chat_id(),
            "🛑 ZigZag Bot: не вдалося перезапустити polling. Потрібне ручне втручання."
        )
