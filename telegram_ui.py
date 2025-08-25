import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m"]

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
    return InlineKeyboardMarkup(keyboard)

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
    for session in FOREX_SESSIONS:
        keyboard.append([InlineKeyboardButton(f"--- {session} сесія ---", callback_data=f"session_forex_{timeframe}_{session}")])
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
        try: context.bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest: pass
    sent_message = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def reset_ui(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.", reply_markup=get_reply_keyboard())

# --- ПОЧАТОК ЗМІН: Додаємо відображення попередження ---
def _format_signal_message(result: dict, timeframe: str) -> str:
    if result.get("error"): return f"❌ Помилка аналізу: {result['error']}"

    message = ""
    # Показуємо спеціальне попередження НАЙПЕРШИМ
    if result.get("special_warning"):
        message += f"**{result['special_warning']}**\n\n"

    pair = result.get('pair', 'N/A')
    price = result.get('price', 0)
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    support = result.get('support')
    resistance = result.get('resistance')
    reasons = result.get('reasons', [])
    candle_pattern = result.get('candle_pattern')
    volume_analysis = result.get('volume_analysis')
    
    price_str = f"{price:.5f}" if price else "N/A"
    message += f"📈 **Аналіз для {pair} ({timeframe})**\n\n"
    message += f"**Сигнал:** {verdict}\n"
    message += f"**Поточна ціна:** `{price_str}`\n\n"
    message += f"**Баланс сил:**\n🐂 Бики: {result.get('bull_percentage', 0)}% ⬆️ | 🐃 Ведмеді: {result.get('bear_percentage', 100)}% ⬇️\n\n"

    if candle_pattern and candle_pattern.get('text'):
        message += f"**🕯️ Свічковий патерн:**\n{candle_pattern['text']}\n\n"
    
    if support or resistance:
        message += "🔑 **Ключові рівні:**\n"
        if support: message += f"    - Підтримка: `{support:.5f}`\n"
        if resistance: message += f"    - Опір: `{resistance:.5f}`\n"
        message += "\n"

    if volume_analysis:
        message += f"**📊 Аналіз об'єму:**\n{volume_analysis}\n\n"

    if reasons:
        message += "📑 **Фактори аналізу:**\n"
        for reason in reasons: message += f"    - {reason}\n"
        
    return message
# --- КІНЕЦЬ ЗМІН ---

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    parts = data.split('_')
    action = parts[0]

    if action == "main":
        query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())

    elif action == "category":
        category = parts[1]
        query.edit_message_text(f"Виберіть таймфрейм для '{category}':", reply_markup=get_timeframe_kb(category))

    elif action == "tf":
        _, category, timeframe = parts
        if category == 'forex':
            query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb(timeframe))
        elif category == 'crypto':
            query.edit_message_text("💎 Виберіть криптовалюту:", reply_markup=get_assets_kb(CRYPTO_PAIRS, category, timeframe))
        elif category == 'stocks':
            query.edit_message_text("📈 Виберіть акцію/індекс:", reply_markup=get_assets_kb(STOCK_TICKERS, category, timeframe))
        elif category == 'commodities':
            query.edit_message_text("🥇 Виберіть сировину:", reply_markup=get_assets_kb(COMMODITIES, category, timeframe))

    elif action == "session":
        _, category, timeframe, session_name = parts
        pairs = FOREX_SESSIONS.get(session_name, [])
        query.edit_message_text(f"Виберіть пару для сесії '{session_name}':", reply_markup=get_assets_kb(pairs, category, timeframe))

    elif action == "analyze":
        _, timeframe, symbol = parts
        if not state.client or not state.client.is_authorized:
            query.answer(text="❌ З'єднання з cTrader ще не встановлено.", show_alert=True); return
        if not state.SYMBOLS_LOADED or symbol not in state.symbol_cache:
            query.answer(text=f"⚠️ Символи ще завантажуються або {symbol} не знайдено.", show_alert=True); return
        
        query.edit_message_text(text=f"⏳ Обрано {symbol} ({timeframe}). Роблю запит до API...")
        
        def on_success(result):
            message_text = _format_signal_message(result, timeframe)
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb())

        def on_error(failure):
            error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {error_message}")
            query.edit_message_text(text=f"❌ Виникла помилка під час аналізу {symbol}: {error_message}", reply_markup=get_main_menu_kb())

        def do_analysis():
            deferred = get_api_detailed_signal_data(state.client, state.symbol_cache, symbol, query.from_user.id, timeframe)
            deferred.addCallbacks(on_success, on_error)
            
        reactor.callFromThread(do_analysis)