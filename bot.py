# bot.py
import traceback
from flask import request, jsonify
from flask_cors import CORS # <-- 1. ОСЬ ПОТРІБНИЙ ІМПОРТ
from telegram import Update

# Імпортуємо головні об'єкти з конфігурації
from config import app, bot, dp, WEBHOOK_SECRET, logger
# Імпортуємо ініціалізацію БД
from db import init_db
# Імпортуємо аналітичну функцію для API
from analysis import get_api_signal_data
# Імпортуємо обробники, щоб Python "побачив" їх
import telegram_ui

# --- 2. ІНІЦІАЛІЗАЦІЯ CORS ---
CORS(app) # <-- ОСЬ ЦЕЙ ВАЖЛИВИЙ РЯДОК

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dp.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}\n{traceback.format_exc()}")
    return "OK", 200

@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    try:
        data = get_api_signal_data(pair)
        if "error" in data:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        logger.error(f"API error for pair {pair}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/get_pairs", methods=["GET"])
def api_get_pairs():
    import json
    import urllib.parse
    init_data = request.args.get("initData")
    user_id = None
    if init_data:
        for item in init_data.split('&'):
            if item.startswith('user='):
                try:
                    user_info = json.loads(urllib.parse.unquote(item.split('=', 1)[1]))
                    user_id = user_info.get('id')
                except:
                    pass
    watchlist = get_watchlist(user_id) if user_id else []
    # Повертаємо пусті списки для економії трафіку, оскільки вони вже є в JS
    return jsonify({
        "watchlist": watchlist,
        "crypto": [],
        "forex": {},
        "stocks": []
    })

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v3.3 Modular (with CORS) running 🟢"

if __name__ != "__main__":
    init_db()