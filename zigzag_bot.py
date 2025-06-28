from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CallbackQueryHandler, CommandHandler, CallbackContext
import os

TOKEN = "8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"
CHAT_ID = 1064175237

def start(update: Update, context: CallbackContext):
    show_main_menu(update)

def show_main_menu(update):
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='crypto'), InlineKeyboardButton("БОТ", callback_data='bot')],
        [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text("Головне меню:", reply_markup=reply_markup)
    else:
        update.message.reply_text("Головне меню:", reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data

    if data == "main_menu":
        show_main_menu(update)

    elif data == "crypto":
        keyboard = [
            [InlineKeyboardButton("5М", callback_data='tf_5m'),
             InlineKeyboardButton("15М", callback_data='tf_15m'),
             InlineKeyboardButton("1Г", callback_data='tf_1h')],
            [InlineKeyboardButton("НАЗАД", callback_data='main_menu')],
            [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
        ]
        query.edit_message_text("Меню крипти — виберіть таймфрейм:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "bot":
        keyboard = [
            [InlineKeyboardButton("СТАРТ", callback_data='start_bot'),
             InlineKeyboardButton("СТОП", callback_data='stop_bot')],
            [InlineKeyboardButton("СТАТУС", callback_data='status')],
            [InlineKeyboardButton("НАЗАД", callback_data='main_menu')],
            [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
        ]
        query.edit_message_text("Меню бота:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("tf_"):
        timeframe = data.replace("tf_", "")
        query.edit_message_text(f"⏱ Обрано таймфрейм: {timeframe.upper()}")

    elif data == "start_bot":
        query.edit_message_text("✅ Бот запущено!")

    elif data == "stop_bot":
        query.edit_message_text("⛔ Бот зупинено.")

    elif data == "status":
        query.edit_message_text("ℹ️ Статус: бот готовий до роботи.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.a
