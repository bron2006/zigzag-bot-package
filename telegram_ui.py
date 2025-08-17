# telegram_ui.py
import math
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler
from telegram.ext import filters

from config import CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCKS_US_SYMBOLS

# Простий http client, бот робить запити до локального веб-сервісу:
LOCAL_API_BASE = "http://127.0.0.1:8080"

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
    subset_pairs = pairs
    if asset_type == 'crypto':
        start = chunk_index
        end = min(start + 10, len(pairs))
        subset_pairs = pairs[start:end]

    for pair_name in subset_pairs:
        cb = f'analyze_{asset_type}_{pair_name.replace("/", "~")}_{pair_name.replace("/", "~")}_{chunk_index}'
        keyboard.append([InlineKeyboardButton(pair_name, callback_data=cb)])
    back_map = {'forex': 'menu_forex', 'crypto': 'menu_crypto', 'stocks': 'menu_stocks', 'watchlist': 'main_menu'}
    keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data=back_map.get(asset_type, 'main_menu'))])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("👋 Вітаю! Я бот для технічного аналізу ринків. Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    # не видаляємо попередні повідомлення — просто показуємо меню
    await context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())

async def fetch_json(path, params=None):
    # блокуючий HTTP — запускати в executor
    def _req():
        r = requests.get(f"{LOCAL_API_BASE}{path}", params=params or {}, timeout=20)
        r.raise_for_status()
        return r.json()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _req)

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

    if data == 'menu_crypto':
        if not CRYPTO_PAIRS_FULL:
            await query.answer("Криптовалюти тимчасово недоступні.", show_alert=True)
            return
        # показуємо перші 10
        await query.edit_message_text("💎 Виберіть криптовалюту:", reply_markup=asset_list_kb('crypto', CRYPTO_PAIRS_FULL, 0))
        return

    if data.startswith('session_'):
        session = data.split('_', 1)[1]
        pairs = FOREX_SESSIONS.get(session, [])
        await query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb('forex', pairs))
        return

    if data.startswith('analyze_') or data.startswith('refresh_'):
        is_refresh = data.startswith('refresh_')
        parts = data.split('_')
        asset = parts[1]
        ticker_safe = parts[2]
        ticker = ticker_safe.replace('~', '/')
        await query.edit_message_text(f"⏳ {'Оновлення' if is_refresh else 'Аналіз'} {ticker}...")
        try:
            # використовуємо локальний веб-ендпоінт /api/signal
            resp = await fetch_json("/api/signal", params={"pair": ticker})
            if isinstance(resp, dict) and resp.get("error"):
                await query.edit_message_text(f"❌ Помилка: {resp.get('error')}")
                return
            # очікуємо, що resp містить "verdict_text" та "price"
            price = resp.get("price")
            verdict = resp.get("verdict_text") or str(resp)
            text = f"*{ticker}* | Ціна: `{price:.5f}`\n\n{verdict}" if price else f"*{ticker}*\n\n{verdict}"
            # прості кнопки: оновити, MTA, назад
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Оновити", callback_data=f'refresh_{asset}_{ticker_safe}_{ticker_safe}_0')],
                [InlineKeyboardButton("📊 MTA", callback_data=f'fullmta_{asset}_{ticker_safe}_{ticker_safe}_0')],
                [InlineKeyboardButton("⬅️ Назад", callback_data='menu_forex' if asset=='forex' else 'main_menu')]
            ])
            await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=kb)
        except Exception as e:
            await query.edit_message_text(f"Помилка при отриманні даних: {e}")
        return

    if data.startswith('fullmta_'):
        parts = data.split('_')
        asset = parts[1]
        ticker_safe = parts[2]
        ticker = ticker_safe.replace('~', '/')
        await query.edit_message_text(f"⏳ Збираю MTF для {ticker}...")
        try:
            resp = await fetch_json("/api/get_mta", params={"pair": ticker})
            if not resp:
                await query.edit_message_text("Немає даних MTA.")
                return
            rows = []
            for it in resp:
                rows.append(f"`{it.get('tf','')}`: {it.get('signal','N/A')}")
            await query.edit_message_text("*MTA:*\n" + "\n".join(rows), parse_mode='Markdown',
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='main_menu')]]))
        except Exception as e:
            await query.edit_message_text(f"Помилка MTA: {e}")
        return

async def register_handlers(application):
    # PTB v20: use add_handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text("МЕНЮ"), menu_command))
    application.add_handler(CallbackQueryHandler(button_handler))
