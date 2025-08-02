# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest

# Тепер імпортуємо лише константи
from config import CRYPTO_PAIRS_FULL, CRYPTO_CHUNK_SIZE, STOCK_TICKERS, FOREX_SESSIONS
from db import get_watchlist, toggle_watch
from analysis import get_signal_strength_verdict, get_full_mta_verdict

# Глобальні змінні, які будуть ініціалізовані в bot.py
bot = None
dp = None

def register_handlers(dispatcher):
    """Реєструє всі обробники команд та кнопок."""
    global dp, bot
    dp = dispatcher
    bot = dp.bot

    # Реєстрація всіх ваших обробників
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(MessageHandler(Filters.regex(r'^МЕНЮ$'), menu))
    dp.add_handler(CallbackQueryHandler(button_handler))

# ... (весь ваш код для analysis_worker, клавіатур та обробників залишається тут, без змін) ...