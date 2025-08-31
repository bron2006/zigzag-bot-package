# telegram_ui.py
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
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
        [InlineKeyboardButton("🥇 Сировина (Метали)", callback_data="category_commodities")]
    ]
    status_forex = "✅" if scanner_status.get('forex') else "❌"
    status_crypto = "✅" if scanner_status.get('crypto') else "❌"
    status_metals = "✅" if scanner_status.get('metals') else "❌"
    keyboard.extend([
        [InlineKeyboardButton(f"{status_forex} Scan Forex", callback_data="toggle_forex")],
        [InlineKeyboardButton(f"{status_crypto} Scan Crypto", callback_data="toggle_crypto")],
        [InlineKeyboardButton(f"{status_metals} Scan Metals", callback_data="toggle_metals")]
    ])
    return InlineKeyboardMarkup(keyboard)

# ... (інші функції побудови клавіатур)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ».", reply_markup=get_reply_keyboard())

def menu(update: Update, context: CallbackContext):
    try:
        response = requests.get(f"{WORKER_URL}/status")
        scanner_status = response.json()
        update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(scanner_status))
    except requests.RequestException:
        update.message.reply_text("Помилка: сервіс тимчасово недоступний.")

def _format_signal_message(result: dict, timeframe: str) -> str:
    if result.get("error"): return f"❌ Помилка: {result['error']}"
    pair = result.get('pair', 'N/A')
    verdict = result.get('verdict_text', 'Н/Д')
    return f"📈 **Аналіз для {pair} ({timeframe})**\n**Сигнал:** {verdict}"

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    parts = data.split('_')
    action = parts[0]

    if action == "toggle":
        scanner_type = parts[1]
        try:
            response = requests.post(f"{WORKER_URL}/toggle_scanner", json={"type": scanner_type})
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(response.json().get("newState", {})))
        except: query.answer("Помилка: не вдалося змінити статус.", show_alert=True)

    elif action == "analyze":
        _, timeframe, symbol = parts
        query.edit_message_text(text=f"⏳ Аналізую {symbol} ({timeframe})...")
        try:
            params = {"pair": symbol, "timeframe": timeframe}
            response = requests.get(f"{WORKER_URL}/analyze", params=params, timeout=30)
            result = response.json()
            message_text = _format_signal_message(result, timeframe)
            status_resp = requests.get(f"{WORKER_URL}/status")
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb(status_resp.json()))
        except: query.edit_message_text(text=f"❌ Помилка аналізу {symbol}.")
    # ... (інша логіка обробки кнопок, яка не змінилася)