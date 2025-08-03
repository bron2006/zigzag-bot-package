# bot.py
import threading
import os
from flask import request, g, send_from_directory, jsonify
from flask_cors import CORS
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler

import config
from config import app, logger, WEBHOOK_SECRET, TOKEN, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
from db import init_db, get_watchlist
import telegram_ui # Важливо, щоб цей імпорт залишився

# --- Логіка для запуску Telegram-бота у фоні ---
def run_telegram_bot():
    """Ця функція ініціалізує та запускає всю логіку Telegram."""
    try:
        logger.info("🤖 Starting Telegram bot initialization in a background thread...")
        
        bot = Bot(token=TOKEN)
        updater = Updater(bot=bot, use_context=True, workers=4)
        dp = updater.dispatcher

        telegram_ui.register_handlers(dp)
        
        from ctrader_api import get_trading_accounts, get_valid_access_token
        def my_accounts(update, context):
            user_id = 12345
            access_token = get_valid_access_token(user_id)
            if not access_token:
                update.message.reply_text("Токен доступу не знайдено.")
                return
            # ... (решта логіки my_accounts)
        dp.add_handler(CommandHandler("myaccounts", my_accounts))

        if dp.job_queue:
            dp.job_queue.start()

        app_name = os.getenv("FLY_APP_NAME", "zigzag-bot-package")
        webhook_url = f"https://{app_name}.fly.dev/{WEBHOOK_SECRET}"
        bot.set_webhook(url=webhook_url)
        
        logger.info(f"🚀 Telegram bot is fully initialized. Webhook set to {webhook_url}")
        config.HEALTH_READY = True
        logger.info("✅ HEALTH_READY flag is now True.")
    except Exception as e:
        logger.error(f"❌ FATAL ERROR in bot initialization thread: {e}", exc_info=True)

# --- Flask логіка ---
CORS(app)

@app.before_request
def setup_and_log():
    if not hasattr(g, '_database_initialized'):
        init_db()
        g._database_initialized = True
    
    if request.path.startswith(('/script.js', '/style.css', '/_headers')) or request.path == '/health':
        return
    logger.info(f"➡️ [{request.method}] {request.path}")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
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

# --- Маршрути для WebApp ---

@app.route('/')
def serve_index():
    """Подає головну сторінку WebApp."""
    return send_from_directory('webapp', 'index.html')

@app.route('/<path:filename>')
def serve_webapp_files(filename):
    """Подає статичні файли WebApp (JS, CSS)."""
    return send_from_directory('webapp', filename)

# --- API Endpoints ---

@app.route('/api/get_ranked_pairs')
def get_ranked_pairs():
    """Віддає списки активів для початкового завантаження WebApp."""
    init_data = request.args.get('initData') # Отримуємо, але поки не використовуємо

    # TODO: На наступних кроках ми будемо валідувати initData і отримувати user_id звідти.
    # Поки що використовуємо тимчасове рішення.
    user_id = 12345 
    
    try:
        user_watchlist = get_watchlist(user_id)
        
        # Формуємо відповідь у форматі, який очікує script.js
        response_data = {
            "crypto": [{"ticker": pair, "active": True} for pair in CRYPTO_PAIRS_FULL],
            "forex": {session: [{"ticker": pair, "active": True} for pair in pairs] for session, pairs in FOREX_SESSIONS.items()},
            "stocks": [{"ticker": ticker, "active": True} for ticker in STOCK_TICKERS],
            "watchlist": user_watchlist
        }
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Помилка в /api/get_ranked_pairs: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

# --- Запуск фонового потоку для Telegram ---
if __name__ != "__main__":
    telegram_thread = threading.Thread(target=run_telegram_bot)
    telegram_thread.daemon = True
    telegram_thread.start()