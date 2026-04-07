import logging
import time
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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
    if update.effective_user: return update.effective_user.id
    return 0

def _safe_delete(bot, chat_id: int, message_id: int):
    try: bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True)

def get_main_menu_kb() -> InlineKeyboardMarkup:
    # Твоя структура + Обране
    keyboard = [
        [InlineKeyboardButton("⭐ Мій список (Обране)", callback_data="category_watchlist")],
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина", callback_data="category_commodities")]
    ]
    scanner_map = {"forex": "💹 Forex", "crypto": "💎 Crypto", "commodities": "🥇 Сировина", "watchlist": "⭐ Обране"}
    for key, text in scanner_map.items():
        status = "✅" if app_state.get_scanner_state(key) else "❌"
        keyboard.append([InlineKeyboardButton(f"{status} Сканер {text}", callback_data=f"toggle_scanner_{key}")])
    return InlineKeyboardMarkup(keyboard)

def get_expiration_kb(category: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(exp, callback_data=f"exp_{category}_{exp}") for exp in EXPIRATIONS]]
    kb.append([InlineKeyboardButton("⬅️ Назад до категорій", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)

def get_forex_sessions_kb(expiration: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(f"{TRADING_HOURS.get(s, '')} {s}".strip(), callback_data=f"session_forex_{expiration}_{s}")] for s in FOREX_SESSIONS]
    kb.append([InlineKeyboardButton("⬅️ Назад до експірацій", callback_data="category_forex")])
    return InlineKeyboardMarkup(kb)

def get_assets_kb(asset_list: list, category: str, expiration: str) -> InlineKeyboardMarkup:
    kb, row = [], []
    for asset in asset_list:
        clean = asset.replace('/', '')
        cd = f"analyze_{expiration}_{clean}"
        row.append(InlineKeyboardButton(asset, callback_data=cd))
        if len(row) == 2: kb.append(row); row = []
    if row: kb.append(row)
    back = "⬅️ Назад до сесій" if category == 'forex' else "⬅️ Назад до експірацій"
    cd_back = f"exp_forex_{expiration}" if category == 'forex' else f"category_{category}"
    kb.append([InlineKeyboardButton(back, callback_data=cd_back)])
    return InlineKeyboardMarkup(kb)

def _format_signal_message(result: dict, expiration: str) -> str:
    if result.get("error"): return f"❌ Помилка: {result['error']}"
    pair, price, verdict = result.get('pair', 'N/A'), result.get('price'), result.get('verdict_text', 'WAIT')
    p_str = f"{price:.5f}" if price else "N/A"
    msg = f"📈 *Сигнал для {pair}* ({expiration})\n**Прогноз:** {verdict}\n**Ціна:** `{p_str}`"
    reasons = result.get('reasons', [])
    if reasons: msg += "\n\n📑 **Фактори аналізу:**\n" + "\n".join([f"• _{r}_" for r in reasons])
    return msg

def start(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)
    sent = update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ».", reply_markup=get_reply_keyboard())
    bot_track_message(context.bot_data, chat_id, sent.message_id)
    menu(update, context)

def menu(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)
    try: bot_clear_messages(context.bot, context.bot_data, chat_id, limit=100)
    except: pass
    sent = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

def stats_command(update, context):
    now, cache = time.time(), app_state.latest_analysis_cache
    lines = ["📊 *Статистика за 1 год:*"]
    for p, r in cache.items():
        if now - r.get("ts", 0) < 3600: lines.append(f"• {p}: {r.get('verdict_text')}")
    update.message.reply_text("\n".join(lines) if len(lines)>1 else "Немає даних", parse_mode='Markdown')

def live_command(update, context):
    lines = ["💹 *Ціни:*"]
    for p, d in app_state.live_prices.items():
        age = time.time() - d.get("ts", 0)
        lines.append(f"{'🟢' if age < 30 else '🔴'} `{p}`: {d.get('mid'):.5f} ({age:.0f}s)")
    update.message.reply_text("\n".join(lines) if len(lines)>1 else "Ефір порожній", parse_mode='Markdown')

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    chat_id = _get_chat_id(update)
    _safe_delete(context.bot, chat_id, query.message.message_id)
    
    parts = query.data.split('_')
    action = parts[0]

    if action == "toggle" and len(parts) > 2:
        cat = parts[2]
        app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
        menu(update, context)
    elif action == "main_menu" or action == "main": menu(update, context)
    elif action == "category":
        cat = parts[1]
        if cat == "watchlist":
            assets = db.get_watchlist(chat_id)
            if not assets:
                context.bot.send_message(chat_id, "📭 Список порожній.", reply_markup=get_main_menu_kb())
            else:
                context.bot.send_message(chat_id, "⭐ Обране. Оберіть ТФ:", reply_markup=get_expiration_kb("watchlist"))
        else:
            context.bot.send_message(chat_id, f"Експірація для {cat}:", reply_markup=get_expiration_kb(cat))
    elif action == "exp":
        _, cat, exp = parts
        if cat == "watchlist":
            context.bot.send_message(chat_id, f"⭐ Обране ({exp}):", reply_markup=get_assets_kb(db.get_watchlist(chat_id), "watchlist", exp))
        elif cat == "forex":
            context.bot.send_message(chat_id, "Сесії Forex:", reply_markup=get_forex_sessions_kb(exp))
        else:
            assets = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}.get(cat, [])
            context.bot.send_message(chat_id, "Оберіть актив:", reply_markup=get_assets_kb(assets, cat, exp))
    elif action == "session":
        _, _, exp, sess = parts
        context.bot.send_message(chat_id, f"Пари {sess}:", reply_markup=get_assets_kb(FOREX_SESSIONS.get(sess, []), "forex", exp))
    elif action == "analyze":
        exp = parts[1]
        symbol = "_".join(parts[2:]) # Підтримка підкреслень
        loading = context.bot.send_message(chat_id, f"⏳ Аналіз {symbol}...")
        def on_res(res):
            _safe_delete(context.bot, chat_id, loading.message_id)
            context.bot.send_message(chat_id, _format_signal_message(res, exp), parse_mode='Markdown')
            menu(update, context)
        get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, symbol, chat_id, exp).addBoth(on_res)

def reset_ui(update, context): update.message.reply_text("Натисніть МЕНЮ.", reply_markup=get_reply_keyboard())
def symbols_command(update, context): update.message.reply_text(f"Символів: {len(getattr(app_state, 'all_symbol_names', []))}")
