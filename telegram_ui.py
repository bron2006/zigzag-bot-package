# telegram_ui.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest
from twisted.internet import reactor

from config import FOREX_SESSIONS, logger
from db import get_watchlist, toggle_watch
from analysis import get_api_detailed_signal_data

# Клавіатури та допоміжні функції залишаються без змін
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Обране", callback_data='menu_watchlist')],
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
    ])

def forex_session_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗾 Азіатська", callback_data="session_Азіатська")],
        [InlineKeyboardButton("🏦 Європейська", callback_data="session_Європейська")],
        [InlineKeyboardButton("💵 Американська", callback_data="session_Американська")],
        [InlineKeyboardButton("⬅️ НАЗАД", callback_data="main_menu")]
    ])

def asset_list_kb(pairs):
    keyboard = []
    for pair_name in pairs:
        # Важливо: callback_data тепер має префікс, щоб уникнути плутанини
        callback_data = f'analyze_{pair_name}'
        keyboard.append([InlineKeyboardButton(pair_name, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data='menu_forex')])
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text("👋 Вітаю! Я бот для технічного аналізу ринків.", reply_markup=reply_markup)

def menu_command(update: Update, context: CallbackContext):
    update.message.reply_text("🏠 Головне меню:", reply_markup=main_kb())

# --- ЗМІНЕНО: Повністю переписано з урахуванням рекомендацій експерта ---
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    
    client = context.bot_data.get('ctrader_client')

    if data == 'main_menu':
        query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())
    elif data == 'menu_forex':
        query.edit_message_text("💹 Виберіть сесію:", reply_markup=forex_session_kb())
    elif data.startswith('session_'):
        session = data.split('_')[1]
        pairs = FOREX_SESSIONS.get(session, [])
        query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb(pairs))

    elif data.startswith('analyze_'):
        # 1. Правильний парсинг назви пари
        ticker = data[len("analyze_"):]
        user_id = query.from_user.id

        # 2. Правильна перевірка статусу клієнта (використовуємо метод isConnected())
        if not client or not client.isConnected():
            query.edit_message_text("❌ Сервіс cTrader ще не готовий. Зачекайте хвилину.")
            return
            
        query.edit_message_text(f"⏳ Аналізую {ticker}...")

        def on_analysis_done(analysis_data):
            reactor.callFromThread(_send_analysis_result, context, query, analysis_data, ticker)

        # 3. Надійна обробка помилок
        def on_analysis_error(failure):
            logger.error(f"Analysis failed for {ticker}: {failure}")
            error_data = {"error": str(failure.value) if failure else "Невідома помилка аналізу"}
            reactor.callFromThread(_send_analysis_result, context, query, error_data, ticker)

        # Виклик залишається тим самим, але тепер він обробляється коректно
        d = get_api_detailed_signal_data(client, ticker, user_id=user_id)
        d.addCallbacks(on_analysis_done, on_analysis_error)

def _send_analysis_result(context, query, analysis_data, ticker):
    if "error" in analysis_data:
        msg = f"❌ Помилка для {ticker}: {analysis_data['error']}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ НАЗАД", callback_data='menu_forex')]])
        try:
            query.edit_message_text(text=msg, reply_markup=kb)
        except BadRequest: pass
        return

    price = analysis_data.get('price', 0)
    verdict_text = analysis_data.get('verdict_text', 'Н/Д')
    msg = f"*{ticker}* | Ціна: `{price:.5f}`\n\n{verdict_text}"
    
    # Можна додати більше кнопок, якщо потрібно
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ НАЗАД", callback_data='menu_forex')]])
    try:
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)
    except BadRequest: pass

def register_handlers(dispatcher, client):
    dispatcher.bot_data['ctrader_client'] = client
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))