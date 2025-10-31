# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest # <--- Додано імпорт

from state import app_state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

EXPIRATIONS = ["1m", "5m"]

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
        "forex": "💹 Forex", "crypto": "💎 Crypto",
        "commodities": "🥇 Сировина", "watchlist": "⭐ Обране"
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
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    if category == 'forex':
         keyboard.append([InlineKeyboardButton("⬅️ Назад до сесій", callback_data=f"exp_forex_{expiration}")])
    else:
         keyboard.append([InlineKeyboardButton("⬅️ Назад до експірацій", callback_data=f"category_{category}")])
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.",
        reply_markup=get_reply_keyboard()
    )

# --- ЗМІНИ: Нова функція menu (Порада 1 Експерта) ---
def menu(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    chat_key = f"chat_{chat_id}_messages" # <--- Виправлено згідно з порадою

    # Очищаємо всі повідомлення, що бот колись надсилав у цьому чаті
    messages = context.bot_data.get(chat_key, [])
    logger.debug(f"Menu: Знайдено {len(messages)} повідомлень для очищення.")
    for mid in messages[-30:]:  # максимум 30 останніх
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except BadRequest:
            pass
        except Exception:
            pass
    context.bot_data[chat_key] = []

    # Надсилаємо нове меню
    sent = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())

    # Зберігаємо ID нового повідомлення
    context.bot_data.setdefault(chat_key, []).append(sent.message_id)
# --- КІНЕЦЬ ЗМІН ---

def reset_ui(update: Update, context: CallbackContext) -> None:
    sent_message = update.message.reply_text(
        f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.",
        reply_markup=get_reply_keyboard()
    )
    # --- ЗМІНИ: Відстежуємо "спам" (Порада 2 Експерта) ---
    chat_id = update.effective_chat.id
    chat_key = f"chat_{chat_id}_messages"
    context.bot_data.setdefault(chat_key, []).append(sent_message.message_id)
    # --- КІНЕЦЬ ЗМІН ---

def symbols_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    chat_key = f"chat_{chat_id}_messages"

    if not app_state.SYMBOLS_LOADED or not hasattr(app_state, 'all_symbol_names'):
        sent_msg = update.message.reply_text("Список символів ще не завантажено. Спробуйте за хвилину.")
        context.bot_data.setdefault(chat_key, []).append(sent_msg.message_id) # Відстежуємо
        return
    
    # ... (код форматування тексту символів без змін) ...
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
        context.bot_data.setdefault(chat_key, []).append(sent_msg.message_id) # Відстежуємо

def _format_signal_message(result: dict, expiration: str) -> str:
    # ... (код форматування без змін) ...
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
        parts.append(f"\n📑 **Фактори аналізу:**\n" + "\n".join([f"• _{r}_" for r in reasons]))
    return "\n".join(parts)

# --- ВАШ ОРИГІНАЛЬНИЙ button_handler (БЕЗ МОЇХ "ТЕХНОЛОГІЙ") ---
def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    
    # Ваш код з last_menu_id (який тепер буде видалятися кнопкою МЕНЮ)
    context.user_data['last_menu_id'] = query.message.message_id 

    parts = data.split('_')
    action = parts[0]

    if action == "toggle" and parts[1] == "scanner":
        if len(parts) > 2:
            category = parts[2]
            if category in app_state.SCANNER_STATE:
                new_state = not app_state.get_scanner_state(category)
                app_state.set_scanner_state(category, new_state)
                status_text = "увімкнено" if new_state else "вимкнено"
                query.answer(text=f"Сканер '{category}' {status_text}")
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
            app_state.cache_signal(symbol, expiration, result)
            msg = _format_signal_message(result, expiration)
            query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=get_main_menu_kb())

        def on_error(failure):
            error = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {error}")
            
            # --- ЗМІНИ: Відстежуємо "спам" про помилку (Порада 2 Експерта) ---
            # Ми не можемо тут редагувати (query.edit_message_text), бо "МЕНЮ" могло видалити це повідомлення.
            # Тому ми видаляємо "Завантаження..." і надсилаємо 2 нових повідомлення.
            
            chat_id = query.effective_chat.id
            chat_key = f"chat_{chat_id}_messages"
            
            # 1. Видаляємо "Завантаження..."
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            except BadRequest:
                pass # Вже видалено

            # 2. Надсилаємо помилку ("спам") і відстежуємо
            sent_err = context.bot.send_message(chat_id, text=f"❌ Виникла помилка: {error}")
            context.bot_data.setdefault(chat_key, []).append(sent_err.message_id)
            
            # 3. Надсилаємо нове меню і відстежуємо
            sent_menu = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
            context.bot_data.setdefault(chat_key, []).append(sent_menu.message_id)
            # --- КІНЕЦЬ ЗМІН ---

        def do_analysis():
            d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, symbol, query.from_user.id, timeframe=expiration)
            d.addCallbacks(on_success, on_error)

        reactor.callLater(0, do_analysis)