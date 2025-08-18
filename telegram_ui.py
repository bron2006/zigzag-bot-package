import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from main import client, symbol_cache

logger = logging.getLogger(__name__)

# Кнопки
def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="EURUSD")],
        [InlineKeyboardButton("GBP/USD", callback_data="GBPUSD")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Вибери валютну пару:", reply_markup=reply_markup)


def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()

    # 🛠️ Виправлення тут: isConnected тепер без дужок
    if not client or not client.isConnected:
        query.edit_message_text(text="❌ Немає підключення до cTrader API")
        return

    symbol = query.data
    if symbol not in symbol_cache:
        query.edit_message_text(text=f"⚠️ Символ {symbol} ще не завантажений")
        return

    query.edit_message_text(text=f"✅ Обрано {symbol}")
