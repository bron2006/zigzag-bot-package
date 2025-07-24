# bot.py
import traceback
import json
from urllib.parse import parse_qs
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS, FOREX_PAIRS_MAP
from db import init_db, get_watchlist
from analysis import get_api_detailed_signal_data, rank_assets_for_api, get_api_mta_data
import telegram_ui

CORS(app)

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
    if not pair: return jsonify({"error": "pair is required"}), 400
    try:
        data = get_api_detailed_signal_data(pair)
        if "error" in data: return jsonify(data)
        return jsonify(data)
    except Exception as e:
        logger.error(f"API error for pair {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Внутрішня помилка сервера"}), 500

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
    return jsonify({ "watchlist": watchlist, "crypto": CRYPTO_PAIRS_FULL, "forex": FOREX_SESSIONS, "stocks": STOCK_TICKERS })

@app.route("/api/get_active_markets", methods=["GET"])
def api_get_active_markets():
    try:
        ranked_crypto = rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto')
        top_crypto = [p['ticker'] for p in ranked_crypto[:5]]
        ranked_stocks = rank_assets_for_api(STOCK_TICKERS, 'stocks')
        top_stocks = [p['ticker'] for p in ranked_stocks[:5]]
        all_forex_pairs = list(FOREX_PAIRS_MAP.keys())
        ranked_forex = rank_assets_for_api(all_forex_pairs, 'forex')
        top_forex = [p['ticker'] for p in ranked_forex[:5]]
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
    if '/' in pair:
        asset_type = 'crypto' if 'USDT' in pair else 'forex'
    try:
        mta_data = get_api_mta_data(pair, asset_type)
        return jsonify(mta_data)
    except Exception as e:
        logger.error(f"API error for MTA on {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при розрахунку MTA"}), 500

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v3.9 Final Stable 🟢"

if __name__ != "__main__":
    init_db()