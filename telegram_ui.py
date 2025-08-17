import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from config import CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCKS_US_SYMBOLS
from db import get_watchlist, toggle_watch
# Ми використовуємо analysis функції тільки для веб — поки залишимо бот навігаційним
# Якщо потрібно — інтегруємо Twisted Deferred -> asyncio у наступному кроці.

# --- АДАПТЕРИ: перетворюють дані на текст для бота (тимчасово мінімальні) ---
async def get_signal_strength_verdict(ticker, display, asset, user_id=None, force_refresh=False):
    # Тимчасово відповідаємо, що аналіз виконується через API (бо analysis повертає Twisted Deferred)
    return f"⏳ Аналіз для {display} виконується на сервері. Спробуйте через кілька секунд.", None

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Обране", callback_data='menu_watchlist')],
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data='menu_crypto')],
        [InlineKeyboardButton("🏢 Акції США", callback_data='menu_stocks')]
    ])

def forex_session_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗾 Азіатська", callback_data="session_Азіатська")],
        [InlineKeyboardButton("🏦 Європейська", callback_data="session_Європейська")],
        [InlineKeyboardButton("💵 Американська", callback_data="session_Американська")],
        [InlineKeyboardButton("⬅️ НАЗАД", callback_data="main_menu")]
    ])

def asset_list_kb(asset_type, pairs, chunk_index=0):
    keyboard = []
    subset_pairs = pairs if asset_type != 'crypto' else pairs[chunk_index:chunk_index+10]
    for pair_name in subset_pairs:
        ticker = pair_name
        callback_data = f'analyze_{asset_type}_{ticker.replace("/", "~")}_{pair_name.replace("/", "~")}_{chunk_index}'
        keyboard.append([InlineKeyboardButton(pair_name, callback_data=callback_data)])
    back_map = {
        'forex': 'menu_forex',
        'crypto': 'menu_crypto',
        'stocks': 'menu_stocks',
        'watchlist': 'main_menu'
    }
    keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data=back_map.get(asset_type, 'main_menu'))])
    return InlineKeyboardMarkup(keyboard)

# --- Async handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("👋 Вітаю! Я бот для технічного аналізу ринків. Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    sent_message = await context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'main_menu':
        await query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())
        return

    if data == 'menu_forex':
        await query.edit_message_text("💹 Виберіть сесію:", reply_markup=forex_session_kb())
        return

    if data.startswith('session_'):
        session = data.split('_', 1)[1]
        pairs = FOREX_SESSIONS.get(session, [])
        await query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb('forex', pairs))
        return

    if data == 'menu_watchlist':
        user_id = query.from_user.id
        watchlist = get_watchlist(user_id)
        if watchlist:
            await query.edit_message_text("⭐ Обрані пари:", reply_markup=asset_list_kb('watchlist', watchlist))
        else:
            await query.answer("Ваш список обраного порожній.", show_alert=True)
        return

    if data.startswith(('analyze_', 'refresh_')):
        parts = data.split('_')
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        chunk_index = int(parts[4]) if len(parts) > 4 else 0
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id

        await query.edit_message_text(f"⏳ {'Примусово оновлюю' if data.startswith('refresh_') else 'Аналізую'} {display}...")
        msg, analysis_data = await get_signal_strength_verdict(ticker, display, asset, user_id=user_id)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до списку", callback_data='main_menu')]])
        await query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)

def register_handlers(application):
    # application — це telegram.ext.Application (v20)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^МЕНЮ$"), menu_command))
    application.add_handler(CallbackQueryHandler(button_handler))
