# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS, get_chat_id, get_fly_app_name
# --- ПОЧАТОК ЗМІН: Змінено імпорт, щоб читати з Redis ---
from analysis import get_analysis_from_redis 
from redis_client import get_redis
# --- КІНЕЦЬ ЗМІН ---

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m"]

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    # ... (код без змін) ...

def get_main_menu_kb() -> InlineKeyboardMarkup:
    # ... (код без змін) ...

def get_timeframe_kb(category: str) -> InlineKeyboardMarkup:
    # ... (код без змін) ...

def get_forex_sessions_kb(timeframe: str) -> InlineKeyboardMarkup:
    # ... (код без змін) ...

def get_assets_kb(asset_list: list, category: str, timeframe: str) -> InlineKeyboardMarkup:
    # ... (код без змін) ...

def start(update: Update, context: CallbackContext) -> None:
    # ... (код без змін) ...

def menu(update: Update, context: CallbackContext) -> None:
    # ... (код без змін) ...

def reset_ui(update: Update, context: CallbackContext) -> None:
    # ... (код без змін) ...

def symbols_command(update: Update, context: CallbackContext):
    # ... (код без змін) ...

def _format_signal_message(result: dict, timeframe: str) -> str:
    # ... (код без змін) ...

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    parts = data.split('_')
    action = parts[0]

    if action == "toggle" and parts[1] == "scanner":
        # ... (код без змін) ...

    if action == "main":
        # ... (код без змін) ...

    elif action == "category":
        # ... (код без змін) ...

    elif action == "tf":
        # ... (код без змін) ...

    elif action == "session":
        # ... (код без змін) ...

    # --- ПОЧАТОК ЗМІН: Повністю оновлена логіка ручного аналізу ---
    elif action == "analyze":
        _, timeframe, symbol = parts
        
        query.edit_message_text(text=f"⏳ Отримую аналіз для {symbol} ({timeframe})...")
        
        def on_success(result):
            if not result:
                result = {"error": f"Аналіз для {symbol} на таймфреймі {timeframe} ще не готовий. Будь ласка, зачекайте."}
            
            message_text = _format_signal_message(result, timeframe)
            # Повертаємо головне меню після показу результату
            back_button = InlineKeyboardButton("⬅️ Назад до меню", callback_data="main_menu")
            keyboard = InlineKeyboardMarkup([[back_button]])
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=keyboard)

        def on_error(failure):
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol} (з Redis): {failure}")
            query.edit_message_text(text=f"❌ Виникла помилка отримання даних.", reply_markup=get_main_menu_kb())

        # Тепер ми читаємо готовий результат з Redis, як і Web App
        d = get_analysis_from_redis(symbol, timeframe)
        d.addCallbacks(on_success, on_error)
    # --- КІНЕЦЬ ЗМІН ---

# --- ПОЧАТОК ЗМІН: Додано нові функції для сповіщень ---
def _format_scanner_notification(data):
    # ... (код без змін) ...

def send_scanner_notification(bot, data):
    # ... (код без змін) ...