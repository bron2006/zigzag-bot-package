import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest
from twisted.internet import reactor

from state import app_state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data
from utils_message_cleanup import bot_track_message, bot_clear_messages

logger = logging.getLogger(__name__)

EXPIRATIONS = ["1m", "5m"]

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True)

def get_main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина", callback_data="category_commodities")]
    ]
    scanner_map = {
        "forex": "💹 Forex", "crypto": "💎 Crypto",
        "commodities": "🥇 Сировина", "watchlist": "⭐ Обране"
    }
    for key, text in scanner_map.items():
        is_enabled = app_state.get_scanner_state(key)
        status_icon = "✅" if is_enabled else "❌"
        callback_data = f"toggle_scanner_{key}"
        keyboard.append([InlineKeyboardButton(f"{status_icon} Сканер {text}", callback_data=callback_data)])
    return InlineKeyboardMarkup(keyboard)

def get_expiration_kb(category: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(exp, callback_data=f"exp_{category}_{exp}") for exp in EXPIRATIONS]]
    kb.append([InlineKeyboardButton("⬅️ Назад до категорій", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)

def get_forex_sessions_kb(expiration: str) -> InlineKeyboardMarkup:
    kb = []
    for session_name in FOREX_SESSIONS:
        text = f"{TRADING_HOURS.get(session_name, '')} {session_name}".strip()
        kb.append([InlineKeyboardButton(text, callback_data=f"session_forex_{expiration}_{session_name}")])
    kb.append([InlineKeyboardButton("⬅️ Назад до експірацій", callback_data="category_forex")])
    return InlineKeyboardMarkup(kb)

def get_assets_kb(asset_list: list, category: str, expiration: str) -> InlineKeyboardMarkup:
    kb, row = [], []
    for asset in asset_list:
        cd = f"analyze_{expiration}_{asset.replace('/', '')}"
        row.append(InlineKeyboardButton(asset, callback_data=cd))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    back = "⬅️ Назад до сесій" if category == 'forex' else "⬅️ Назад до експірацій"
    cd_back = f"exp_forex_{expiration}" if category == 'forex' else f"category_{category}"
    kb.append([InlineKeyboardButton(back, callback_data=cd_back)])
    return InlineKeyboardMarkup(kb)

def start(update: Update, context: CallbackContext) -> None:
    sent = update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.",
                                     reply_markup=get_reply_keyboard())
    bot_track_message(context.bot_data, update.effective_chat.id, sent.message_id)

def menu(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    bot_clear_messages(context.bot, context.bot_data, chat_id, limit=100)
    sent = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

def reset_ui(update: Update, context: CallbackContext) -> None:
    sent = update.message.reply_text(
        f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.",
        reply_markup=get_reply_keyboard()
    )
    bot_track_message(context.bot_data, update.effective_chat.id, sent.message_id)

def symbols_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not app_state.SYMBOLS_LOADED or not hasattr(app_state, 'all_symbol_names'):
        sent = update.message.reply_text("Список символів ще не завантажено. Спробуйте за хвилину.")
        bot_track_message(context.bot_data, chat_id, sent.message_id)
        return

    forex = sorted([s for s in app_state.all_symbol_names if "/" in s and len(s) < 8 and "USD" not in s.upper()])
    crypto_usd = sorted([s for s in app_state.all_symbol_names if "/USD" in s.upper()])
    crypto_usdt = sorted([s for s in app_state.all_symbol_names if "/USDT" in s.upper()])
    others = sorted([s for s in app_state.all_symbol_names if "/" not in s])
    message = "**Доступні символи від брокера:**\n\n"
    if forex: message += f"**Forex:**\n`{', '.join(forex)}`\n\n"
    if crypto_usd: message += f"**Crypto (USD):**\n`{', '.join(crypto_usd)}`\n\n"
    if crypto_usdt: message += f"**Crypto (USDT):**\n`{', '.join(crypto_usdt)}`\n\n"
    if others: message += f"**Indices/Stocks/Commodities:**\n`{', '.join(others)}`"
    for i in range(0, len(message), 4096):
        sent = update.message.reply_text(message[i:i + 4096], parse_mode='Markdown')
        bot_track_message(context.bot_data, chat_id, sent.message_id)

def _format_signal_message(result: dict, expiration: str) -> str:
    if result.get("error"):
        return f"❌ Помилка аналізу: {result['error']}"
    pair = result.get('pair', 'N/A')
    price = result.get('price')
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    price_str = f"{price:.5f}" if price and price > 0 else "N/A"
    parts = [f"📈 *Сигнал для {pair} (Експірація: {expiration})*",
             f"**Прогноз:** {verdict}",
             f"**Ціна в момент сигналу:** `{price_str}`"]
    reasons = result.get('reasons', [])
    if reasons:
        parts.append(f"\n📑 **Фактори аналізу:**\n" + "\n".join([f"• _{r}_" for r in reasons]))
    return "\n".join(parts)

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id
    parts = data.split('_')
    action = parts[0]

    if action == "toggle" and parts[1] == "scanner":
        if len(parts) > 2:
            category = parts[2]
            if category in app_state.SCANNER_STATE:
                new_state = not app_state.get_scanner_state(category)
                app_state.set_scanner_state(category, new_state)
                query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
            return

    if action == "main":
        query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())

    elif action == "category":
        category = parts[1]
        query.edit_message_text(f"Оберіть час експірації для '{category}':", reply_markup=get_expiration_kb(category))

    elif action == "exp":
        _, category, expiration = parts
        if category == 'forex':
            query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb(expiration))
        else:
            asset_map = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}
            query.edit_message_text(f"Виберіть актив:", reply_markup=get_assets_kb(asset_map.get(category, []), category, expiration))

    elif action == "session":
        _, category, expiration, session_name = parts
        pairs = FOREX_SESSIONS.get(session_name, [])
        query.edit_message_text(f"Виберіть пару для сесії '{session_name}':", reply_markup=get_assets_kb(pairs, category, expiration))

    elif action == "analyze":
        _, expiration, symbol = parts
        if not app_state.client or not app_state.SYMBOLS_LOADED:
            query.answer(text="❌ Сервіс ще завантажується, спробуйте пізніше.", show_alert=True)
            return
        query.edit_message_text(text=f"⏳ Обрано {symbol} (експірація {expiration}). Роблю запит...")

        def on_success(result):
            msg = _format_signal_message(result, expiration)
            sent = query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=get_main_menu_kb())
            bot_track_message(context.bot_data, query.message.chat.id, sent.message_id)

        def on_error(failure):
            error = str(failure)
            chat_id = query.message.chat.id
            context.bot.send_message(chat_id, f"❌ Помилка: {error}")
            sent_menu = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
            bot_track_message(context.bot_data, chat_id, sent_menu.message_id)

        reactor.callLater(0, lambda: get_api_detailed_signal_data(
            app_state.client, app_state.symbol_cache, symbol, query.from_user.id, timeframe=expiration
        ).addCallbacks(on_success, on_error))
