import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

# ВИПРАВЛЕНО: Імпортуємо залежності з нового файлу спільного стану.
from state import client, symbol_cache

logger = logging.getLogger(__name__)


def start(update: Update, context: CallbackContext) -> None:
    """Надсилає стартове повідомлення з кнопками вибору."""
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="EURUSD")],
        [InlineKeyboardButton("GBP/USD", callback_data="GBPUSD")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Вибери валютну пару:", reply_markup=reply_markup)


def button_handler(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на inline-кнопки."""
    query = update.callback_query
    query.answer()

    if not client or not client.isConnected:
        query.edit_message_text(text="❌ Немає підключення до cTrader API. Запуск...")
        return

    symbol = query.data
    if symbol not in symbol_cache:
        logger.warning(f"Символ '{symbol}' не знайдено в кеші. Розмір кешу: {len(symbol_cache)}.")
        query.edit_message_text(text=f"⚠️ Символ {symbol} ще не завантажений. Будь ласка, зачекайте кілька секунд та спробуйте ще раз.")
        return

    query.edit_message_text(text=f"✅ Обрано {symbol}")