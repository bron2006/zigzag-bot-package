# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest
from twisted.internet import reactor, defer

from config import FOREX_SESSIONS, logger
from db import get_watchlist, toggle_watch
from analysis import get_api_detailed_signal_data

# Helper functions like _get_back_callback, main_kb, etc., remain the same

def _get_back_callback(asset, display, chunk_index):
    # This logic remains unchanged
    return 'main_menu'

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Обране", callback_data='menu_watchlist')],
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data='menu_crypto')],
        [InlineKeyboardButton("🏢 Акції США", callback_data='menu_stocks')]
    ])

# Other keyboard functions remain the same...

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("👋 Вітаю! Я бот для технічного аналізу ринків. Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Logic remains similar, but now async
    chat_id = update.message.chat_id
    sent_message = await context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id
    
    # --- ЗМІНЕНО: Отримання client з application.bot_data ---
    client = context.application.bot_data.get('ctrader_client')
    if not client or not client.isConnected:
        await query.edit_message_text("❌ Сервіс cTrader ще не готовий. Зачекайте хвилину.")
        return

    if data.startswith(('analyze_', 'refresh_')):
        parts = data.split('_')
        # ... (parsing logic is the same)
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id

        await query.edit_message_text(f"⏳ Аналізую {display}...")

        # --- ЗМІНЕНО: Використання Deferred з Twisted у асинхронній функції ---
        def on_analysis_done(analysis_data):
            # We need to call the async function from Twisted's thread
            reactor.callFromThread(async_send_analysis_result, context, query, analysis_data, ticker_safe, display, asset, 0, user_id)

        def on_analysis_error(failure):
            logger.error(f"Analysis failed: {failure.getErrorMessage()}")
            error_data = {"error": str(failure.value)}
            reactor.callFromThread(async_send_analysis_result, context, query, error_data, ticker_safe, display, asset, 0, user_id)

        d = get_api_detailed_signal_data(client, ticker, user_id=user_id)
        d.addCallbacks(on_analysis_done, on_analysis_error)
    
    # Other button logic remains similar...
    elif data == 'main_menu':
        await query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())


# --- ЗМІНЕНО: Функція відправки результату тепер асинхронна ---
async def async_send_analysis_result(context, query, analysis_data, ticker_safe, display, asset, chunk_index, user_id):
    if "error" in analysis_data:
        msg = f"❌ Помилка для {display}: {analysis_data['error']}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до списку", callback_data=_get_back_callback(asset, display, chunk_index))]])
        try:
            await query.edit_message_text(text=msg, reply_markup=kb)
        except BadRequest: pass
        return

    context.user_data[f"analysis_{ticker_safe}"] = analysis_data
    price = analysis_data.get('price', 0)
    verdict_text = analysis_data.get('verdict_text', 'Н/Д')
    msg = f"*{display}* | Ціна: `{price:.5f}`\n\n{verdict_text}"
    # ... (rest of the message building logic)
    
    kb = InlineKeyboardMarkup([
        # ... (keyboard building logic)
        [InlineKeyboardButton("⬅️ Назад до списку", callback_data='main_menu')]
    ])
    try:
        await query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)
    except BadRequest: pass

# --- ЗМІНЕНО: Реєстрація хендлерів для PTB v21 ---
def register_handlers(application: Application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^МЕНЮ$"), menu_command))
    application.add_handler(CallbackQueryHandler(button_handler))