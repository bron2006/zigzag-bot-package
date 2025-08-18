import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from state import client, symbol_cache
# Імпортуємо наші списки валютних пар
from config import FOREX_SESSIONS

logger = logging.getLogger(__name__)

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Створює динамічну клавіатуру на основі торгових сесій."""
    keyboard = []
    
    # Проходимо по кожній сесії та її парам
    for session_name, pairs in FOREX_SESSIONS.items():
        # Створюємо кнопки для кожної пари в сесії
        pair_buttons = [
            # Текст кнопки: "EUR/USD", дані для колбеку: "EURUSD"
            InlineKeyboardButton(pair, callback_data=pair.replace("/", ""))
            for pair in pairs
        ]
        # Додаємо заголовок сесії
        keyboard.append([InlineKeyboardButton(f"--- {session_name} сесія ---", callback_data="ignore")])
        # Розбиваємо кнопки по 3 в ряд для кращого вигляду
        for i in range(0, len(pair_buttons), 3):
            keyboard.append(pair_buttons[i:i+3])
            
    return InlineKeyboardMarkup(keyboard)


def start(update: Update, context: CallbackContext) -> None:
    """Обробляє команду /start."""
    if client and client.isConnected:
        update.message.reply_text(
            "✅ З'єднання встановлено. Виберіть валютну пару:",
            reply_markup=get_main_keyboard()
        )
    else:
        keyboard = [
            [InlineKeyboardButton("🔄 Оновити статус", callback_data="refresh_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            "⏳ Встановлюю з'єднання з сервером cTrader... Натисніть 'Оновити' за кілька секунд.",
            reply_markup=reply_markup
        )


def button_handler(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на всі inline-кнопки."""
    query = update.callback_query
    button_data = query.data if query else None
    
    logger.info(f"🔔 Отримано CallbackQuery: '{button_data}' від користувача {query.from_user.id}")
    
    if query:
        query.answer()
    
    # Ігноруємо натискання на заголовки сесій
    if button_data == "ignore":
        return

    if button_data == "refresh_status":
        if client and client.isConnected:
            query.edit_message_text(
                text="✅ З'єднання встановлено. Виберіть валютну пару:",
                reply_markup=get_main_keyboard()
            )
        else:
            query.answer(text="⏳ З'єднання ще встановлюється... Спробуйте за мить.", show_alert=True)
        return

    if not client or not client.isConnected:
        query.answer(text="❌ З'єднання з cTrader API ще не встановлено. Спробуйте оновити статус.", show_alert=True)
        return

    symbol = button_data
    if symbol not in symbol_cache:
        logger.warning(f"Символ '{symbol}' не знайдено в кеші. Розмір кешу: {len(symbol_cache)}.")
        query.edit_message_text(text=f"⚠️ Символ {symbol} не знайдено. Можливо, він не торгується у вашого брокера.")
        return

    # Якщо все добре, показуємо, що починаємо роботу
    query.edit_message_text(text=f"✅ Обрано {symbol}. Отримую дані для аналізу...")
    
    # В майбутньому тут буде виклик функції з analysis.py для отримання сигналу
    # наприклад: context.bot.send_message(chat_id=query.message.chat_id, text="Результат аналізу...")