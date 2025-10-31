# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, Message
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

from state import app_state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

EXPIRATIONS = ["1m", "5m"]

# --- ПОЧАТОК КОДУ ВІД ЕКСПЕРТА ---

def _get_chat_id(update: Update) -> int:
    """Повертає chat_id незалежно від того, message чи callback_query."""
    if update.effective_chat:
        return update.effective_chat.id
    if update.effective_user:
        return update.effective_user.id
    # Резервний варіант для callback_query без effective_chat
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat_id
    logger.error("Не вдалося отримати chat_id з update", extra={"update": update.to_dict()})
    raise RuntimeError("Немає chat_id в update")

def _safe_delete(bot, chat_id: int, message_id: int):
    """Безпечне видалення повідомлення з логуванням помилок."""
    try:
        bot.delete_message(chat_id=chat_id, message_id=message_id)
    except BadRequest as e:
        # логування для діагностики (змінимо на warning, щоб не спамити в debug)
        logger.warning("safe_delete failed: %s (chat=%s mid=%s)", e, chat_id, message_id)
    except Exception as e:
        logger.error("Unexpected error in _safe_delete: %s", e, exc_info=True)

def track_message(context: CallbackContext, message: Message):
    """Зберігає ID усіх повідомлень бота для подальшого очищення."""
    if not message: # Перевірка, чи message не None
        return
    if 'sent_messages' not in context.user_data:
        context.user_data['sent_messages'] = []
    context.user_data['sent_messages'].append(message.message_id)
    # обмежуємо зберігання
    if len(context.user_data['sent_messages']) > 100:
        context.user_data['sent_messages'] = context.user_data['sent_messages'][-100:]

def clear_bot_messages(update: Update, context: CallbackContext, limit: int = 20):
    """Видаляє до `limit` останніх повідомлень, надісланих ботом."""
    chat_id = _get_chat_id(update)
    stored = context.user_data.get('sent_messages', [])
    if not stored:
        logger.debug("clear_bot_messages: Немає збережених повідомлень для видалення.")
        return
    
    to_delete = stored[-limit:]
    logger.debug(f"clear_bot_messages: Намагаюся видалити {len(to_delete)} повідомлень.")
    
    for mid in to_delete:
        _safe_delete(context.bot, chat_id, mid)
    
    # видаляємо тільки ті, що спробували видалити
    context.user_data['sent_messages'] = [mid for mid in stored if mid not in to_delete]

# --- КІНЕЦЬ КОДУ ВІД ЕКСПЕРТА ---


# --- Клавіатури (Без змін) ---

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("МЕНЮ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

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
        button_text = f"{status_icon} Сканер {text}"
        callback_data = f"toggle_scanner_{key}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
    return InlineKeyboardMarkup(keyboard)

def get_expiration_kb(category: str) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(exp, callback_data=f"exp_{category}_{exp}") for exp in EXPIRATIONS]]
    keyboard.append([InlineKeyboardButton("⬅️ Назад до категорій", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_forex_sessions_kb(expiration: str) -> InlineKeyboardMarkup:
    keyboard = []
    for session_name in FOREX_SESSIONS:
        display_text = f"{TRADING_HOURS.get(session_name, '')} {session_name}".strip()
        keyboard.append([InlineKeyboardButton(display_text, callback_data=f"session_forex_{expiration}_{session_name}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад до експірацій", callback_data="category_forex")])
    return InlineKeyboardMarkup(keyboard)

def get_assets_kb(asset_list: list, category: str, expiration: str) -> InlineKeyboardMarkup:
    keyboard, row = [], []
    for asset in asset_list:
        callback_data = f"analyze_{expiration}_{asset.replace('/', '')}"
        row.append(InlineKeyboardButton(asset, callback_data=callback_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    if category == 'forex':
         keyboard.append([InlineKeyboardButton("⬅️ Назад до сесій", callback_data=f"exp_forex_{expiration}")])
    else:
         keyboard.append([InlineKeyboardButton("⬅️ Назад до експірацій", callback_data=f"category_{category}")])
    return InlineKeyboardMarkup(keyboard)

# --- Хендлери (Повністю інтегровані з логікою Експерта) ---

def start(update: Update, context: CallbackContext) -> None:
    sent = update.message.reply_text(
        "👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.",
        reply_markup=get_reply_keyboard()
    )
    # Не відстежуємо привітання, щоб не видаляти його

def menu(update: Update, context: CallbackContext) -> None:
    # 1. Агресивне очищення
    clear_bot_messages(update, context, limit=50) # Видаляємо до 50 старих

    # 2. Надсилаємо нове меню
    sent_message = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())

    # 3. Реєструємо нове меню
    track_message(context, sent_message)

def reset_ui(update: Update, context: CallbackContext) -> None:
    sent_message = update.message.reply_text(
        f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.",
        reply_markup=get_reply_keyboard()
    )
    track_message(context, sent_message) # Відстежуємо

def symbols_command(update: Update, context: CallbackContext):
    if not app_state.SYMBOLS_LOADED or not hasattr(app_state, 'all_symbol_names'):
        sent_msg = update.message.reply_text("Список символів ще не завантажено. Спробуйте за хвилину.")
        track_message(context, sent_msg)
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
        sent_msg = update.message.reply_text(message[i:i + 4096], parse_mode='Markdown')
        track_message(context, sent_msg) # Відстежуємо

def _format_signal_message(result: dict, expiration: str) -> str:
    if result.get("error"):
        return f"❌ Помилка аналізу: {result['error']}"
    pair = result.get('pair', 'N/A')
    price = result.get('price')
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    price_str = f"{price:.5f}" if price and price > 0 else "N/A"
    
    parts = []
    parts.append(f"📈 *Сигнал для {pair} (Експірація: {expiration})*")
    parts.append(f"**Прогноз:** {verdict}")
    parts.append(f"**Ціна в момент сигналу:** `{price_str}`")
    reasons = result.get('reasons', [])
    if reasons:
        parts.append(f"\n📑 **Фактори аналізу:**\n" + "\n".join([f"• _{r}_" for r in reasons]))
    return "\n".join(parts)


def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not query:
        logger.warning("button_handler викликаний без query")
        return
        
    query.answer()
    data = query.data or ""
    chat_id = _get_chat_id(update)
    
    # --- ЛОГІКА ЕКСПЕРТА: Завжди видаляємо повідомлення з кнопками ---
    try:
        query.delete_message()
    except Exception as e:
        logger.debug("query.delete_message failed: %s", e)
    # --- КІНЕЦЬ ---

    parts = data.split('_')
    action = parts[0]
    sent_msg = None # Ініціалізуємо змінну для відстеження

    if action == "toggle" and parts[1] == "scanner":
        if len(parts) > 2:
            category = parts[2]
            if category in app_state.SCANNER_STATE:
                new_state = not app_state.get_scanner_state(category)
                app_state.set_scanner_state(category, new_state)
        # Надсилаємо нове меню (замість edit)
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
            track_message(context, sent_msg) # Відстежуємо меню, на яке повернулися
            return
        
        # Надсилаємо "Завантаження" і відстежуємо
        loading_msg = context.bot.send_message(chat_id, text=f"⏳ Обрано {symbol} (експірація {expiration}). Роблю запит...")
        track_message(context, loading_msg)

        def on_success(result):
            _safe_delete(context.bot, chat_id, loading_msg.message_id) # Видаляємо "Завантаження..."
            
            app_state.cache_signal(symbol, expiration, result)
            msg = _format_signal_message(result, expiration)
            
            # Надсилаємо результат і відстежуємо
            sent_signal = context.bot.send_message(chat_id, text=msg, parse_mode='Markdown')
            track_message(context, sent_signal)

        def on_error(failure):
            _safe_delete(context.bot, chat_id, loading_msg.message_id) # Видаляємо "Завантаження..."

            error = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {error}")
            
            # Надсилаємо помилку і відстежуємо
            sent_error = context.bot.send_message(chat_id, text=f"❌ Виникла помилка: {error}")
            track_message(context, sent_error)

        def do_analysis():
            d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, symbol, query.from_user.id, timeframe=expiration)
            d.addCallbacks(on_success, on_error)

        reactor.callLater(0, do_analysis)
        # sent_msg тут None, бо ми вже відстежили loading_msg
    
    # Відстежуємо всі повідомлення, надіслані в цьому хендлері
    if sent_msg:
        track_message(context, sent_msg)