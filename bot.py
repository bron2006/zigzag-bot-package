# bot.py
import logging
import threading

from telegram import BotCommand, BotCommandScopeChat
from telegram.ext import CallbackQueryHandler, CommandHandler, Filters, MessageHandler, Updater

import telegram_ui
from config import DEV_USER_ID, TELEGRAM_BOT_TOKEN
from errors import ConfigError, TelegramError
from notifier import notify_bot_failed
from state import app_state

logger = logging.getLogger("bot")

_polling_lock = threading.RLock()

# Telegram's own native "/" command-menu button (bottom-left of the
# message box in every Telegram client) - registered with
# BotCommandScopeChat so it's visible ONLY in the admin's own chat, never
# in the shared get_main_menu_kb() inline keyboard every subscriber sees
# (2026-08-22 audit fix: those buttons already existed as a reply
# keyboard attached to each command's response, but there was no way to
# discover them without already knowing to type /vwap_executor_status by
# hand - this is that discovery path, without leaking admin-only trading
# controls into a menu paying subscribers also see).
_ADMIN_COMMANDS = [
    BotCommand("vwap_executor_status", "VWAP executor: статус + кнопки керування"),
    BotCommand("vwap_executor_on", "VWAP executor: увімкнути"),
    BotCommand("vwap_executor_off", "VWAP executor: вимкнути (emergency stop)"),
    BotCommand("vwap_executor_readonly", "VWAP executor: read-only on|off"),
]


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
    dp.add_handler(CommandHandler("winrate", telegram_ui.winrate_command))
    dp.add_handler(CommandHandler("autotrade_status", telegram_ui.autotrade_status_command))
    dp.add_handler(CommandHandler("autotrade_on", telegram_ui.autotrade_on_command))
    dp.add_handler(CommandHandler("autotrade_off", telegram_ui.autotrade_off_command))
    dp.add_handler(CommandHandler("binomo_status", telegram_ui.binomo_status_command))
    dp.add_handler(CommandHandler("binomo_on", telegram_ui.binomo_on_command))
    dp.add_handler(CommandHandler("binomo_off", telegram_ui.binomo_off_command))
    dp.add_handler(CommandHandler("vwap_executor_status", telegram_ui.vwap_executor_status_command))
    dp.add_handler(CommandHandler("vwap_executor_on", telegram_ui.vwap_executor_on_command))
    dp.add_handler(CommandHandler("vwap_executor_off", telegram_ui.vwap_executor_off_command))
    dp.add_handler(CommandHandler("vwap_executor_readonly", telegram_ui.vwap_executor_readonly_command))
    dp.add_handler(CommandHandler("live", telegram_ui.live_command))
    dp.add_handler(CommandHandler("language", telegram_ui.language_command))
    dp.add_handler(CommandHandler("lang", telegram_ui.language_command))
    dp.add_handler(CommandHandler(["uk", "en", "es", "de", "ru"], telegram_ui.set_language_command))

    dp.add_handler(MessageHandler(Filters.regex(r"^(МЕНЮ|МЕНЮ|MENÚ|MENÜ|MENU|[Mm][Ee][Nn][Uu])$"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))


def _register_admin_command_menu(updater: Updater) -> None:
    """Best-effort: a failure here must never take down the rest of the
    bot, since every one of these commands still works fine typed by hand
    regardless of whether the menu registration succeeded."""
    if not DEV_USER_ID:
        return
    try:
        updater.bot.set_my_commands(commands=_ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=DEV_USER_ID))
        logger.info("Адмінське меню команд Telegram зареєстровано (chat_id=%s)", DEV_USER_ID)
    except Exception:
        logger.exception("Не вдалося зареєструвати адмінське меню команд Telegram")


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
            _register_admin_command_menu(updater)

            app_state.updater = updater
            _start_polling_thread(updater)

            logger.info("Telegram bot запущено. Команди: /start /symbols /stats /winrate /live")
            return updater

        except ConfigError:
            raise
        except Exception as e:
            logger.exception("Не вдалося запустити Telegram bot")
            notify_bot_failed(str(e))
            raise TelegramError(f"Не вдалося запустити: {e}", recoverable=False) from e
