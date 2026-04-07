import logging
import time
from collections import defaultdict
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest
import db
from state import app_state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data
from utils_message_cleanup import bot_track_message, bot_clear_messages

logger = logging.getLogger(__name__)

EXPIRATIONS = ["1m", "5m"]

def _get_chat_id(update: Update) -> int:
    if update.effective_chat: return update.effective_chat.id
    if update.callback_query and update.callback_query.message: return update.callback_query.message.chat_id
    return 0

def _safe_delete(bot, chat_id: int, message_id: int):
    try: bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True)

def get_main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⭐ Мій список (Обране)", callback_data="category_watchlist")],
        [InlineKeyboardButton("💹 Валютні пари (Forex)",  callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти",           callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси",           callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина",                callback_data="category_commodities")],
    ]
    scanner_map = {"watchlist": "⭐ Обране", "forex": "💹 Forex", "crypto": "💎 Crypto", "commodities": "🥇 Сировина"}
    for key, text in scanner_map.items():
        status = "✅" if app_state.get_scanner_state(key) else "❌"
        keyboard.append([InlineKeyboardButton(f"{status} Сканер {text}", callback_data=f"toggle_scanner_{key}")])
    return InlineKeyboardMarkup(keyboard)

def get_expiration_kb(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(exp, callback_data=f"exp_{category}_{exp}") for exp in EXPIRATIONS],
        [InlineKeyboardButton("⬅️ Назад до меню", callback_data="main_menu")]
    ])

def get_assets_kb(asset_list: list, category: str, expiration: str) -> InlineKeyboardMarkup:
    kb, row = [], []
    for asset in asset_list:
        clean_asset = asset.replace('/', '')
        cd = f"analyze_{expiration}_{clean_asset}"
        row.append(InlineKeyboardButton(asset, callback_data=cd))
        if len(row) == 2:
            kb.append(row); row = []
    if row: kb.append(row)
    back_cd = "main_menu" if category == 'watchlist' else f"category_{category}"
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_cd)])
    return InlineKeyboardMarkup(kb)

def _format_signal_message(result: dict, expiration: str) -> str:
    if not isinstance(result, dict) or result.get("error"):
        err = result.get("error") if isinstance(result, dict) else "Помилка аналізу"
        return f"❌ *Помилка:* {err}"
    
    pair = result.get('pair', 'N/A')
    verdict = result.get('verdict_text', 'WAIT')
    price = result.get('price', 0)
    emoji = {"BUY": "📈 BUY", "SELL": "📉 SELL", "NEUTRAL": "⏸ NEUTRAL", "NEWS_WAIT": "📰 NEWS WAIT"}.get(verdict, verdict)
    
    msg = f"🎯 *Сигнал: {pair}* ({expiration})\n*Прогноз:* {emoji}\n*Ціна:* `{price if price else 0:.5f}`\n\n📑 *Аналіз:*"
    for r in result.get('reasons', []): msg += f"\n• _{r}_"
    return msg

def start(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)
    update.message.reply_text("🏠 Вітаю в ZigZag! Використовуйте кнопки:", reply_markup=get_reply_keyboard())
    menu(update, context)

def menu(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)
    bot_clear_messages(context.bot, context.bot_data, chat_id)
    sent = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

def stats_command(update: Update, context: CallbackContext):
    now = time.time()
    lines = [f"📊 *Статистика за 1 год:*"]
    count = 0
    for p, r in app_state.latest_analysis_cache.items():
        if now - r.get("ts", 0) < 3600:
            lines.append(f"• {p}: {r.get('verdict_text')}")
            count += 1
    update.message.reply_text("\n".join(lines) if count > 0 else "Сигналів поки немає.", parse_mode='Markdown')

def live_command(update: Update, context: CallbackContext):
    if not app_state.live_prices:
        update.message.reply_text("💹 Ефір порожній.")
        return
    lines = ["💹 *Ціни:*"]
    for p, d in app_state.live_prices.items():
        age = time.time() - d.get("ts", 0)
        lines.append(f"{'🟢' if age < 30 else '🔴'} `{p}`: {d.get('mid', 0):.5f} ({age:.0f}s)")
    update.message.reply_text("\n".join(lines), parse_mode='Markdown')

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    chat_id = _get_chat_id(update)
    _safe_delete(context.bot, chat_id, query.message.message_id)

    data = query.data or ""
    parts = data.split('_')
    action = parts[0]

    try:
        if action == "toggle" and len(parts) > 2:
            cat = parts[2]
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            if app_state.get_scanner_state(cat):
                from ctrader import start_price_subscriptions
                reactor.callLater(0.5, start_price_subscriptions)
            menu(update, context)

        elif action == "main": menu(update, context)

        elif action == "category":
            cat = parts[1]
            if cat == "watchlist":
                assets = db.get_watchlist(chat_id)
                if not assets:
                    sent = context.bot.send_message(chat_id, "📭 Список порожній.", reply_markup=get_main_menu_kb())
                else:
                    sent = context.bot.send_message(chat_id, "⭐ Обране. Таймфрейм:", reply_markup=get_expiration_kb("watchlist"))
            else:
                sent = context.bot.send_message(chat_id, f"Оберіть експірацію для {cat}:", reply_markup=get_expiration_kb(cat))
            bot_track_message(context.bot_data, chat_id, sent.message_id)

        elif action == "exp":
            _, cat, exp = parts
            if cat == "watchlist":
                kb = get_assets_kb(db.get_watchlist(chat_id), "watchlist", exp)
                sent = context.bot.send_message(chat_id, f"⭐ Обране ({exp}):", reply_markup=kb)
            elif cat == "forex":
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(s, callback_data=f"session_forex_{exp}_{s}")] for s in FOREX_SESSIONS] + [[InlineKeyboardButton("⬅️ Назад", callback_data="category_forex")]])
                sent = context.bot.send_message(chat_id, f"Форекс сесії ({exp}):", reply_markup=kb)
            else:
                asset_map = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}
                kb = get_assets_kb(asset_map.get(cat, []), cat, exp)
                sent = context.bot.send_message(chat_id, f"Активи {cat} ({exp}):", reply_markup=kb)
            bot_track_message(context.bot_data, chat_id, sent.message_id)

        elif action == "session":
            _, _, exp, session = parts
            sent = context.bot.send_message(chat_id, f"Пари {session}:", reply_markup=get_assets_kb(FOREX_SESSIONS.get(session, []), "forex", exp))
            bot_track_message(context.bot_data, chat_id, sent.message_id)

        elif action == "analyze":
            exp = parts[1]
            symbol = "_".join(parts[2:]) # ФІКС: Підтримка назв з підкресленням
            loading = context.bot.send_message(chat_id, f"⏳ Аналіз {symbol}...")
            
            def on_res(res):
                _safe_delete(context.bot, chat_id, loading.message_id)
                msg = _format_signal_message(res, exp)
                sent = context.bot.send_message(chat_id, msg, parse_mode='Markdown')
                bot_track_message(context.bot_data, chat_id, sent.message_id)
                menu(update, context)

            d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, symbol, chat_id, exp)
            d.addBoth(on_res)
            
    except Exception as e:
        logger.exception("Помилка в button_handler")
        context.bot.send_message(chat_id, f"❌ Сталася помилка: {str(e)}")
        menu(update, context)

def reset_ui(update, context): update.message.reply_text("Використовуйте МЕНЮ.")
def symbols_command(update, context): update.message.reply_text(f"Символів: {len(getattr(app_state, 'all_symbol_names', []))}")
