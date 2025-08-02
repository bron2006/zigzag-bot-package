# bot.py
import threading
import time
from flask import request, jsonify, g
from flask_cors import CORS
from telegram import Bot
from telegram.ext import Updater, CommandHandler

import config
from config import app, logger, WEBHOOK_SECRET, TOKEN
from db import init_db
import telegram_ui # Важливо, щоб цей імпорт залишився

# --- Логіка для запуску Telegram-бота у фоні ---
def run_telegram_bot():
    """Ця функція ініціалізує та запускає всю логіку Telegram."""
    logger.info("🤖 Starting Telegram bot initialization in a background thread...")
    
    # Створюємо об'єкти Telegram тут, а не в config.py
    bot = Bot(token=TOKEN)
    updater = Updater(bot=bot, use_context=True, workers=4)
    dp = updater.dispatcher

    # Реєструємо всі обробники з telegram_ui
    telegram_ui.register_handlers(dp)
    
    # Додаємо обробник /myaccounts, оскільки він був тут
    from ctrader_api import get_trading_accounts, get_valid_access_token
    def my_accounts(update, context):
        user_id = 12345
        access_token = get_valid_access_token(user_id)
        if not access_token:
            update.message.reply_text("Токен доступу не знайдено.")
            return
        # ... (решта логіки my_accounts)
    dp.add_handler(CommandHandler("myaccounts", my_accounts))

    # Запускаємо чергу завдань
    if dp.job_queue:
        dp.job_queue.start()

    # Встановлюємо вебхук
    webhook_url = f"https://{app.config['SERVER_NAME']}/{WEBHOOK_SECRET}"
    bot.set_webhook(url=webhook_url)
    
    logger.info(f"🚀 Telegram bot is fully initialized. Webhook set to {webhook_url}")
    config.HEALTH_READY = True # Встановлюємо прапор готовності
    logger.info("✅ HEALTH_READY flag is now True.")

# --- Flask логіка ---
CORS(app)

@app.before_request
def setup_and_log():
    if not hasattr(g, '_database_initialized'):
        init_db()
        g._database_initialized = True
    logger.info(f"➡️ [{request.method}] {request.path}")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    # Цей ендпоінт тепер просто передає оновлення в уже ініціалізований dispatcher
    from telegram import Update
    telegram_ui.dp.process_update(Update.de_json(request.get_json(force=True), telegram_ui.bot))
    return "OK", 200

@app.route('/')
def health_check():
    # Health check тепер залежить від прапора, як ви і запропонували
    if config.HEALTH_READY:
        return "✅ Bot is ready", 200
    else:
        return "⏳ Still initializing...", 503

# ... (сюди можна додати решту ваших API ендпоінтів, якщо вони потрібні)

# --- Запуск фонового потоку для Telegram ---
# Gunicorn запустить цей файл, і ми одразу стартуємо потік для Telegram
if __name__ != "__main__":
    app.config['SERVER_NAME'] = "zigzag-bot-package.fly.dev" # Вказуємо домен для вебхука
    
    # Запускаємо ініціалізацію Telegram у фоновому потоці, щоб не блокувати Flask
    telegram_thread = threading.Thread(target=run_telegram_bot)
    telegram_thread.daemon = True
    telegram_thread.start()