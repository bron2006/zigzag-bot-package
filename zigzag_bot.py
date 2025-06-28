import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
)

# Вставлено за твоїми умовами
TELEGRAM_TOKEN = "bot8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"
CHAT_ID = 1064175237

# Логи
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Кнопки
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("КРИПТА", callback_data='crypto'),
         InlineKeyboardButton("БОТ", callback_data='bot')],
        [InlineKeyboardButton("НАЗАД", callback_data='back')],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')],
    ])

def start(update: Update, context: CallbackContext) -> None:
    # Надсилаємо повідомлення один раз і показуємо меню
    update.message.reply_text("Меню:", reply_markup=main_menu())

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    data = query.data

    if data == "menu" or data == "back":
        query.edit_message_reply_markup(reply_markup=main_menu())

    elif data == "crypto":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1H", callback_data='tf_1h'),
             InlineKeyboardButton("4H", callback_data='tf_4h')],
            [InlineKeyboardButton("НАЗАД", callback_data='back')],
            [InlineKeyboardButton("МЕНЮ", callback_data='menu')],
        ])
        query.edit_message_reply_markup(reply_markup=keyboard)

    elif data == "bot":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("СТАТУС", callback_data='status'),
             InlineKeyboardButton("СТАРТ", callback_data='start_bot'),
             InlineKeyboardButton("СТОП", callback_data='stop_bot')],
            [InlineKeyboardButton("НАЗАД", callback_data='back')],
            [InlineKeyboardButton("МЕНЮ", callback_data='menu')],
        ])
        query.edit_message_reply_markup(reply_markup=keyboard)

    else:
        # Просто ігноруємо інші callback
        query.answer()

def main() -> None:
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
