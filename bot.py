# bot.py
import traceback
import json
import urllib.parse
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

# Імпортуємо головні об'єкти з конфігурації
from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
# Імпортуємо ініціалізацію БД та функції
from db import init_db, get_watchlist
# Імпортуємо аналітичну функцію для API
from analysis import get_api_signal_data
# Імпортуємо обробники, щоб Python "побачив" їх
import telegram_ui

# Ініціалізуємо CORS для нашого додатку
CORS(app)

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dp.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}\n{traceback.format_exc()}")
    return "OK", 200

# --- ПОЧАТОК ЗМІН ---
@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "Параметр 'pair' є обов'язковим"}), 400
    try:
        data = get_api_signal_data(pair)
        # Якщо функція аналізу повернула помилку...
        if "error" in data:
            # ...ми все одно повертаємо статус 200 OK,
            # але в тілі відповіді буде сама помилка.
            # Це дозволить фронтенду її коректно обробити.
            logger.warning(f"Could not get data for API signal: {pair}. Reason: {data['error']}")
            return jsonify({"error": f"Не вдалося отримати дані для {pair}. Можливо, ринок закритий або актив тимчасово недоступний."})
        
        # Якщо все добре, повертаємо дані
        return jsonify(data)
    except Exception as e:
        logger.error(f"API error for pair {pair}: {e}\n{traceback.format_exc()}")
        # Те саме робимо для критичних помилок сервера
        return jsonify({"error": f"Внутрішня помилка сервера при аналізі {pair}"})
# --- КІНЕЦЬ ЗМІН ---

@app.route("/api/get_pairs", methods=["GET"])
def api_get_pairs():
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
    
    return jsonify({
        "watchlist": watchlist,
        "crypto": CRYPTO_PAIRS_FULL,
        "forex": FOREX_SESSIONS,
        "stocks": STOCK_TICKERS
    })

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v3.4 Modular (with API fix) running 🟢"

if __name__ != "__main__":
    init_db()