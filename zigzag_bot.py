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

# 30 топових пар
CRYPTO_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT",
    "MATICUSDT", "SHIBUSDT", "LTCUSDT", "LINKUSDT", "BCHUSDT",
    "ATOMUSDT", "ETCUSDT", "XLMUSDT", "HBARUSDT", "ICPUSDT",
    "FILUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "NEARUSDT",
    "STXUSDT", "INJUSDT", "RUNEUSDT", "TIAUSDT", "LDOUSDT"
]

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("КРИПТА", callback_data='menu_crypto'),
         InlineKeyboardButton("БОТ", callback_data='menu_bot')],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')]
    ])

def get_back_menu(callback_back):
    return [
        [InlineKeyboardButton("НАЗАД", callback_data=callback_back)],
        [InlineKeyboardButton("МЕНЮ", callback_data='menu')]
    ]

def start(update: Update, context: CallbackContext):
    update.message.reply_text(".", reply_markup=get_main_menu())

def show_main_menu(update: Update, context: CallbackContext):
    update.callback_query.edit_message_text(".", reply_markup=get_main_menu())

def show_crypto_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("1M", callback_data='tf_1m'),
         InlineKeyboardButton("5M", callback_data='tf_5m'),
         InlineKeyboardButton("15M", callback_data='tf_15m')]
    ] + get_back_menu('m
