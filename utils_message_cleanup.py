# utils_message_cleanup.py
from telegram.error import BadRequest
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

BOT_DATA_KEY = "sent_messages_by_chat"  # dict: chat_id -> [message_id,...]

def _ensure_store(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    if bot_data is None:
        return {}
    if not isinstance(bot_data, dict):
        # dispatcher.bot_data might be a MutableMapping; try to use it as dict-like
        try:
            return dict(bot_data)
        except Exception:
            return {}
    return bot_data

def bot_track_message(bot_data: Dict[str, Any], chat_id: int, message_id: int, max_store: int = 200):
    """
    Записує message_id у bot_data під ключем BOT_DATA_KEY.
    bot_data — повинен бути dispatcher.bot_data або context.bot_data (mapping).
    """
    if bot_data is None:
        logger.debug("bot_track_message: bot_data is None; skipping track.")
        return
    store = bot_data.setdefault(BOT_DATA_KEY, {})
    lst = store.setdefault(str(chat_id), [])
    lst.append(message_id)
    if len(lst) > max_store:
        store[str(chat_id)] = lst[-max_store:]
    bot_data[BOT_DATA_KEY] = store
    logger.debug("Tracked message chat=%s mid=%s (stored=%d)", chat_id, message_id, len(store.get(str(chat_id), [])))

def bot_clear_messages(bot, bot_data: Dict[str, Any], chat_id: int, limit: int = 20):
    """
    Видаляє до 'limit' останніх відстежених повідомлень з чату і очищає запис.
    - bot: telegram.Bot або ExtBot
    - bot_data: dispatcher.bot_data або context.bot_data
    """
    if not bot_data:
        logger.debug("bot_clear_messages: bot_data is None or empty; nothing to clear.")
        return

    store = bot_data.get(BOT_DATA_KEY, {})
    lst = store.get(str(chat_id), [])
    if not lst:
        logger.debug("bot_clear_messages: no tracked messages for chat=%s", chat_id)
        return

    to_delete = lst[-limit:] if limit else lst[:]
    logger.debug(f"bot_clear_messages: Намагаюся видалити {len(to_delete)} повідомлень для chat={chat_id}.")

    for mid in to_delete:
        try:
            bot.delete_message(chat_id=chat_id, message_id=mid)
            logger.debug("Deleted message chat=%s mid=%s", chat_id, mid)
        except BadRequest as e:
            # нормально — повідомлення може бути вже не видалиме
            logger.debug("safe_delete failed: %s (chat=%s mid=%s)", e, chat_id, mid)
        except Exception as e:
            logger.exception("Unexpected error deleting message chat=%s mid=%s: %s", chat_id, mid, e)

    # Оновлюємо запис — видаляємо ті, які ми пробували видалити.
    remaining = [m for m in lst if m not in to_delete]
    if remaining:
        store[str(chat_id)] = remaining
    else:
        store.pop(str(chat_id), None)

    bot_data[BOT_DATA_KEY] = store
    logger.debug("After clear, remaining tracked for chat=%s: %d", chat_id, len(store.get(str(chat_id), [])))
