from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CallbackQueryHandler, CommandHandler, CallbackContext

TOKEN = '8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o'

def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("МЕНЮ", callback_data='menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Натисни кнопку:", reply_markup=reply_markup)

def menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='crypto')],
        [InlineKeyboardButton("БОТ", callback_data='bot')],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("Меню:", reply_markup=reply_markup)

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data == 'menu':
        menu(update, context)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
