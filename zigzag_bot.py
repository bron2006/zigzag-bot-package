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

TOKEN = '8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o'

# 30 топ-пар
CRYPTO_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT",
    "MATICUSDT", "SHIBUSDT", "LTCUSDT", "LINKUSDT", "BCHUSDT",
    "ATOMUSDT", "ETCUSDT", "XLMUSDT", "HBARUSDT", "ICPUSDT",
    "FILUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "NEARUSDT",
    "STXUSDT", "INJUSDT", "RUNEUSDT", "TIAUSDT", "LDOUSDT"
]

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

def show_crypto_pairs(update: Update, context: CallbackContext, page: int = 0):
    context.user_data['page'] = page
    pairs_per_page = 6
    start = page * pairs_per_page
    end = start + pairs_per_page
    pairs = CRYPTO_PAIRS[start:end]

    keyboard = []
    for i in range(0, len(pairs), 3):
        row = [InlineKeyboardButton(p, callback_data=f'symbol_{p}') for p in pairs[i:i+3]]
        keyboard.append(row)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("<<", callback_data='page_prev'))
    nav_buttons.append(InlineKeyboardButton("НАЗАД", callback_data='menu_crypto'))
    if end < len(CRYPTO_PAIRS):
        nav_buttons.append(InlineKeyboardButton(">>", callback_data='page_next'))
    keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text("Виберіть пару:", reply_markup=reply_markup)

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
        context.user_data['tf'] = tf
        show_crypto_pairs(update, context)
    elif data.startswith('symbol_'):
        symbol = data.split('_')[1]
        context.user_data['symbol'] = symbol
        query.answer()
        query.edit_message_text(f"✅ Обрано: {context.user_data['tf']} + {symbol}")
    elif data == 'page_next':
        page = context.user_data.get('page', 0) + 1
        show_crypto_pairs(update, context, page)
    elif data == 'page_prev':
        page = max(0, context.user_data.get('page', 0) - 1)
        show_crypto_pairs(update, context, page)
    elif data == 'back':
        show_main_menu(update, context)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CallbackQueryHandler(handle_callbacks))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
