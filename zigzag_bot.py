from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

TOKEN = "8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"

# === Фіксована кнопка МЕНЮ ===
def fixed_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]])

# === Команда /start ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text("👇", reply_markup=fixed_menu())

# === Обробка натискань кнопок ===
def handle_buttons(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data

    if data == 'main_menu':
        buttons = [
            [InlineKeyboardButton("КРИПТА", callback_data='crypto')],
            [InlineKeyboardButton("БОТ", callback_data='bot')],
            [InlineKeyboardButton("НАЗАД", callback_data='back')]
        ]
        query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(buttons + [[InlineKeyb]()]()_
