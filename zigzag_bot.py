from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

TOKEN = "8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"

def get_main_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("МЕНЮ", callback_data='main')]])

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Натисни кнопку нижче ⬇️", reply_markup=get_main_menu())

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'main':
        keyboard = [
            [InlineKeyboardButton("КРИПТА", callback_data='crypto'), InlineKeyboardButton("БОТ", callback_data='bot')],
            [InlineKeyboardButton("НАЗАД", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard + [[InlineKeyboardButton("МЕНЮ", callback_data='main')]])
        query.edit_message_text("Меню:", reply_markup=reply_markup)

    elif query.data == 'crypto':
        keyboard = [
            [InlineKeyboardButton("5М", callback_data='tf_5m'), InlineKeyboardButton("15М", callback_data='tf_15m')],
            [InlineKeyboardButton("НАЗАД", callback_data='main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard + [[InlineKeyboardButton("МЕНЮ", callback_data='main')]])
        query.edit_message_text("Обери таймфрейм:", reply_markup=reply_markup)

    elif query.data == 'bot':
        keyboard = [
            [InlineKeyboardButton("СТАРТ", callback_data='start_bot'), InlineKeyboardButton("СТОП", callback_data='stop_bot')],
            [InlineKeyboardButton("СТАТУС", callback_data='status')],
            [InlineKeyboardButton("НАЗАД", callback_data='main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard + [[InlineKeyboardButton("МЕНЮ", callback_data='main')]])
        query.edit_message_text("Меню бота:", reply_markup=reply_markup)

    elif query.data == 'start_bot':
        query.edit_message_text("✅ Бот запущено!", reply_markup=get_main_menu())

    elif query.data == 'stop_bot':
        query.edit_message_text("⛔ Бот зупинено.", reply_markup=get_main_menu())

    elif query.data == 'status':
        query.edit_message_text("ℹ️ Статус: бот готовий до роботи.", reply_markup=get_main_menu())

    elif query.data.startswith('tf_'):
        tf = query.data.replace("tf_", "")
        query.edit_message_text(f"✅ Обрано таймфрейм: {tf}", reply_markup=get_main_menu())

def main():
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
