# main.py
import os
from flask import request, abort
from config import app, TOKEN, WEBHOOK_SECRET, dp, bot, logger
from telegram_ui import register_handlers
from telegram import Update
from twisted.internet import reactor

# --- Реєстрація всіх Telegram-хендлерів ---
register_handlers(dp)

# --- Flask route для webhook ---
@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    if request.method == "POST":
        if request.headers.get("content-type") == "application/json":
            json_update = request.get_json(force=True)
            update = Update.de_json(json_update, bot)
            dp.process_update(update)
            return "ok", 200
        else:
            abort(403)
    else:
        abort(405)

# --- Точка входу при запуску локально ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port)
