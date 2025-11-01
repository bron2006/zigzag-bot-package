# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

from state import app_state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data
from utils_message_cleanup import bot_track_message, bot_clear_messages

logger = logging.getLogger(__name__)
EXPIRATIONS = ["1m", "5m"]

def _get_chat_id(update: Update) -> int:
    if update.effective_chat:
        return update.effective_chat.id
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat_id
    if update.effective_user:
        return update.effective_user.id
    logger.error("Не вдалося отримати chat_id з update")
    return 0

def _safe_delete(bot, chat_id: int, message_id: int):
    try:
        bot.delete_message(chat_id=chat_id, message_id=message_id)
    except BadRequest as e:
        logger.debug("safe_delete failed: %s (chat=%s mid=%s)", e, chat_id, message_id)
    except Exception:
        logger.exception("safe_delete unexpected error (chat=%s mid=%s)", chat_id, message_id)

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
        "forex": "💹 Forex",
        "crypto": "💎 Crypto",
        "commodities": "🥇 Сировина",
        "watchlist": "⭐ Обране"
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
            kb.append(row); row = []
    if row:
        kb.append(row)
    back = "⬅️ Назад до сесій" if category == 'forex' else "⬅️ Назад до експірацій"
    cd_back = f"exp_forex_{expiration}" if category == 'forex' else f"category_{category}"
    kb.append([InlineKeyboardButton(back, callback_data=cd_back)])
    return InlineKeyboardMarkup(kb)

def start(update: Update, context: CallbackContext) -> None:
    chat_id = _get_chat_id(update)
    if not chat_id:
        return
    sent = update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.", reply_markup=get_reply_keyboard())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

def menu(update: Update, context: CallbackContext) -> None:
    chat_id = _get_chat_id(update)
    if not chat_id:
        return

    # Очистити повідомлення, які зберігаються в поточному dispatcher (context.bot_data)
    try:
        bot_clear_messages(context.bot, context.bot_data, chat_id, limit=100)
    except Exception:
        logger.exception("bot_clear_messages(context.bot) failed")

    # Якщо є інший dispatcher (app_state.updater), очистити і його tracked (scanner повідомлення)
    if app_state.updater:
        try:
            other_bot_data = getattr(app_state.updater.dispatcher, "bot_data", None)
            if other_bot_data is not None:
                bot_clear_messages(app_state.updater.bot, other_bot_data, chat_id, limit=100)
        except Exception:
            logger.exception("Не вдалося очистити app_state.updater.dispatcher.bot_data")

    # Надсилаємо головне меню (inline) і відстежуємо
    sent = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

    # Повторно відображаємо клавіатуру "МЕНЮ" у вигляді reply keyboard, щоб кнопка залишалася доступною
    try:
        kb_msg = context.bot.send_message(chat_id, "📋 Для повернення натисніть «МЕНЮ».", reply_markup=get_reply_keyboard())
        bot_track_message(context.bot_data, chat_id, kb_msg.message_id)
    except Exception:
        logger.exception("Не вдалося надіслати reply keyboard після очищення")

def reset_ui(update: Update, context: CallbackContext) -> None:
    chat_id = _get_chat_id(update)
    if not chat_id:
        return
    sent = update.message.reply_text(f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.", reply_markup=get_reply_keyboard())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

def symbols_command(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)
    if not chat_id:
        return

    if not app_state.SYMBOLS_LOADED or not hasattr(app_state, 'all_symbol_names'):
        sent_msg = update.message.reply_text("Список символів ще не завантажено. Спробуйте за хвилину.")
        bot_track_message(context.bot_data, chat_id, sent_msg.message_id)
        return

    forex = sorted([s for s in app_state.all_symbol_names if "/" in s and len(s) < 8 and "USD" not in s.upper()])
    crypto_usd = sorted([s for s in app_state.all_symbol_names if "/USD" in s.upper()])
    crypto_usdt = sorted([s for s in app_state.all_symbol_names if "/USDT" in s.upper()])
    others = sorted([s for s in app_state.all_symbol_names if "/" not in s])
    message = "**Доступні символи від брокера:**\n\n"
    if forex:
        message += f"**Forex:**\n`{', '.join(forex)}`\n\n"
    if crypto_usd:
        message += f"**Crypto (USD):**\n`{', '.join(crypto_usd)}`\n\n"
    if crypto_usdt:
        message += f"**Crypto (USDT):**\n`{', '.join(crypto_usdt)}`\n\n"
    if others:
        message += f"**Indices/Stocks/Commodities:**\n`{', '.join(others)}`"

    for i in range(0, len(message), 4096):
        sent_msg = update.message.reply_text(message[i:i + 4096], parse_mode='Markdown')
        bot_track_message(context.bot_data, chat_id, sent_msg.message_id)

def _format_signal_message(result: dict, expiration: str) -> str:
    if result.get("error"):
        return f"❌ Помилка аналізу: {result['error']}"
    pair = result.get('pair', 'N/A')
    price = result.get('price')
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    price_str = f"{price:.5f}" if price and price > 0 else "N/A"
    parts = [f"📈 *Сигнал для {pair} (Експірація: {expiration})*"]
    parts.append(f"**Прогноз:** {verdict}")
    parts.append(f"**Ціна в момент сигналу:** `{price_str}`")
    reasons = result.get('reasons', [])
    if reasons:
        parts.append("\n📑 **Фактори аналізу:**\n" + "\n".join([f"• _{r}_" for r in reasons]))
    return "\n".join(parts)

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not query:
        return
    query.answer()
    chat_id = _get_chat_id(update)
    if not chat_id:
        return

    # Видаляємо повідомлення з inline клавіатурою (щоб не накопичувалося)
    try:
        _safe_delete(context.bot, chat_id, query.message.message_id)
    except Exception:
        logger.exception("Failed to delete query message")

    data = (query.data or "")
    parts = data.split('_')
    action = parts[0]
    sent_msg = None

    if action == "toggle" and len(parts) > 1 and parts[1] == "scanner":
        if len(parts) > 2:
            category = parts[2]
            if category in app_state.SCANNER_STATE:
                new_state = not app_state.get_scanner_state(category)
                app_state.set_scanner_state(category, new_state)
        sent_msg = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())

    elif action == "main":
        sent_msg = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())

    elif action == "category":
        category = parts[1]
        sent_msg = context.bot.send_message(chat_id, f"Оберіть час експірації для '{category}':", reply_markup=get_expiration_kb(category))

    elif action == "exp":
        _, category, expiration = parts
        if category == 'forex':
            sent_msg = context.bot.send_message(chat_id, "💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb(expiration))
        else:
            asset_map = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}
            sent_msg = context.bot.send_message(chat_id, f"Виберіть актив:", reply_markup=get_assets_kb(asset_map.get(category, []), category, expiration))

    elif action == "session":
        _, category, expiration, session_name = parts
        pairs = FOREX_SESSIONS.get(session_name, [])
        sent_msg = context.bot.send_message(chat_id, f"Виберіть пару для сесії '{session_name}':", reply_markup=get_assets_kb(pairs, category, expiration))

    elif action == "analyze":
        _, expiration, symbol = parts
        if not app_state.client or not app_state.SYMBOLS_LOADED:
            query.answer(text="❌ Сервіс ще завантажується, спробуйте пізніше.", show_alert=True)
            sent_msg = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
            bot_track_message(context.bot_data, chat_id, sent_msg.message_id)
            return

        loading_msg = context.bot.send_message(chat_id, text=f"⏳ Обрано {symbol} (експірація {expiration}). Роблю запит...")
        bot_track_message(context.bot_data, chat_id, loading_msg.message_id)

        def on_success(result):
            try:
                _safe_delete(context.bot, chat_id, loading_msg.message_id)
            except Exception:
                logger.debug("loading_msg delete failed")

            app_state.cache_signal(symbol, expiration, result)
            msg = _format_signal_message(result, expiration)

            sent_signal = context.bot.send_message(chat_id, text=msg, parse_mode='Markdown')
            bot_track_message(context.bot_data, chat_id, sent_signal.message_id)

            sent_menu = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
            bot_track_message(context.bot_data, chat_id, sent_menu.message_id)

        def on_error(failure):
            try:
                _safe_delete(context.bot, chat_id, loading_msg.message_id)
            except Exception:
                pass
            error = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
            logger.error("Error getting signal for %s: %s", symbol, error)
            sent_err = context.bot.send_message(chat_id, text=f"❌ Виникла помилка: {error}")
            bot_track_message(context.bot_data, chat_id, sent_err.message_id)
            sent_menu = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
            bot_track_message(context.bot_data, chat_id, sent_menu.message_id)

        def do_analysis():
            d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, symbol, query.from_user.id, timeframe=expiration)
            d.addCallbacks(on_success, on_error)

        reactor.callLater(0, do_analysis)

    if sent_msg:
        bot_track_message(context.bot_data, chat_id, sent_msg.message_id)
