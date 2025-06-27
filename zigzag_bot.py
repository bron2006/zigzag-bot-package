from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Updater,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
)

# === Твій токен ===
TOKEN = '8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o'

# === Меню ===
def start(update: Update, context: CallbackContext):
    show_main_menu(update, context)

def show_main_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='menu_crypto'),
         InlineKeyboardButton("БОТ", callback_data='menu_bot')],
        [InlineKeyboardButton("НАЗАД", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        update.message.reply_text("Меню:", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text("Меню:", reply_markup=reply_markup)

def show_crypto_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("1M", callback_data='tf_1m'),
         InlineKeyboardButton("5M", callback_data='tf_5m'),
         InlineKeyboardButton("15M", callback_data='tf_15m')],
        [InlineKeyboardButton("НАЗАД", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("Виберіть таймфрейм:", reply_markup=reply_markup)

def show_bot_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("СТАТУС", callback_data='bot_status')],
        [InlineKeyboardButton("СТАРТ", callback_data='bot_start')],
        [InlineKeyboardButton("СТОП", callback_data='bot_stop')],
        [InlineKeyboardButton("НАЗАД", callback_data='menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("Управління ботом:", reply_markup=reply_markup)

def handle_callbacks(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data

    if data == 'menu':
        show_main_menu(update, context)
    elif data == 'menu_crypto':
        show_crypto_menu(update, context)
    elif data == 'menu_bot':
        show_bot_menu(update, context)
    elif data.startswith('tf_'):
        tf = data.split('_')[1]
        query.answer()
        query.edit_message_text(f"Вибраний таймфрейм: {tf.upper()}")
    elif data.startswith('bot_'):
        command = data.split('_')[1]
        query.answer()
        query.edit_message_text(f"Команда: {command.upper()}")
    elif data == 'back':
        query.answer()
        query.edit_message_text("Повернення назад...")
        show_main_menu(update, context)

# === Запуск ===
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CallbackQueryHandler(handle_callbacks))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
