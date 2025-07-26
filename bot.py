# bot.py
import traceback
import json
from urllib.parse import parse_qs
from flask import request, jsonify
from flask_cors import CORS
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS, FOREX_PAIRS_MAP
# --- Змінено: Імпортуємо функцію для отримання історії ---
from db import init_db, get_watchlist, toggle_watch, get_signal_history
from analysis import (
    get_api_detailed_signal_data,
    rank_assets_for_api,
    get_api_mta_data,
    get_signal_strength_verdict # Додано, бо використовується в get_api_detailed_signal_data
)
import telegram_ui

CORS(app)

# --- НОВЕ: Допоміжна функція для отримання user_id ---
def _get_user_id_from_request(req):
    """Отримує user_id з параметру initData."""
    init_data = req.args.get("initData")
    if not init_data: return None
    try:
        parsed = parse_qs(init_data)
        user_json_str = parsed.get("user", [None])[0]
        if user_json_str:
            return json.loads(user_json_str).get("id")
    except Exception as e:
        logger.warning(f"Не вдалося розпарсити initData: {e}")
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
        logger.error(f"Помилка вебхука: {e}\n{traceback.format_exc()}")
    return "OK", 200

@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    if not pair: return jsonify({"error": "pair is required"}), 400
    
    # Змінено: Використовуємо допоміжну функцію для отримання user_id
    user_id = _get_user_id_from_request(request)
    try:
        # get_api_detailed_signal_data тепер не зберігає історію,
        # це робить get_signal_strength_verdict
        data = get_api_detailed_signal_data(pair)
        if "error" in data: return jsonify(data), 400
        return jsonify(data)
    except Exception as e:
        logger.error(f"Помилка API для пари {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Внутрішня помилка сервера"}), 500

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
        ranked_stocks = rank_assets_for_api(STOCK_TICKERS, 'stocks')
        top_stocks = [p['ticker'] for p in ranked_stocks[:5]]
        all_forex_pairs = list(FOREX_PAIRS_MAP.keys())
        ranked_forex = rank_assets_for_api(all_forex_pairs, 'forex')
        top_forex = [p['ticker'] for p in ranked_forex[:5]]
        return jsonify({ "active_crypto": top_crypto, "active_stocks": top_stocks, "active_forex": top_forex })
    except Exception as e:
        logger.error(f"Помилка API для активних ринків: {e}\n{traceback.format_exc()}")
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
        logger.error(f"Помилка API для MTA на {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при розрахунку MTA"}), 500

# --- НОВЕ: API-маршрут для отримання історії сигналів ---
@app.route("/api/signal_history", methods=["GET"])
def api_signal_history():
    pair = request.args.get("pair")
    user_id = _get_user_id_from_request(request)

    if not user_id:
        return jsonify({"error": "Не авторизовано"}), 401
    if not pair:
        return jsonify({"error": "Необхідно вказати пару"}), 400
    
    try:
        history = get_signal_history(user_id, pair)
        return jsonify(history)
    except Exception as e:
        logger.error(f"Помилка API для історії сигналів на {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при отриманні історії"}), 500

@app.route("/api/toggle_watchlist", methods=["GET"])
def toggle_watchlist_route():
    pair = request.args.get("pair")
    user_id = _get_user_id_from_request(request)
    if not user_id or not pair:
        return jsonify({"success": False, "error": "Відсутні необхідні параметри"}), 400
    try:
        toggle_watch(user_id, pair)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Помилка в toggle_watchlist: {e}")
        return jsonify({"success": False, "error": "Внутрішня помилка сервера"}), 500

@app.route("/", methods=["GET"])
def index():
    return "ZigZag Bot v4.3 Backend with Watchlist API 🟢"

if __name__ != "__main__":
    init_db()