# bot.py
import logging
from twisted.internet import reactor
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, 
    Filters, CallbackQueryHandler, PicklePersistence
)
import os 
from state import app_state
import telegram_ui
from config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger("bot")

def start_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram disabled")
        return
    try:
        # --- КРИТИЧНО: Вмикаємо Persistence ---
        persistence_path = os.path.join('/data', 'bot_persistence.pkl')
        logger.info(f"Using persistence file at: {persistence_path}")
        persistence = PicklePersistence(filename=persistence_path)
        
        updater = Updater(
            token=TELEGRAM_BOT_TOKEN, 
            use_context=True, 
            persistence=persistence
        )
        # --- КІНЕЦЬ ---
        
        app_state.updater = updater 
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
        dp.add_handler(MessageHandler(Filters.regex('^МЕНЮ$'), telegram_ui.menu)) 
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        reactor.callInThread(updater.start_polling)
        logger.info("Telegram bot started (polling in background thread).")
    except Exception:
        logger.exception("Failed to start Telegram bot")