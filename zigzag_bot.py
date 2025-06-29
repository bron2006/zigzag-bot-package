from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

TOKEN = "8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"

# === Фіксована кнопка МЕНЮ ===
def fixed_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]])

# === Команда /start ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text("👇", reply_markup=fixed_menu())  # ← виправлено

# === Обробка натискань кнопок ===
def handle_buttons(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data

    if data == 'main_menu':
        buttons = [
            [InlineKeyboardButton("КРИПТА", callback_data='crypto'), InlineKeyboardButton("БОТ", callback_data='bot')],
            [InlineKeyboardButton("НАЗАД", callback_data='back')]
        ]
        query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons + [[InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]]))

    elif data == 'back':
        query.edit_message_reply_markup(reply_markup=fixed_menu())

    elif data == 'crypto':
        buttons = [
            [InlineKeyboardButton("5М", callback_data='tf_5m'), InlineKeyboardButton("15М", callback_data='tf_15m')],
            [InlineKeyboardButton("НАЗАД", callback_data='main_menu')]
        ]
        query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons + [[InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]]))

    elif data == 'bot':
        buttons = [
            [InlineKeyboardButton("СТАРТ", callback_data='start_bot'), InlineKeyboardButton("СТОП", callback_data='stop_bot')],
            [InlineKeyboardButton("СТАТУС", callback_data='status')],
            [InlineKeyboardButton("НАЗАД", callback_data='main_menu')]
        ]
        query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons + [[InlineKeyboardButton("МЕНЮ", callback_data='main_menu')]]))

    elif data == 'start_bot':
        query.edit_message_text("✅ Бот запущено", reply_markup=fixed_menu())

    elif data == 'stop_bot':
        query.edit_message_text("⛔ Бот зупинено", reply_markup=fixed_menu())

    elif data == 'status':
        query.edit_message_text("📊 Статус: бот очікує", reply_markup=fixed_menu())

    elif data.startswith("tf_"):
        tf = data.split("_")[1]
        query.edit_message_text(f"🕒 Обрано таймфрейм: {tf}", reply_markup=fixed_menu())

# === Запуск ===
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(handle_buttons))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
