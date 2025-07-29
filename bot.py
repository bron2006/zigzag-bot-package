# bot.py
import traceback
import json
from urllib.parse import parse_qs
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
from db import init_db, get_watchlist, toggle_watch, get_signal_history
from analysis import get_api_detailed_signal_data, rank_assets_for_api, get_api_mta_data, sort_pairs_by_activity
import telegram_ui

CORS(app)

def _get_user_id_from_request(req):
    init_data = req.args.get("initData")
    if not init_data: return None
    try:
        parsed = parse_qs(init_data)
        user_json_str = parsed.get("user", [None])[0]
        if user_json_str:
            return json.loads(user_json_str).get("id")
    except Exception as e:
        logger.warning(f"Failed to parse initData: {e}")
    return None

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

@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    timeframe = request.args.get("tf", "1m")
    if not pair: return jsonify({"error": "pair is required"}), 400
    try:
        data = get_api_detailed_signal_data(pair, timeframe=timeframe)
        if "error" in data: return jsonify(data)
        return jsonify(data)
    except Exception as e:
        logger.error(f"API error for pair {pair} on tf {timeframe}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Внутрішня помилка сервера"}), 500

@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []
    try:
        ranked_crypto_data = rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto')
        stocks_data = [{'ticker': p, 'active': True} for p in STOCK_TICKERS]
        sorted_stocks = sort_pairs_by_activity(stocks_data)
        forex_data = {}
        for session, pairs in FOREX_SESSIONS.items():
            session_data = [{'ticker': p, 'active': True} for p in pairs]
            forex_data[session] = sort_pairs_by_activity(session_data)
        return jsonify({
            "watchlist": watchlist,
            "crypto": ranked_crypto_data,
            "forex": forex_data,
            "stocks": sorted_stocks
        })
    except Exception as e:
        logger.error(f"API error for ranked pairs: {e}\n{traceback.format_exc()}")
        return jsonify({"error_message": "Помилка при завантаженні списків."})

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v5.0 Final"

# ... (решта ендпоінтів без змін)