# bot.py
import traceback
import json
from urllib.parse import parse_qs
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS, FOREX_PAIRS_MAP
from db import init_db, get_watchlist
# Змінено: Імпортуємо нову функцію get_api_mta_data
from analysis import get_api_detailed_signal_data, rank_assets, get_api_mta_data
import telegram_ui

CORS(app)

@app.before_request
def log_request():
    logger.info(f"[{request.method}] {request.path} - args={request.args.to_dict()}")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    # ... (код залишається без змін)
    return "OK", 200

@app.route("/api/signal", methods=["GET"])
def api_signal():
    # ... (код залишається без змін)
    return jsonify({})

@app.route("/api/get_pairs", methods=["GET"])
def api_get_pairs():
    # ... (код залишається без змін)
    return jsonify({})

@app.route("/api/get_active_markets", methods=["GET"])
def api_get_active_markets():
    # ... (код залишається без змін)
    return jsonify({})

# --- ПОЧАТОК НОВОГО КОДУ ---
@app.route("/api/get_mta", methods=["GET"])
def api_get_mta():
    """
    API endpoint для отримання даних мульти-таймфрейм аналізу.
    """
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    asset_type = 'stocks'
    if '/' in pair:
        asset_type = 'crypto' if 'USDT' in pair else 'forex'

    try:
        mta_data = get_api_mta_data(pair, asset_type)
        return jsonify(mta_data)
    except Exception as e:
        logger.error(f"API error for MTA on {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при розрахунку MTA"}), 500
# --- КІНЕЦЬ НОВОГО КОДУ ---

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v3.8 Backend with MTA API 🟢"

if __name__ != "__main__":
    init_db()