import os
import logging
from flask import Flask, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from telegram.error import BadRequest

# --- Налаштування ---
# Токен та інші налаштування тепер беремо з Heroku Config Vars (змінних середовища)
TOKEN = os.environ.get("TOKEN")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
# Порт, який Heroku надає для веб-застосунку
PORT = int(os.environ.get("PORT", "8443"))

# Вмикаємо логування для відстеження помилок на Heroku
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Створюємо екземпляр веб-сервера Flask, який буде "слухати" Heroku
app = Flask(__name__)

# === Генератори клавіатур (для чистоти коду та центрування) ===

def get_main_menu_keyboard():
    """Повертає головне меню. Кнопки розташовані по центру."""
    keyboard = [
        [InlineKeyboardButton("КРИПТА", callback_data='crypto')],
        [InlineKeyboardButton("БОТ", callback_data='bot')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_crypto_menu_keyboard():
    """Повертає меню 'КРИПТА'."""
    keyboard = [
        [InlineKeyboardButton("5М", callback_data='tf_5m'), InlineKeyboardButton("15М", callback_data='tf_15m')],
        [InlineKeyboardButton("НАЗАД", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_bot_menu_keyboard():
    """Повертає меню 'БОТ'."""
    keyboard = [
        [InlineKeyboardButton("СТАРТ", callback_data='start_bot'), InlineKeyboardButton("СТОП", callback_data='stop_bot')],
        [InlineKeyboardButton("СТАТУС", callback_data='status')],
        [InlineKeyboardButton("НАЗАД", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# === Обробники команд та кнопок ===

def start(update: Update, context: CallbackContext):
    """Команда /start. Відразу показує головне меню без зайвого тексту."""
    update.message.reply_text(
        text="Головне меню:",
        reply_markup=get_main_menu_keyboard()
    )

def handle_buttons(update: Update, context: CallbackContext):
    """Обробляє всі натискання на inline-кнопки."""
    query = update.callback_query
    # Важливо відповісти на запит, щоб кнопка перестала "завантажуватися"
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
        reply_markup = get_main_menu_keyboard() # Повертаємо до головного меню
    elif data == 'stop_bot':
        text = "⛔ Бот зупинено"
        reply_markup = get_main_menu_keyboard()
    elif data == 'status':
        text = "📊 Статус: бот очікує"
        reply_markup = get_bot_menu_keyboard() # Залишаємось у меню бота
    elif data.startswith("tf_"):
        tf = data.split("_")[1]
        text = f"🕒 Обрано таймфрейм: {tf}"
        reply_markup = get_main_menu_keyboard()

    # Намагаємося редагувати повідомлення
    try:
        if text:
             query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Ігноруємо помилку, якщо повідомлення не змінилося
            pass
        else:
            # Інші помилки виводимо в лог
            logger.error(f"Error editing message: {e}")

# === Налаштування для Heroku (Webhook) ===

# Створюємо Updater та Dispatcher (без запуску)
updater = Updater(TOKEN, use_context=True)
dp = updater.dispatcher

# Додаємо обробники
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CallbackQueryHandler(handle_buttons))

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook_handler():
    """Обробляє вебхук від Telegram."""
    update = Update.de_json(request.get_json(force=True), updater.bot)
    dp.process_update(update)
    return 'ok'

# Ця функція буде викликана один раз при старті, щоб зареєструвати вебхук
def setup():
    webhook_url = f'https://{HEROKU_APP_NAME}.herokuapp.com/{TOKEN}'
    updater.bot.set_webhook(webhook_url)
    logger.info(f"Webhook has been set to {webhook_url}")

# Запускаємо налаштування вебхука
setup()

# Важливо! Не використовуйте if __name__ == '__main__' для Gunicorn.
# Gunicorn сам імпортує змінну 'app' і запустить її.