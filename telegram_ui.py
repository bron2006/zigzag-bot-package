# telegram_ui.py
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest

from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m"]
WORKER_URL = "http://localhost:8081"

def get_reply_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True)

def get_main_menu_kb(scanner_status: dict) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина (Метали)", callback_data="category_commodities")]
    ]
    
    status_forex = "✅ Увімкнено" if scanner_status.get('forex') else "❌ Вимкнено"
    status_crypto = "✅ Увімкнено" if scanner_status.get('crypto') else "❌ Вимкнено"
    status_metals = "✅ Увімкнено" if scanner_status.get('metals') else "❌ Вимкнено"

    keyboard.extend([
        [InlineKeyboardButton(f"Scan Forex: {status_forex}", callback_data="toggle_forex")],
        [InlineKeyboardButton(f"Scan Crypto: {status_crypto}", callback_data="toggle_crypto")],
        [InlineKeyboardButton(f"Scan Metals: {status_metals}", callback_data="toggle_metals")]
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_kb(category: str):
    keyboard = [[InlineKeyboardButton(tf, callback_data=f"tf_{category}_{tf}") for tf in TIMEFRAMES]]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_forex_sessions_kb(timeframe: str):
    keyboard = []
    for session_name in FOREX_SESSIONS:
        display_text = f"{TRADING_HOURS.get(session_name, '')} {session_name}".strip()
        keyboard.append([InlineKeyboardButton(display_text, callback_data=f"session_forex_{timeframe}_{session_name}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="category_forex")])
    return InlineKeyboardMarkup(keyboard)

def get_assets_kb(asset_list: list, category: str, timeframe: str):
    keyboard = [[InlineKeyboardButton(asset, callback_data=f"analyze_{timeframe}_{asset.replace('/', '')}")] for asset in asset_list]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"category_{category}")])
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ».", reply_markup=get_reply_keyboard())

def menu(update: Update, context: CallbackContext):
    try:
        response = requests.get(f"{WORKER_URL}/status")
        scanner_status = response.json()
    except requests.RequestException:
        scanner_status = {}
        update.message.reply_text("Помилка: не вдалося отримати статус сканерів.")

    update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(scanner_status))

def _format_signal_message(result: dict, timeframe: str) -> str:
    # Ваша існуюча логіка форматування...
    if result.get("error"): return f"❌ Помилка аналізу: {result['error']}"
    pair = result.get('pair', 'N/A')
    verdict = result.get('verdict_text', 'Н/Д')
    return f"📈 Аналіз для {pair} ({timeframe})\n\n**Сигнал:** {verdict}"

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    parts = data.split('_')
    action = parts[0]

    if action == "toggle":
        scanner_type = parts[1]
        try:
            response = requests.post(f"{WORKER_URL}/toggle_scanner", json={"type": scanner_type}, timeout=5)
            new_state = response.json().get("newState", {})
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(new_state))
        except requests.RequestException as e:
            query.answer(f"Помилка: {e}", show_alert=True)
        return

    if action == "main":
        try:
            response = requests.get(f"{WORKER_URL}/status")
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(response.json()))
        except:
             query.edit_message_text("Помилка: не вдалося оновити меню.")

    elif action == "category":
        category = parts[1]
        query.edit_message_text(f"Виберіть таймфрейм для '{category}':", reply_markup=get_timeframe_kb(category))

    elif action == "tf":
        _, category, timeframe = parts
        asset_map = {'crypto': CRYPTO_PAIRS, 'stocks': STOCK_TICKERS, 'commodities': COMMODITIES}
        if category == 'forex':
            query.edit_message_text("💹 Виберіть сесію:", reply_markup=get_forex_sessions_kb(timeframe))
        elif category in asset_map:
            query.edit_message_text(f"Виберіть актив:", reply_markup=get_assets_kb(asset_map[category], category, timeframe))

    elif action == "session":
        _, category, timeframe, session_name = parts
        pairs = FOREX_SESSIONS.get(session_name, [])
        query.edit_message_text(f"Виберіть пару:", reply_markup=get_assets_kb(pairs, category, timeframe))
    
    elif action == "analyze":
        _, timeframe, symbol = parts
        query.edit_message_text(text=f"⏳ Аналізую {symbol} ({timeframe})...")
        try:
            params = {"pair": symbol, "timeframe": timeframe}
            response = requests.get(f"{WORKER_URL}/analyze", params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            message_text = _format_signal_message(result, timeframe)
            
            status_resp = requests.get(f"{WORKER_URL}/status")
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb(status_resp.json()))
        except requests.RequestException as e:
            query.edit_message_text(text=f"❌ Помилка аналізу {symbol}: сервіс недоступний.")