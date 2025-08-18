# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from twisted.internet import reactor

from state import client, symbol_cache
from config import FOREX_SESSIONS
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Створює динамічну клавіатуру на основі торгових сесій."""
    keyboard = []
    
    for session_name, pairs in FOREX_SESSIONS.items():
        pair_buttons = [
            InlineKeyboardButton(pair, callback_data=pair.replace("/", ""))
            for pair in pairs
        ]
        keyboard.append([InlineKeyboardButton(f"--- {session_name} сесія ---", callback_data="ignore")])
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

def _format_signal_message(result: dict) -> str:
    """Форматує результат аналізу у повідомлення для користувача."""
    if result.get("error"):
        return f"❌ Помилка аналізу: {result['error']}"

    # Використовуємо .get() з fallback-значеннями для безпеки
    pair = result.get('pair', 'N/A')
    price = result.get('price', 0)
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    support = result.get('support')
    resistance = result.get('resistance')
    reasons = result.get('reasons', [])

    price_str = f"{price:.5f}" if price else "N/A"

    message = f"📈 **Аналіз для {pair}**\n\n"
    message += f"**Сигнал:** {verdict}\n"
    message += f"**Поточна ціна:** `{price_str}`\n\n"

    if support or resistance:
        message += "🔑 **Ключові рівні:**\n"
        if support:
            message += f"   - Підтримка: `{support:.5f}`\n"
        if resistance:
            message += f"   - Опір: `{resistance:.5f}`\n"
        message += "\n"

    if reasons:
        message += "📑 **Фактори аналізу:**\n"
        for reason in reasons:
            message += f"   - {reason}\n"
            
    return message


def button_handler(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на всі inline-кнопки."""
    query = update.callback_query
    button_data = query.data if query else None
    
    logger.info(f"🔔 Отримано CallbackQuery: '{button_data}' від користувача {query.from_user.id}")
    
    if query:
        query.answer()
    
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

    query.edit_message_text(text=f"⏳ Обрано {symbol}. Отримую дані для аналізу...")
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # --- ПОЧАТОК НОВОЇ ЛОГІКИ ---

    def on_success(result):
        """Колбек, який виконується при успішному отриманні сигналу."""
        logger.info(f"✅ Сигнал для {symbol} успішно отримано. Результат: {result}")
        message_text = _format_signal_message(result)
        context.bot.send_message(chat_id=chat_id, text=message_text, parse_mode='Markdown')

    def on_error(failure):
        """Колбек для обробки помилок."""
        logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {failure.getErrorMessage()}")
        context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Виникла помилка під час аналізу {symbol}. Будь ласка, спробуйте пізніше."
        )

    def do_analysis():
        """Функція, що запускає асинхронний аналіз."""
        # Викликаємо функцію з analysis.py, яка повертає Deferred
        d = get_api_detailed_signal_data(client, symbol, user_id)
        # Додаємо колбеки для обробки результату
        d.addCallbacks(on_success, on_error)

    # Безпечно викликаємо функцію `do_analysis` з потоку TG-бота в головному потоці Twisted
    reactor.callFromThread(do_analysis)
    # --- КІНЕЦЬ НОВОЇ ЛОГІКИ ---