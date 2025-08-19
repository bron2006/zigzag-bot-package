import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from twisted.internet import reactor

import state
from config import FOREX_SESSIONS
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Створює клавіатуру з валютними парами."""
    keyboard = []
    all_pairs = []
    for pairs in FOREX_SESSIONS.values():
        all_pairs.extend(pairs)
    
    row = []
    for pair in all_pairs:
        row.append(InlineKeyboardButton(pair, callback_data=pair.replace("/", "")))
        if len(row) >= 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
            
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext) -> None:
    """Обробляє команду /start."""
    if state.client and state.client.isConnected:
        update.message.reply_text(
            "✅ З'єднання встановлено. Виберіть валютну пару:",
            reply_markup=get_main_keyboard()
        )
    else:
        keyboard = [[InlineKeyboardButton("🔄 Оновити статус", callback_data="refresh_status")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            "⏳ Встановлюю з'єднання з сервером cTrader... Натисніть 'Оновити' за кілька секунд.",
            reply_markup=reply_markup
        )

def _format_signal_message(result: dict) -> str:
    if result.get("error"):
        return f"❌ Помилка аналізу: {result['error']}"
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
    query = update.callback_query
    query.answer()
    symbol = query.data

    if symbol == "refresh_status":
        if state.client and state.client.isConnected:
            query.edit_message_text(
                text="✅ З'єднання встановлено. Виберіть валютну пару:",
                reply_markup=get_main_keyboard()
            )
        else:
            query.answer(text="⏳ З'єднання ще встановлюється...", show_alert=True)
        return

    query.edit_message_text(text=f"⏳ Обрано {symbol}. Отримую дані для аналізу...")
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    def on_success(result):
        message_text = _format_signal_message(result)
        context.bot.send_message(chat_id=chat_id, text=message_text, parse_mode='Markdown')
        # Після аналізу знову показуємо головне меню
        context.bot.send_message(chat_id=chat_id, text="Виберіть наступну пару:", reply_markup=get_main_keyboard())

    def on_error(failure):
        logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {failure.getErrorMessage()}")
        context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Виникла помилка під час аналізу {symbol}. Спробуйте ще раз.",
            reply_markup=get_main_keyboard()
        )

    def do_analysis():
        d = get_api_detailed_signal_data(state.client, symbol, user_id)
        d.addCallbacks(on_success, on_error)

    reactor.callFromThread(do_analysis)