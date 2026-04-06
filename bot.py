# bot.py
import logging
from twisted.internet import reactor
from telegram.ext import (
    Updater, CommandHandler, MessageHandler,
    Filters, CallbackQueryHandler, PicklePersistence
)
from state import app_state
import telegram_ui
from config import TELEGRAM_BOT_TOKEN
from errors import ConfigError, TelegramError
from notifier import notify_bot_started, notify_bot_failed

logger = logging.getLogger("bot")


def start_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        raise ConfigError("TELEGRAM_BOT_TOKEN не налаштований — Telegram вимкнено")

    try:
        persistence_path = 'bot_persistence.pkl'
        logger.info(f"Файл persistence: {persistence_path}")
        persistence = PicklePersistence(filename=persistence_path)

        updater = Updater(
            token=TELEGRAM_BOT_TOKEN,
            use_context=True,
            persistence=persistence
        )
        app_state.updater = updater

        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start",   telegram_ui.start))
        dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
        dp.add_handler(MessageHandler(Filters.regex('^МЕНЮ$'),         telegram_ui.menu))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))

        reactor.callInThread(updater.start_polling)
        logger.info("Telegram bot запущено (polling у фоновому потоці).")
        notify_bot_started()

    except ConfigError:
        raise
    except Exception as e:
        logger.exception("Не вдалося запустити Telegram bot")
        notify_bot_failed(str(e))
        raise TelegramError(f"Не вдалося запустити Telegram bot: {e}", recoverable=False) from e
