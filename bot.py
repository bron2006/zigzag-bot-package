# bot.py
import traceback
import json
from urllib.parse import parse_qs
from concurrent.futures import ThreadPoolExecutor
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
        
        # --- ПОЧАТОК ТЕСТОВИХ ЗМІН: Тимчасово вимикаємо сортування ---
        
        # Готуємо дані, як і раніше
        stocks_data = [{'ticker': p, 'active': True} for p in STOCK_TICKERS]
        forex_data = {}
        for session, pairs in FOREX_SESSIONS.items():
            forex_data[session] = [{'ticker': p, 'active': True} for p in pairs]

        # Функції сортування тимчасово не викликаються
        # sorted_stocks = sort_pairs_by_activity(stocks_data)
        # for session, pairs_data in forex_data.items():
        #     forex_data[session] = sort_pairs_by_activity(pairs_data)

        return jsonify({
            "watchlist": watchlist,
            "crypto": ranked_crypto_data,
            "forex": forex_data,       # Повертаємо невідсортовані дані
            "stocks": stocks_data      # Повертаємо невідсортовані дані
        })
        # --- КІНЕЦЬ ТЕСТОВИХ ЗМІН ---

    except Exception as e:
        logger.error(f"API error for ranked pairs: {e}\n{traceback.format_exc()}")
        return jsonify({
            "watchlist": watchlist,
            "crypto": [{'ticker': p, 'active': True} for p in CRYPTO_PAIRS_FULL],
            "forex": {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()},
            "stocks": [{'ticker': p, 'active': True} for p in STOCK_TICKERS],
            "error_message": "Помилка при сортуванні, показано стандартний список."
        })

@app.route("/api/get_pairs", methods=["GET"])
def api_get_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []
    return jsonify({ "watchlist": watchlist, "crypto": CRYPTO_PAIRS_FULL, "forex": FOREX_SESSIONS, "stocks": STOCK_TICKERS })

@app.route("/api/get_active_markets", methods=["GET"])
def api_get_active_markets():
    try:
        ranked_crypto = rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto')
        top_crypto = [p['ticker'] for p in ranked_crypto[:5]]
        top_stocks = []
        top_forex = []
        return jsonify({
            "active_crypto": top_crypto,
            "active_stocks": top_stocks,
            "active_forex": top_forex
        })
    except Exception as e:
        logger.error(f"API error for active markets: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при аналізі ринків"}), 500

@app.route("/api/get_mta", methods=["GET"])
def api_get_mta():
    pair = request.args.get("pair")
    if not pair: return jsonify({"error": "pair is required"}), 400
    asset_type = 'stocks'
    if '/' in pair: asset_type = 'crypto' if 'USDT' in pair else 'forex'
    try:
        mta_data = get_api_mta_data(pair, asset_type)
        return jsonify(mta_data)
    except Exception as e:
        logger.error(f"API error for MTA on {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при розрахунку MTA"}), 500

@app.route("/api/toggle_watchlist", methods=["GET"])
def toggle_watchlist_route():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id or not pair:
        return jsonify({"success": False, "error": "Missing required parameters"}), 400
    try:
        toggle_watch(user_id, pair)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in toggle_watchlist: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/api/signal_history", methods=["GET"])
def api_signal_history():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id: return jsonify({"error": "Not authorized"}), 401
    if not pair: return jsonify({"error": "pair is required"}), 400
    try:
        history = get_signal_history(user_id, pair)
        return jsonify(history)
    except Exception as e:
        logger.error(f"API error for signal history on {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при отриманні історії"}), 500

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v4.5 Backend with Watchlist & Timeframe API 🟢"

if __name__ != "__main__":
    init_db()