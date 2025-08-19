import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
from telegram.error import BadRequest
from twisted.internet import reactor

import state
from config import FOREX_SESSIONS
from analysis import get_api_detailed_signal_data

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
    keyboard, row = [], []
    for pair in pairs:
        row.append(InlineKeyboardButton(pair, callback_data=pair.replace("/", "")))
        if len(row) == 3:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад до сесій", callback_data="menu_forex")])
    return InlineKeyboardMarkup(keyboard)

# --- ОБРОБНИКИ ---
def start(update: Update, context: CallbackContext) -> None:
    """Постійна кнопка 'МЕНЮ'"""
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.", reply_markup=reply_markup)

def reset_ui(update: Update, context: CallbackContext) -> None:
    if getattr(update, "message", None) and update.message.text != "МЕНЮ":
        start(update, context)

def menu(update: Update, context: CallbackContext) -> None:
    try:
        context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    except BadRequest:
        pass
    if 'last_menu_id' in context.user_data:
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest:
            pass
    sent = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    context.user_data['last_menu_id'] = sent.message_id

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
    msg = f"📈 **Аналіз для {pair}**\n\n"
    msg += f"**Сигнал:** {verdict}\n"
    msg += f"**Поточна ціна:** `{price_str}`\n\n"
    if support or resistance:
        msg += "🔑 **Ключові рівні:**\n"
        if support: msg += f"   - Підтримка: `{support:.5f}`\n"
        if resistance: msg += f"   - Опір: `{resistance:.5f}`\n"
        msg += "\n"
    if reasons:
        msg += "📑 **Фактори аналізу:**\n"
        for r in reasons:
            msg += f"   - {r}\n"
    return msg

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    if data == "main_menu":
        query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
        return
    if data == "menu_forex":
        query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb())
        return
    if data.startswith("session_"):
        session_name = data.split("_", 1)[1]
        query.edit_message_text(f"Виберіть пару для сесії '{session_name}':", reply_markup=get_pairs_kb(session_name))
        return

    # символ
    symbol = data
    if not state.client or not getattr(state.client, "isConnected", False):
        query.answer(text="❌ З'єднання з cTrader API ще не встановлено.", show_alert=True); return
    if symbol not in state.symbol_cache:
        query.answer(text=f"⚠️ Символ {symbol} не знайдено.", show_alert=True); return

    query.edit_message_text(text=f"⏳ Обрано {symbol}. Отримую дані для аналізу...")
    user_id = query.from_user.id

    def on_success(result):
        try:
            txt = _format_signal_message(result)
            query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=get_forex_sessions_kb())
        except Exception:
            logger.exception("Помилка при відправці результату")
            query.edit_message_text(text=f"❌ Помилка при обробці результату для {symbol}.", reply_markup=get_forex_sessions_kb())

    def on_error(failure):
        try:
            err = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        except Exception:
            err = str(failure)
        logger.error(f"Помилка при отриманні сигналу для {symbol}: {err}")
        query.edit_message_text(text=f"❌ Виникла помилка під час аналізу {symbol}.", reply_markup=get_forex_sessions_kb())

    def do_analysis():
        d = get_api_detailed_signal_data(state.client, symbol, user_id)
        d.addCallbacks(on_success, on_error)

    reactor.callFromThread(do_analysis)
