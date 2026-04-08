# news_filter.py
import json
import logging
import queue
import threading
import time

import requests as _requests

from state import app_state

logger = logging.getLogger("notifier")

_SEND_FAIL_THRESHOLD = 5
_ALERT_COOLDOWN = 300.0
_TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

_queue: queue.Queue = queue.Queue(maxsize=1000)
_lock = threading.RLock()
_send_fail_count = 0
_last_alert_times: dict = {}


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


def _serialize_reply_markup(reply_markup):
    if reply_markup is None:
        return None

    try:
        if hasattr(reply_markup, "to_dict"):
            return reply_markup.to_dict()
        if hasattr(reply_markup, "to_json"):
            return json.loads(reply_markup.to_json())
    except Exception:
        logger.exception("Не вдалося серіалізувати reply_markup")

    return None


def _http_fallback(chat_id, text: str, parse_mode: str = None, reply_markup=None) -> bool:
    token = _get_bot_token()
    if not token or not chat_id:
        return False

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    serialized_reply_markup = _serialize_reply_markup(reply_markup)
    if serialized_reply_markup:
        payload["reply_markup"] = serialized_reply_markup

    try:
        url = _TG_API_URL.format(token=token)
        resp = _requests.post(url, json=payload, timeout=10)
        if resp.ok:
            logger.info("HTTP fallback: повідомлення надіслано.")
            return True

        logger.warning(f"HTTP fallback failed: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception:
        logger.exception("HTTP fallback exception")
        return False


def _deliver_message(payload: dict) -> bool:
    chat_id = payload.get("chat_id")
    text = payload.get("text", "")
    parse_mode = payload.get("parse_mode")
    reply_markup = payload.get("reply_markup")

    if not chat_id:
        logger.warning("deliver_message: chat_id порожній")
        return False

    updater = app_state.updater
    if updater:
        try:
            kwargs = {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            if reply_markup is not None:
                kwargs["reply_markup"] = reply_markup

            updater.bot.send_message(**kwargs)
            return True
        except Exception as e:
            logger.warning(f"deliver_message через updater failed: {e}. HTTP fallback...")
            return _http_fallback(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)

    return _http_fallback(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)


def _restart_polling_async() -> None:
    thread = threading.Thread(target=_restart_polling, name="tg-polling-restart", daemon=True)
    thread.start()


def _restart_polling() -> None:
    logger.warning("Перезапуск Telegram bot polling...")
    updater = app_state.updater

    if updater:
        try:
            updater.stop()
        except Exception:
            logger.exception("Не вдалося зупинити старий updater")
        finally:
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
            "🛑 ZigZag Bot: не вдалося перезапустити polling. Потрібне ручне втручання.",
        )


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
    _restart_polling_async()

    with _lock:
        _send_fail_count = 0


def _worker_loop():
    global _send_fail_count

    while True:
        try:
            payload = _queue.get()
            ok = _deliver_message(payload)

            with _lock:
                if ok:
                    if _send_fail_count > 0:
                        logger.info(f"send_message відновлено (було {_send_fail_count} помилок)")
                    _send_fail_count = 0
                else:
                    _send_fail_count += 1
                    current_fails = _send_fail_count

            if not ok:
                logger.error(f"send_message failed ({current_fails}/{_SEND_FAIL_THRESHOLD})")
                if current_fails >= _SEND_FAIL_THRESHOLD:
                    _on_send_threshold_reached(current_fails)

        except Exception:
            logger.exception("Помилка в notifier worker")
            time.sleep(1)


_worker_thread = threading.Thread(
    target=_worker_loop,
    name="notifier-worker",
    daemon=True,
)
_worker_thread.start()


def _enqueue(chat_id, text: str, parse_mode: str = None, reply_markup=None) -> bool:
    if not chat_id:
        logger.warning("_enqueue: chat_id порожній, пропускаємо.")
        return False

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "reply_markup": reply_markup,
    }

    try:
        _queue.put_nowait(payload)
        return True
    except queue.Full:
        logger.error("Notifier queue переповнена — повідомлення скинуто")
        return False


def send_signal(chat_id, text: str, parse_mode: str = "HTML", reply_markup=None) -> bool:
    return _enqueue(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)


def notify_admin(text: str, alert_key: str = None) -> bool:
    if alert_key and not _cooldown_ok(alert_key):
        logger.debug(f"notify_admin пропущено (cooldown): {alert_key}")
        return False

    chat_id = _get_admin_chat_id()
    if not chat_id:
        logger.warning("notify_admin: chat_id адміна не налаштований.")
        return False

    return _enqueue(chat_id, text, parse_mode=None, reply_markup=None)


def notify_bot_started() -> None:
    notify_admin("✅ ZigZag Bot запущено і готовий до роботи.", alert_key="bot_started")


def notify_bot_failed(reason: str) -> None:
    chat_id = _get_admin_chat_id()
    msg = f"🛑 ZigZag Bot: Telegram updater не запустився!\n\nПричина: {reason}"
    logger.critical(msg)
    _http_fallback(chat_id, msg)