# bot.py
import threading
import os
from flask import request, g, send_from_directory
from flask_cors import CORS
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler

import config
from config import app, logger, WEBHOOK_SECRET, TOKEN
from db import init_db
import telegram_ui # Важливо, щоб цей імпорт залишився

# --- Логіка для запуску Telegram-бота у фоні ---
def run_telegram_bot():
    """Ця функція ініціалізує та запускає всю логіку Telegram."""
    # --- ПОЧАТОК ЗМІН: Додано блок try...except для відлову фатальних помилок ---
    try:
        logger.info("🤖 Starting Telegram bot initialization in a background thread...")
        
        # Створюємо об'єкти Telegram тут
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
        # URL для вебхука тепер буде братись з оточення, що більш гнучко
        app_name = os.getenv("FLY_APP_NAME", "zigzag-bot-package")
        webhook_url = f"https://{app_name}.fly.dev/{WEBHOOK_SECRET}"
        bot.set_webhook(url=webhook_url)
        
        logger.info(f"🚀 Telegram bot is fully initialized. Webhook set to {webhook_url}")
        config.HEALTH_READY = True # Встановлюємо прапор готовності
        logger.info("✅ HEALTH_READY flag is now True.")
    except Exception as e:
        # Якщо щось піде не так під час ініціалізації, ми побачимо це в логах
        logger.error(f"❌ FATAL ERROR in bot initialization thread: {e}", exc_info=True)
    # --- КІНЕЦЬ ЗМІН ---

# --- Flask логіка ---
CORS(app) # Дозволяє крос-доменні запити (Cross-Origin Resource Sharing)

@app.before_request
def setup_and_log():
    if not hasattr(g, '_database_initialized'):
        init_db()
        g._database_initialized = True
    
    # Не логуємо запити до статичних файлів та health check, щоб не засмічувати логи
    if request.path.startswith(('/script.js', '/style.css', '/_headers')) or request.path == '/health':
        return
    logger.info(f"➡️ [{request.method}] {request.path}")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    # Перевіряємо, чи ініціалізовано dispatcher, перш ніж його використовувати
    if telegram_ui.dp:
        telegram_ui.dp.process_update(Update.de_json(request.get_json(force=True), telegram_ui.bot))
        return "OK", 200
    else:
        logger.error("⚠️ Webhook received before dispatcher was initialized.")
        return "Initializing", 503

@app.route('/health')
def health_check():
    """Новий маршрут для перевірки стану, який буде використовувати Fly.io."""
    if config.HEALTH_READY:
        return "✅ Bot is ready", 200
    else:
        return "⏳ Still initializing...", 503

@app.route('/')
def serve_index():
    """Подає головну сторінку WebApp."""
    return send_from_directory('webapp', 'index.html')

@app.route('/<path:filename>')
def serve_webapp_files(filename):
    """Подає статичні файли WebApp (JS, CSS)."""
    return send_from_directory('webapp', filename)


# --- Запуск фонового потоку для Telegram ---
if __name__ != "__main__":
    # app.config['SERVER_NAME'] = "zigzag-bot-package.fly.dev" # ВИДАЛЕНО. Цей рядок викликав конфлікт з проксі Fly.io
    
    telegram_thread = threading.Thread(target=run_telegram_bot)
    telegram_thread.daemon = True
    telegram_thread.start()