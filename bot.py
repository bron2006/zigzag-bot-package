# bot.py
import logging
import threading

from telegram.ext import CallbackQueryHandler, CommandHandler, Filters, MessageHandler, Updater

import telegram_ui
from config import TELEGRAM_BOT_TOKEN
from errors import ConfigError, TelegramError
from notifier import notify_bot_failed, notify_bot_started
from state import app_state

logger = logging.getLogger("bot")

_polling_lock = threading.RLock()


def _build_updater() -> Updater:
    return Updater(
        token=TELEGRAM_BOT_TOKEN,
        use_context=True,
        workers=8,
    )


def _register_handlers(updater: Updater) -> None:
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
    dp.add_handler(CommandHandler("stats", telegram_ui.stats_command))
    dp.add_handler(CommandHandler("live", telegram_ui.live_command))

    dp.add_handler(MessageHandler(Filters.regex(r"^(МЕНЮ|[Mm][Ee][Nn][Uu])$"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))


def _start_polling_thread(updater: Updater) -> None:
    def runner():
        try:
            logger.info("Запускаємо Telegram polling у dedicated thread...")
            updater.start_polling(drop_pending_updates=False)
            logger.info("Telegram polling успішно стартував.")
        except Exception as e:
            logger.exception("Помилка в Telegram polling thread")
            notify_bot_failed(str(e))

    thread = threading.Thread(
        target=runner,
        name="telegram-polling-starter",
        daemon=True,
    )
    thread.start()


def start_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        raise ConfigError("TELEGRAM_BOT_TOKEN не налаштований — Telegram вимкнено")

    with _polling_lock:
        try:
            if app_state.updater is not None:
                logger.info("Telegram bot вже ініціалізовано — повторний старт пропущено")
                return app_state.updater

            updater = _build_updater()
            _register_handlers(updater)

            app_state.updater = updater
            _start_polling_thread(updater)

            logger.info("Telegram bot запущено. Команди: /start /symbols /stats /live")
            notify_bot_started()
            return updater

        except ConfigError:
            raise
        except Exception as e:
            logger.exception("Не вдалося запустити Telegram bot")
            notify_bot_failed(str(e))
            raise TelegramError(f"Не вдалося запустити: {e}", recoverable=False) from e
