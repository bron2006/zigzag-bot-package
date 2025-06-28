from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CallbackQueryHandler, CommandHandler, CallbackContext

TOKEN = '8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o'

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='crypto')],
        [InlineKeyboardButton("БОТ", callback_data='bot')],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def crypto_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("1M", callback_data='tf_1m'),
         InlineKeyboardButton("5M", callback_data='tf_5m'),
         InlineKeyboardButton("15M", callback_data='tf_15m')],
        [InlineKeyboardButton("НАЗАД", callback_data='menu')],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def bot_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("СТАТУС", callback_data='bot_status')],
        [InlineKeyboardButton("СТАРТ", callback_data='bot_start')],
        [InlineKeyboardButton("СТОП", callback_data='bot_stop')],
        [InlineKeyboardButton("НАЗАД", callback_data='menu')],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Головне меню:", reply_markup=main_menu_keyboard())

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data

    if data == 'menu':
        query.edit_message_text("Головне меню:", reply_markup=main_menu_keyboard())
    elif data == 'crypto':
        query.edit_message_text("Меню крипти — виберіть таймфрейм:", reply_markup=crypto_menu_keyboard())
    elif data == 'bot':
        query.edit_message_text("Меню бота — оберіть дію:", reply_markup=bot_menu_keyboard())
    elif data.startswith('tf_'):
        tf = data.split('_')[1]
        query.edit_message_text(f"Обрано таймфрейм: {tf.upper()}\n(Тут буде список криптопар)", reply_markup=main_menu_keyboard())
    elif data == 'bot_status':
        query.edit_message_text("Статус бота: очікуємо...", reply_markup=main_menu_keyboard())
    elif data == 'bot_start':
        query.edit_message_text("Бот запущено!", reply_markup=main_menu_keyboard())
    elif data == 'bot_stop':
        query.edit_message_text("Бот зупинено!", reply_markup=main_menu_keyboard())
    else:
        query.edit_message_text("Невідома команда", reply_markup=main_menu_keyboard())

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = [
    [InlineKeyboardButton("КРИПТА", callback_data='crypto'), InlineKeyboardButton("БОТ", callback_data='bot')],
    [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
]
reply_markup = InlineKeyboardMarkup(keyboard)
