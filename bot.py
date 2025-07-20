# bot.py
import traceback
from flask import request, jsonify
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
from db import init_db, get_watchlist
from analysis import get_api_signal_data
import telegram_ui

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

# --- НОВИЙ МАРШРУТ ДЛЯ ОТРИМАННЯ СПИСКІВ ПАР ---
@app.route("/api/get_pairs", methods=["GET"])
def api_get_pairs():
    # Telegram передає дані про користувача в ініціалізаційному рядку
    init_data = request.args.get("initData")
    user_id = None
    # Проста (небезпечна для продакшену) перевірка ID, для нашого випадку підійде
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
    return "ZigZag Bot v3.2 Modular (with WebApp API) running 🟢"

if __name__ != "__main__":
    # Потрібні нові імпорти для API
    import json
    import urllib.parse
    init_db()