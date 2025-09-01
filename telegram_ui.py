# telegram_ui.py
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext

from config import FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES

logger = logging.getLogger(__name__)

# FIX: Замінено localhost на правильну внутрішню адресу
WORKER_URL = "http://zigzag-bot-package.internal:8081"

# ... (решта коду telegram_ui.py без змін) ...
def get_reply_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True)
def get_main_menu_kb(scanner_status: dict) -> InlineKeyboardMarkup:
    # ...
    return InlineKeyboardMarkup(keyboard)
def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ».", reply_markup=get_reply_keyboard())
def menu(update: Update, context: CallbackContext):
    try:
        response = requests.get(f"{WORKER_URL}/status")
        update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(response.json()))
    except requests.RequestException:
        update.message.reply_text("Помилка: сервіс тимчасово недоступний.")
def _format_signal_message(result: dict, timeframe: str) -> str:
    # ...
    return f"Сигнал..."
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; query.answer(); data = query.data; parts = data.split('_'); action = parts[0]
    if action == "toggle":
        scanner_type = parts[1]
        try:
            response = requests.post(f"{WORKER_URL}/toggle_scanner", json={"type": scanner_type})
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb(response.json().get("newState", {})))
        except: query.answer("Помилка.", show_alert=True)
    elif action == "analyze":
        _, timeframe, symbol = parts
        query.edit_message_text(text=f"⏳ Аналізую {symbol} ({timeframe})...")
        try:
            params = {"pair": symbol, "timeframe": timeframe}
            response = requests.get(f"{WORKER_URL}/analyze", params=params, timeout=30)
            message_text = _format_signal_message(response.json(), timeframe)
            status_resp = requests.get(f"{WORKER_URL}/status")
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb(status_resp.json()))
        except: query.edit_message_text(text=f"❌ Помилка аналізу {symbol}.")
    # ...