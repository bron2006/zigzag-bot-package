# bot.py
import json
from urllib.parse import parse_qs
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
from db import init_db, get_watchlist, toggle_watch
# Змінено імпорт: get_api_detailed_signal_data тепер імпортується з analysis
from analysis import get_api_detailed_signal_data, rank_assets_for_api, get_api_mta_data, sort_pairs_by_activity
import telegram_ui

CORS(app)

def _get_user_id_from_request(req):
    init_data = req.args.get("initData")
    if not init_data:
        return None
    try:
        user_json_str = parse_qs(init_data).get("user", [None])[0]
        if user_json_str:
            return json.loads(user_json_str).get("id")
    except Exception:
        return None

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dp.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "OK", 200

@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    timeframe = request.args.get("tf", "1m")
    user_id = _get_user_id_from_request(request) # Отримуємо user_id з запиту
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    # Передаємо user_id до функції аналізу
    return jsonify(get_api_detailed_signal_data(pair, timeframe=timeframe, user_id=user_id))

@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []

    return jsonify({
        "watchlist": watchlist,
        "crypto": rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto'),
        "forex": {session: sort_pairs_by_activity([{'ticker': p} for p in pairs]) for session, pairs in FOREX_SESSIONS.items()},
        "stocks": sort_pairs_by_activity([{'ticker': p} for p in STOCK_TICKERS])
    })

@app.route("/api/toggle_watchlist", methods=["GET"])
def toggle_watchlist_route():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id or not pair:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
    toggle_watch(user_id, pair)
    return jsonify({"success": True})

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v8.0 - Stable Launch"

if __name__ != "__main__":
    init_db()
