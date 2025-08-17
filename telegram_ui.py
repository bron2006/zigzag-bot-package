# telegram_ui.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest
from twisted.internet import reactor

from config import FOREX_SESSIONS, logger
from db import get_watchlist, toggle_watch
from analysis import get_api_detailed_signal_data

# Клавіатури та допоміжні функції залишаються без змін
def _get_back_callback(asset, display, chunk_index):
    return 'main_menu'

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Обране", callback_data='menu_watchlist')],
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
    ])

# --- ЗМІНЕНО: Обробники повернено до синхронного стилю (без async/await) ---
def start(update: Update, context: CallbackContext):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text("👋 Вітаю! Я бот для технічного аналізу ринків. Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

def menu_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    sent_message = context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id
    
    client = context.bot_data.get('ctrader_client')
    if not client or not client.isConnected:
        query.edit_message_text("❌ Сервіс cTrader ще не готовий. Зачекайте хвилину.")
        return

    if data.startswith(('analyze_', 'refresh_')):
        parts = data.split('_')
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id

        query.edit_message_text(f"⏳ Аналізую {display}...")

        def on_analysis_done(analysis_data):
            reactor.callFromThread(_send_analysis_result, context, query, analysis_data, ticker, display)

        def on_analysis_error(failure):
            logger.error(f"Analysis failed: {failure.getErrorMessage()}")
            error_data = {"error": str(failure.value)}
            reactor.callFromThread(_send_analysis_result, context, query, error_data, ticker, display)

        d = get_api_detailed_signal_data(client, ticker, user_id=user_id)
        d.addCallbacks(on_analysis_done, on_analysis_error)
    
    elif data == 'main_menu':
        query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())

def _send_analysis_result(context, query, analysis_data, ticker, display):
    if "error" in analysis_data:
        msg = f"❌ Помилка для {display}: {analysis_data['error']}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до списку", callback_data='main_menu')]])
        try:
            query.edit_message_text(text=msg, reply_markup=kb)
        except BadRequest: pass
        return

    price = analysis_data.get('price', 0)
    verdict_text = analysis_data.get('verdict_text', 'Н/Д')
    msg = f"*{display}* | Ціна: `{price:.5f}`\n\n{verdict_text}"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до списку", callback_data='main_menu')]])
    try:
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)
    except BadRequest: pass

def register_handlers(dispatcher, client):
    dispatcher.bot_data['ctrader_client'] = client
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))