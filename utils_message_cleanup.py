# utils_message_cleanup.py
from telegram.error import BadRequest
import logging

logger = logging.getLogger(__name__)

BOT_DATA_KEY = "sent_messages_by_chat"
def bot_track_message(bot_data, chat_id: int, message_id: int, max_store: int = 200):
    if bot_data is None:
        logger.debug("bot_track_message: bot_data is None; skipping track")
        return
    store = bot_data.setdefault(BOT_DATA_KEY, {})
    lst = store.setdefault(str(chat_id), [])
    lst.append(int(message_id))
    if len(lst) > max_store:
        store[str(chat_id)] = lst[-max_store:]
    bot_data[BOT_DATA_KEY] = store
    logger.debug("Tracked message chat=%s mid=%s (stored=%d)", chat_id, message_id, len(store.get(str(chat_id), [])))

def bot_clear_messages(bot, bot_data, chat_id: int, limit: int = 20):
    if bot_data is None:
        logger.debug("bot_clear_messages: bot_data is None; nothing to clear")
        return
    store = bot_data.get(BOT_DATA_KEY, {})
    lst = store.get(str(chat_id), [])
    if not lst:
        logger.debug("bot_clear_messages: no tracked messages for chat=%s", chat_id)
        return
    to_delete = lst[-limit:]
    logger.debug("bot_clear_messages: Намагаюся видалити %d повідомлень для chat=%s.", len(to_delete), chat_id)
    for mid in to_delete:
        try:
            bot.delete_message(chat_id=chat_id, message_id=mid)
            logger.debug("Deleted message chat=%s mid=%s", chat_id, mid)
        except BadRequest as e:
            logger.debug("safe_delete failed: %s (chat=%s mid=%s)", e, chat_id, mid)
        except Exception:
            logger.exception("Unexpected error deleting message chat=%s mid=%s", chat_id, mid)
    remaining = [m for m in lst if m not in to_delete]
    if remaining:
        store[str(chat_id)] = remaining
    else:
        store.pop(str(chat_id), None)
    bot_data[BOT_DATA_KEY] = store
    logger.debug("bot_clear_messages: remaining tracked for chat=%s = %d", chat_id, len(store.get(str(chat_id), [])))
