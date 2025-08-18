import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
from config import FOREX_SESSIONS

logger = logging.getLogger(__name__)

# --- КЛАВІАТУРИ ---

def get_main_menu_kb() -> InlineKeyboardMarkup:
    """Створює головне inline-меню з вибором типів активів."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="menu_forex")],
    ])

def get_forex_sessions_kb() -> InlineKeyboardMarkup:
    """Створює меню вибору торгових сесій Forex."""
    keyboard = []
    for session in FOREX_SESSIONS:
        keyboard.append([InlineKeyboardButton(f"--- {session} сесія ---", callback_data=f"session_{session}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад до меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_pairs_kb(session: str) -> InlineKeyboardMarkup:
    """Створює меню з валютними парами для обраної сесії."""
    pairs = FOREX_SESSIONS.get(session, [])
    keyboard = []
    row = []
    for pair in pairs:
        row.append(InlineKeyboardButton(pair, callback_data=pair.replace("/", "")))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад до сесій", callback_data="menu_forex")])
    return InlineKeyboardMarkup(keyboard)

# --- ОБРОБНИКИ ---

def start(update: Update, context: CallbackContext) -> None:
    """Обробляє команду /start і створює головну клавіатуру."""
    # --- ЗМІНА: Прибираємо кнопку WebApp ---
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text(
        "👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.", 
        reply_markup=reply_markup
    )

# --- НОВА ФУНКЦІЯ: Повертає меню, якщо воно зникло ---
def reset_ui(update: Update, context: CallbackContext) -> None:
    """При будь-якому текстовому повідомленні повертає головне меню."""
    if update.message.text != "МЕНЮ":
        start(update, context)

def menu(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на кнопку 'МЕНЮ'."""
    try:
        context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    except BadRequest:
        pass
    if 'last_menu_id' in context.user_data:
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest:
            pass
    sent_message = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def _format_signal_message(result: dict) -> str:
    # ... (код без змін)
    return message

def button_handler(update: Update, context: CallbackContext) -> None:
    # ... (код без змін)