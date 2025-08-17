from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from db import get_watchlist, toggle_watch
from analysis import get_api_detailed_signal_data, get_api_mta_data
from config import CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCKS_US_SYMBOLS

def start(update: Update, context: CallbackContext):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ».", reply_markup=reply_markup)

def menu_command(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("⭐ Обране", callback_data='menu_watchlist'),
                 InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')]]
    update.message.reply_text("🏠 Меню:", reply_markup=InlineKeyboardMarkup(keyboard))

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("Обробка натискання...")  # Простіше для прикладу

def register_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
