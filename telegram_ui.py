# telegram_ui.py
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest

# MODIFIED: Залежності від state, reactor, analysis видалено
# Замість них використовуємо конфіги та робимо запити до воркера

from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m"]
WORKER_URL = "http://localhost:8081" # Адреса внутрішнього API нашого воркера

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("МЕНЮ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# MODIFIED: Клавіатура тепер приймає статус сканерів як аргумент
def get_main_menu_kb(scanner_status: dict) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина (Метали)", callback_data="category_commodities")]
    ]
    
    # NEW: Окремі кнопки для кожного сканера
    status_forex = "✅ Увімкнено" if scanner_status.get('forex') else "❌ Вимкнено"
    status_crypto = "✅ Увімкнено" if scanner_status.get('crypto') else "❌ Вимкнено"
    status_metals = "✅ Увімкнено" if scanner_status.get('metals') else "❌ Вимкнено"

    keyboard.extend([
        [InlineKeyboardButton(f"Forex Scan: {status_forex}", callback_data="toggle_forex")],
        [InlineKeyboardButton(f"Crypto Scan: {status_crypto}", callback_data="toggle_crypto")],
        [InlineKeyboardButton(f"Metals Scan: {status_metals}", callback_data="toggle_metals")]
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_kb(category: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = [InlineKeyboardButton(tf, callback_data=f"tf_{category}_{tf}") for tf in TIMEFRAMES]
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
    
    # MODIFIED: Отримуємо актуальний статус сканерів перед відображенням меню
    try:
        response = requests.get(f"{WORKER_URL}/status")
        scanner_status = response.json()
    except requests.RequestException:
        scanner_status = {}
        update.message.reply_text("Помилка: не вдалося отримати статус сканерів від воркера.")

    sent_message = update.message.reply_text(
        "🏠 Головне меню:",
        reply_markup=get_main_menu_kb(scanner_status)
    )
    context.user_data['last_menu_id'] = sent_message.message_id

def reset_ui(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"Невідома команда. Використовуйте кнопки.", reply_markup=get_reply_keyboard())

def symbols_command(update: Update, context: CallbackContext):
    # Ця функція тепер теж має робити запит до воркера, але поки що її можна залишити без змін
    # або тимчасово вимкнути, оскільки вона не є частиною основного функціоналу.
    update.message.reply_text("Ця команда тимчасово недоступна в новій архітектурі.")

def _format_signal_message(result: dict, timeframe: str) -> str:
    # Ця функція залишається без змін, вона працює з тою ж структурою даних
    if result.get("error"): return f"❌ Помилка аналізу: {result['error']}"
    # ... (весь ваш код форматування)
    message = ""
    if result.get("special_warning"): message += f"**{result.get('special_warning')}**\n\n"
    pair = result.get('pair', 'N/A'); price = result.get('price', 0)
    verdict = result.get('verdict_text', 'Не вдалося визначити.'); score = result.get('bull_percentage', 50)
    confidence_text = ""
    if score > 75 or score < 25: confidence_text = "Висока"
    elif score > 55 or score < 45: confidence_text = "Помірна"
    else: confidence_text = "Низька"
    support = result.get('support'); resistance = result.get('resistance')
    reasons = result.get('reasons', []); candle_pattern = result.get('candle_pattern')
    volume_analysis = result.get('volume_info')
    price_str = f"{price:.5f}" if price else "N/A"
    message += f"📈 **Аналіз для {pair} ({timeframe})**\n\n"
    message += f"**Сигнал:** {verdict}\n**Впевненість:** {confidence_text}\n"
    message += f"**Поточна ціна:** `{price_str}`\n\n"
    message += f"**Баланс сил:**\n🐂 Бики: {score}% | 🐃 Ведмеді: {100-score}%\n\n"
    if candle_pattern and candle_pattern.get('text'): message += f"**🕯️ Патерн:** {candle_pattern['text']}\n\n"
    if support or resistance:
        message += "🔑 **Ключові рівні:**\n"
        if support: message += f" - Підтримка: `{support:.5f}`\n"
        if resistance: message += f" - Опір: `{resistance:.5f}`\n"
        message += "\n"
    if volume_analysis: message += f"**📊 Об'єм:** {volume_analysis}\n\n"
    if reasons:
        message += "📑 **Ключові фактори:**\n"
        for reason in reasons: message += f" - {reason}\n"
    return message

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    parts = data.split('_')
    action = parts[0]

    # MODIFIED: Повністю перероблена логіка керування сканерами
    if action == "toggle":
        scanner_type = parts[1] # forex, crypto, metals
        try:
            response = requests.post(f"{WORKER_URL}/toggle_scanner", json={"type": scanner_type}, timeout=5)
            response.raise_for_status()
            new_state = response.json().get("newState", {})
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(new_state))
        except requests.RequestException as e:
            query.answer(f"Помилка: не вдалося з'єднатись з воркером. {e}", show_alert=True)
        return

    if action == "main":
        try:
            response = requests.get(f"{WORKER_URL}/status")
            scanner_status = response.json()
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(scanner_status))
        except requests.RequestException:
             query.edit_message_text("Помилка: не вдалося оновити меню.")

    elif action == "category":
        category = parts[1]
        query.edit_message_text(f"Виберіть таймфрейм для '{category}':", reply_markup=get_timeframe_kb(category))

    elif action == "tf":
        _, category, timeframe = parts
        asset_map = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}
        if category == 'forex':
            query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb(timeframe))
        elif category in asset_map:
            query.edit_message_text(f"Виберіть актив:", reply_markup=get_assets_kb(asset_map[category], category, timeframe))

    elif action == "session":
        _, category, timeframe, session_name = parts
        pairs = FOREX_SESSIONS.get(session_name, [])
        query.edit_message_text(f"Виберіть пару для '{session_name}':", reply_markup=get_assets_kb(pairs, category, timeframe))
    
    # MODIFIED: Повністю перероблена логіка ручного аналізу
    elif action == "analyze":
        _, timeframe, symbol = parts
        query.edit_message_text(text=f"⏳ Роблю запит на аналіз {symbol} ({timeframe})...")
        
        try:
            params = {"pair": symbol, "timeframe": timeframe}
            response = requests.get(f"{WORKER_URL}/analyze", params=params, timeout=20)
            response.raise_for_status()
            result = response.json()
            
            message_text = _format_signal_message(result, timeframe)
            
            # Отримуємо свіжий статус сканерів для кнопки "Назад"
            status_resp = requests.get(f"{WORKER_URL}/status")
            scanner_status = status_resp.json()
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb(scanner_status))

        except requests.RequestException as e:
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {e}")
            query.edit_message_text(text=f"❌ Помилка під час аналізу {symbol}: Не вдалося з'єднатися з сервісом аналітики.")