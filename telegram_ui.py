import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
from config import FOREX_SESSIONS

logger = logging.getLogger(__name__)

# --- КЛАВІАТУРИ ---
def get_main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="menu_forex")],
    ])

def get_forex_sessions_kb() -> InlineKeyboardMarkup:
    keyboard = []
    for session in FOREX_SESSIONS:
        keyboard.append([InlineKeyboardButton(f"--- {session} сесія ---", callback_data=f"session_{session}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад до меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_pairs_kb(session: str) -> InlineKeyboardMarkup:
    pairs = FOREX_SESSIONS.get(session, [])
    keyboard = []
    row = []
    for pair in pairs:
        row.append(InlineKeyboardButton(pair, callback_data=pair.replace("/", "")))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад до сесій", callback_data="menu_forex")])
    return InlineKeyboardMarkup(keyboard)

# --- ОБРОБНИКИ ---
def start(update: Update, context: CallbackContext) -> None:
    """Обробляє команду /start і створює головну клавіатуру."""
    keyboard = [["МЕНЮ"]]
    # --- ВИПРАВЛЕННЯ: Додаємо one_time_keyboard=False, щоб клавіатура була постійною ---
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text(
        "👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.", 
        reply_markup=reply_markup
    )

def reset_ui(update: Update, context: CallbackContext) -> None:
    """При будь-якому текстовому повідомленні, крім 'МЕНЮ', повертає головну клавіатуру."""
    if update.message.text != "МЕНЮ":
        start(update, context)

def menu(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на кнопку 'МЕНЮ'."""
    try:
        context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    except BadRequest:
        pass
    if 'last_menu_id' in context.user_data:
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest:
            pass
    sent_message = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

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
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    if data == "main_menu":
        query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    elif data == "menu_forex":
        query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb())
    elif data.startswith("session_"):
        session_name = data.split("_")[1]
        query.edit_message_text(f"Виберіть пару для сесії '{session_name}':", reply_markup=get_pairs_kb(session_name))
    else:
        symbol = data
        if not state.client or not state.client.isConnected:
            query.answer(text="❌ З'єднання з cTrader API ще не встановлено.", show_alert=True)
            return
        if symbol not in state.symbol_cache:
            query.answer(text=f"⚠️ Символ {symbol} не знайдено.", show_alert=True)
            return
        query.edit_message_text(text=f"⏳ Обрано {symbol}. Отримую дані для аналізу...")
        user_id = query.from_user.id
        chat_id = query.message.chat_id

        def on_success(result):
            message_text = _format_signal_message(result)
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_forex_sessions_kb())
        def on_error(failure):
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {failure.getErrorMessage()}")
            query.edit_message_text(
                text=f"❌ Виникла помилка під час аналізу {symbol}.",
                reply_markup=get_forex_sessions_kb()
            )
        def do_analysis():
            d = get_api_detailed_signal_data(state.client, symbol, user_id)
            d.addCallbacks(on_success, on_error)
        reactor.callFromThread(do_analysis)