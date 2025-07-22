# bot.py
import traceback
import json
from urllib.parse import parse_qs
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

# Імпортуємо головні об'єкти з конфігурації
from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
# Імпортуємо ініціалізацію БД та функції
from db import init_db, get_watchlist
# Змінено: Імпортуємо нову функцію для детального аналізу
from analysis import get_api_detailed_signal_data
# Імпортуємо обробники, щоб Python "побачив" їх
import telegram_ui

# Ініціалізуємо CORS для нашого додатку
CORS(app)

# Змінено: Додаємо логування всіх запитів
@app.before_request
def log_request():
    logger.info(f"[{request.method}] {request.path} - args={request.args.to_dict()}")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dp.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}\n{traceback.format_exc()}")
    return "OK", 200

# Змінено: Тепер цей endpoint викликає нову функцію для детального аналізу
@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    try:
        data = get_api_detailed_signal_data(pair)
        if "error" in data:
            return jsonify(data)
        return jsonify(data)
    except Exception as e:
        logger.error(f"API error for pair {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Внутрішня помилка сервера при аналізі {pair}"}), 500

# Змінено: Виправлено критичну помилку розбору initData
@app.route("/api/get_pairs", methods=["GET"])
def api_get_pairs():
    init_data = request.args.get("initData")
    user_id = None

    if init_data:
        try:
            parsed = parse_qs(init_data)
            user_json_str = parsed.get("user", [None])[0]
            if user_json_str:
                user_data = json.loads(user_json_str)
                user_id = user_data.get("id")
        except Exception as e:
            logger.warning(f"Failed to parse initData: {e}")
    
    watchlist = get_watchlist(user_id) if user_id else []
    
    return jsonify({
        "watchlist": watchlist,
        "crypto": CRYPTO_PAIRS_FULL,
        "forex": FOREX_SESSIONS,
        "stocks": STOCK_TICKERS
    })

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v3.5 Backend Enhanced 🟢"

if __name__ != "__main__":
    init_db()