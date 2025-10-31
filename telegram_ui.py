# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

from state import app_state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS
from analysis import get_api_detailed_signal_data
from utils_message_cleanup import bot_clear_messages, bot_track_message

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

def menu(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    # Очищаємо всі повідомлення користувача
    bot_clear_messages(context.bot, context.bot_data, chat_id, limit=100)

    # Очищаємо всі повідомлення сканера
    if app_state.updater and app_state.updater.bot:
        bot_clear_messages(app_state.updater.bot, app_state.updater.bot.bot_data, chat_id, limit=100)

    # Надсилаємо нове меню
    sent = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    bot_track_message(context.bot_data, chat_id, sent.message_id)

def reset_ui(update: Update, context: CallbackContext) -> None:
    sent_message = update.message.reply_text(
        f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.",
        reply_markup=get_reply_keyboard()
    )
    chat_id = update.effective_chat.id
    bot_track_message(context.bot_data, chat_id, sent_message.message_id)

# Форматування сигналів
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
        parts.append(f"\n📑 **Фактори аналізу:**\n" + "\n".join([f"• _{r}_" for r in reasons]))
    return "\n".join(parts)

# button_handler і решта функцій залишаються без змін
# ...
