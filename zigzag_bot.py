import os
import logging
from flask import Flask, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from telegram.error import BadRequest

# --- Налаштування ---
TOKEN = os.environ.get("TOKEN")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === Клавіатури (без змін) ===
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='crypto')],
        [InlineKeyboardButton("БОТ", callback_data='bot')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_crypto_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("5М", callback_data='tf_5m'), InlineKeyboardButton("15М", callback_data='tf_15m')],
        [InlineKeyboardButton("НАЗАД", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_bot_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("СТАРТ", callback_data='start_bot'), InlineKeyboardButton("СТОП", callback_data='stop_bot')],
        [InlineKeyboardButton("СТАТУС", callback_data='status')],
        [InlineKeyboardButton("НАЗАД", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# === Обробники (без змін) ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        text="Головне меню:",
        reply_markup=get_main_menu_keyboard()
    )

def handle_buttons(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    data = query.data
    text = ""
    reply_markup = None

    if data == 'main_menu':
        text = "Головне меню:"
        reply_markup = get_main_menu_keyboard()
    elif data == 'crypto':
        text = "Оберіть таймфрейм:"
        reply_markup = get_crypto_menu_keyboard()
    elif data == 'bot':
        text = "Керування ботом:"
        reply_markup = get_bot_menu_keyboard()
    elif data == 'start_bot':
        text = "✅ Бот запущено"
        reply_markup = get_main_menu_keyboard()
    elif data == 'stop_bot':
        text = "⛔ Бот зупинено"
        reply_markup = get_main_menu_keyboard()
    elif data == 'status':
        text = "📊 Статус: бот очікує"
        reply_markup = get_bot_menu_keyboard()
    elif data.startswith("tf_"):
        tf = data.split("_")[1]
        text = f"🕒 Обрано таймфрейм: {tf}"
        reply_markup = get_main_menu_keyboard()

    try:
        if text:
             query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing message: {e}")

# === Налаштування для Heroku (Webhook) ===

@app.route('/')
def index():
    return "OK"

# =========================================================
# ФІНАЛЬНЕ ВИПРАВЛЕННЯ №1: Використовуємо просту, статичну адресу '/webhook'
@app.route('/webhook', methods=['POST'])
def webhook_handler():
    update = Update.de_json(request.get_json(force=True), updater.bot)
    dp.process_update(update)
    return 'ok'
# =========================================================

updater = Updater(TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CallbackQueryHandler(handle_buttons))

def setup():
    # =========================================================
    # ФІНАЛЬНЕ ВИПРАВЛЕННЯ №2: Встановлюємо вебхук на нову статичну адресу
    webhook_url = f'https://{HEROKU_APP_NAME}.herokuapp.com/webhook'
    # =========================================================
    updater.bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook has been set to {webhook_url}")

setup()