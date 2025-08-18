import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

# Імпортуємо залежності з файлу спільного стану
from state import client, symbol_cache

logger = logging.getLogger(__name__)


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Повертає основну клавіатуру з валютними парами."""
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="EURUSD")],
        [InlineKeyboardButton("GBP/USD", callback_data="GBPUSD")],
    ]
    return InlineKeyboardMarkup(keyboard)


def start(update: Update, context: CallbackContext) -> None:
    """
    Обробляє команду /start.
    Перевіряє стан підключення перед тим, як надіслати клавіатуру.
    """
    # Перевіряємо, чи клієнт підключений
    if client and client.isConnected:
        update.message.reply_text(
            "✅ З'єднання встановлено. Виберіть валютну пару:",
            reply_markup=get_main_keyboard()
        )
    else:
        # Якщо з'єднання ще встановлюється, пропонуємо зачекати і оновити
        keyboard = [
            [InlineKeyboardButton("🔄 Оновити статус", callback_data="refresh_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            "⏳ Встановлюю з'єднання з сервером cTrader... Будь ласка, зачекайте кілька секунд і натисніть 'Оновити'.",
            reply_markup=reply_markup
        )


def button_handler(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на всі inline-кнопки."""
    query = update.callback_query
    query.answer()
    
    button_data = query.data

    # Нова логіка для кнопки оновлення
    if button_data == "refresh_status":
        if client and client.isConnected:
            query.edit_message_text(
                text="✅ З'єднання встановлено. Виберіть валютну пару:",
                reply_markup=get_main_keyboard()
            )
        else:
            # Якщо все ще не підключено, просто повідомляємо користувача
            query.answer(text="⏳ З'єднання ще встановлюється... Спробуйте за мить.", show_alert=True)
        return

    # Стара логіка для кнопок символів
    if not client or not client.isConnected:
        query.answer(text="❌ З'єднання з cTrader API ще не встановлено. Спробуйте оновити статус.", show_alert=True)
        return

    symbol = button_data
    if symbol not in symbol_cache:
        logger.warning(f"Символ '{symbol}' не знайдено в кеші. Розмір кешу: {len(symbol_cache)}.")
        query.edit_message_text(text=f"⚠️ Символ {symbol} не знайдено. Можливо, кеш ще завантажується.")
        return

    query.edit_message_text(text=f"✅ Обрано {symbol}. Дані завантажуються...")
    # Тут буде ваша майбутня логіка для показу аналітики по символу