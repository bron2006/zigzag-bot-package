# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m"]

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("МЕНЮ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ПОЧАТОК ЗМІН: Оновлено функцію створення головного меню ---
def get_main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина", callback_data="category_commodities")]
    ]
    
    # Створення кнопок для керування сканерами
    scanner_map = {
        "forex": "💹 Forex",
        "crypto": "💎 Crypto",
        "commodities": "🥇 Сировина"
    }

    for key, text in scanner_map.items():
        is_enabled = state.SCANNER_STATE.get(key, False)
        status_icon = "✅" if is_enabled else "❌"
        button_text = f"{status_icon} Сканер {text}"
        callback_data = f"toggle_scanner_{key}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
    return InlineKeyboardMarkup(keyboard)
# --- КІНЕЦЬ ЗМІН ---

def get_timeframe_kb(category: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for tf in TIMEFRAMES:
        row.append(InlineKeyboardButton(tf, callback_data=f"tf_{category}_{tf}"))
    keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад до категорій", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_forex_sessions_kb(timeframe: str) -> InlineKeyboardMarkup:
    keyboard = []
    for session_name in FOREX_SESSIONS:
        display_text = f"{TRADING_HOURS.get(session_name, '')} {session_name}".strip()
        keyboard.append([InlineKeyboardButton(display_text, callback_data=f"session_forex_{timeframe}_{session_name}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад до таймфреймів", callback_data="category_forex")])
    return InlineKeyboardMarkup(keyboard)

def get_assets_kb(asset_list: list, category: str, timeframe: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for asset in asset_list:
        callback_data = f"analyze_{timeframe}_{asset.replace('/', '')}"
        row.append(InlineKeyboardButton(asset, callback_data=callback_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад до таймфреймів", callback_data=f"category_{category}")])
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.",
        reply_markup=get_reply_keyboard()
    )

def menu(update: Update, context: CallbackContext) -> None:
    if 'last_menu_id' in context.user_data:
        try:
            context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data['last_menu_id'])
        except BadRequest:
            pass

    sent_message = update.message.reply_text(
        "🏠 Головне меню:",
        reply_markup=get_main_menu_kb()
    )
    context.user_data['last_menu_id'] = sent_message.message_id

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=".",
        disable_notification=True,
        reply_markup=get_reply_keyboard()
    )

def reset_ui(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.", reply_markup=get_reply_keyboard())

def symbols_command(update: Update, context: CallbackContext):
    if not state.SYMBOLS_LOADED or not hasattr(state, 'all_symbol_names'):
        update.message.reply_text("Список символів ще не завантажено. Спробуйте за хвилину.")
        return
    
    forex = sorted([s for s in state.all_symbol_names if "/" in s and len(s) < 8 and "USD" not in s.upper()])
    crypto_usd = sorted([s for s in state.all_symbol_names if "/USD" in s.upper()])
    crypto_usdt = sorted([s for s in state.all_symbol_names if "/USDT" in s.upper()])
    others = sorted([s for s in state.all_symbol_names if "/" not in s])

    message = "**Доступні символи від брокера:**\n\n"
    if forex: message += f"**Forex:**\n`{', '.join(forex)}`\n\n"
    if crypto_usd: message += f"**Crypto (USD):**\n`{', '.join(crypto_usd)}`\n\n"
    if crypto_usdt: message += f"**Crypto (USDT):**\n`{', '.join(crypto_usdt)}`\n\n"
    if others: message += f"**Indices/Stocks/Commodities:**\n`{', '.join(others)}`"
    
    for i in range(0, len(message), 4096):
        update.message.reply_text(message[i:i + 4096], parse_mode='Markdown')

def _format_signal_message(result: dict, timeframe: str) -> str:
    if result.get("error"):
        return f"❌ Помилка аналізу: {result['error']}"

    message_parts = []
    
    if result.get("special_warning"):
        message_parts.append(f"**{result.get('special_warning')}**\n")

    pair = result.get('pair', 'N/A')
    price = result.get('price')
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    score = result.get('bull_percentage', 50)

    confidence_text = "Низька (ринок невизначений)"
    if score > 75 or score < 25: confidence_text = "Висока"
    elif score > 55 or score < 45: confidence_text = "Помірна (є суперечливі фактори)"
    
    price_str = f"{price:.5f}" if price else "N/A"
    
    message_parts.append(f"📈 *Аналіз для {pair} ({timeframe})*")
    message_parts.append(f"**Сигнал:** {verdict}")
    message_parts.append(f"**Впевненість:** {confidence_text}")
    message_parts.append(f"**Поточна ціна:** `{price_str}`")
    message_parts.append(f"\n**Баланс сил:**\n🐂 Бики: {score}% ⬆️ | 🐃 Ведмеді: {100-score}% ⬇️\n")

    candle_pattern = result.get('candle_pattern')
    if candle_pattern and candle_pattern.get('text'):
        message_parts.append(f"**🕯️ Свічковий патерн:**\n_{candle_pattern['text']}_")
    
    support = result.get('support')
    resistance = result.get('resistance')
    if support or resistance:
        levels = []
        if support: levels.append(f"Підтримка: `{support:.5f}`")
        if resistance: levels.append(f"Опір: `{resistance:.5f}`")
        message_parts.append(f"🔑 **Ключові рівні:** " + " | ".join(levels))

    volume_analysis = result.get('volume_info')
    if volume_analysis:
        message_parts.append(f"**📊 Аналіз об'єму:**\n_{volume_analysis}_")

    reasons = result.get('reasons', [])
    if reasons:
        reason_text = "\n".join([f"• _{reason}_" for reason in reasons])
        message_parts.append(f"\n📑 **Ключові фактори аналізу:**\n{reason_text}")
        
    return "\n".join(message_parts)

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    parts = data.split('_')
    action = parts[0]

    # --- ПОЧАТОК ЗМІН: Оновлено логіку обробника кнопок сканера ---
    if action == "toggle" and parts[1] == "scanner":
        category_to_toggle = parts[2] # forex, crypto, etc.
        if category_to_toggle in state.SCANNER_STATE:
            # Перемикаємо стан
            state.SCANNER_STATE[category_to_toggle] = not state.SCANNER_STATE[category_to_toggle]
            status_text = "увімкнено" if state.SCANNER_STATE[category_to_toggle] else "вимкнено"
            query.answer(text=f"Сканер для '{category_to_toggle}' {status_text}")
            # Оновлюємо меню, щоб показати новий стан
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
        return
    # --- КІНЕЦЬ ЗМІН ---

    if action == "main":
        query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())

    elif action == "category":
        category = parts[1]
        query.edit_message_text(f"Виберіть таймфрейм для '{category}':", reply_markup=get_timeframe_kb(category))

    elif action == "tf":
        _, category, timeframe = parts
        if category == 'forex':
            query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb(timeframe))
        else: 
            asset_map = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}
            query.edit_message_text(f"Виберіть актив:", reply_markup=get_assets_kb(asset_map.get(category,[]), category, timeframe))

    elif action == "session":
        _, category, timeframe, session_name = parts
        pairs = FOREX_SESSIONS.get(session_name, [])
        query.edit_message_text(f"Виберіть пару для сесії '{session_name}':", reply_markup=get_assets_kb(pairs, category, timeframe))

    elif action == "analyze":
        _, timeframe, symbol = parts
        if not state.client or not state.SYMBOLS_LOADED:
            query.answer(text="❌ Сервіс ще завантажується, спробуйте за мить.", show_alert=True); return
        
        query.edit_message_text(text=f"⏳ Обрано {symbol} ({timeframe}). Роблю запит...")
        
        def on_success(result):
            message_text = _format_signal_message(result, timeframe)
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb())

        def on_error(failure):
            error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {error_message}")
            query.edit_message_text(text=f"❌ Виникла помилка: {error_message}", reply_markup=get_main_menu_kb())

        def do_analysis():
            d = get_api_detailed_signal_data(state.client, state.symbol_cache, symbol, query.from_user.id, timeframe)
            d.addCallbacks(on_success, on_error)
            
        reactor.callInThread(do_analysis)