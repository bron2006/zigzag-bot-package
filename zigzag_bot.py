from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

TOKEN = "8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"

def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='crypto'), InlineKeyboardButton("БОТ", callback_data='bot')],
        [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Головне меню:", reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'crypto':
        keyboard = [
            [InlineKeyboardButton("5М", callback_data='tf_5m'),
             InlineKeyboardButton("15М", callback_data='tf_15m')],
            [InlineKeyboardButton("НАЗАД", callback_data='main_menu')],
            [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("Обери таймфрейм:", reply_markup=reply_markup)

    elif query.data == 'bot':
        keyboard = [
            [InlineKeyboardButton("СТАРТ", callback_data='start_bot'),
             InlineKeyboardButton("СТОП", callback_data='stop_bot')],
            [InlineKeyboardButton("СТАТУС", callback_data='status')],
            [InlineKeyboardButton("НАЗАД", callback_data='main_menu')],
            [InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("Меню бота:", reply_markup=reply_markup)

    elif query.data == 'main_menu':
        start(query, context)

    elif query.data.startswith('tf_'):
        tf = query.data.replace("tf_", "")
        query.edit_message_text(f"✅ Обрано таймфрейм: {tf}")

    elif query.data == 'start_bot':
        query.edit_message_text("✅ Бот запущено!")

    elif query.data == 'stop_bot':
        query.edit_message_text("⛔ Бот зупинено.")

    elif query.data == 'status':
        query.edit_message_text("ℹ️ Статус: бот готовий до роботи.")

def main():
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
