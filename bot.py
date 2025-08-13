# bot.py
import traceback
import json
from urllib.parse import parse_qs, unquote
from flask import request, jsonify, send_from_directory
from flask_cors import CORS
from telegram import Update

from config import app, bot, dp, WEBHOOK_SECRET, logger, CRYPTO_PAIRS_FULL, FOREX_SESSIONS, MY_TELEGRAM_ID, CTRADER_ACCESS_TOKEN, CTRADER_REFRESH_TOKEN
from db import init_db, get_watchlist, toggle_watch, get_signal_history, get_ctrader_token, save_ctrader_token
from analysis import get_api_detailed_signal_data, rank_assets_for_api, get_api_mta_data
import telegram_ui

CORS(app)

def _get_user_id_from_request(req):
    init_data = req.args.get("initData")
    if not init_data:
        return int(MY_TELEGRAM_ID) if MY_TELEGRAM_ID else None
    try:
        decoded_init_data = unquote(init_data)
        parsed = parse_qs(decoded_init_data)
        user_json_str = parsed.get("user", [None])[0]
        if user_json_str:
            return json.loads(user_json_str).get("id")
    except Exception as e:
        logger.warning(f"Failed to parse initData: {e}")
    return int(MY_TELEGRAM_ID) if MY_TELEGRAM_ID else None

def init_ctrader_token():
    if not MY_TELEGRAM_ID or not CTRADER_ACCESS_TOKEN or not CTRADER_REFRESH_TOKEN:
        logger.warning("Змінні середовища для cTrader не встановлені. Пропускаю ініціалізацію токену.")
        return
    try:
        user_id = int(MY_TELEGRAM_ID)
        if get_ctrader_token(user_id) is None:
            logger.info(f"Токен cTrader для користувача {user_id} не знайдено. Зберігаю з секретів...")
            save_ctrader_token(user_id, CTRADER_ACCESS_TOKEN, CTRADER_REFRESH_TOKEN, expires_in=3600)
            logger.info("Токен cTrader успішно збережено в базу даних.")
        else:
            logger.info(f"Токен cTrader для користувача {user_id} вже існує в базі даних.")
    except Exception as e:
        logger.error(f"Помилка під час ініціалізації токену cTrader: {e}")

@app.before_request
def log_request():
    if request.path.startswith(('/script.js', '/style.css')) or request.path in ['/health', '/favicon.ico']:
        return
    logger.info(f"[{request.method}] {request.path}")

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
    user_id = _get_user_id_from_request(request)
    if not pair: return jsonify({"error": "pair is required"}), 400
    try:
        data = get_api_detailed_signal_data(pair, user_id=user_id)
        if "error" in data: return jsonify(data), 500
        return jsonify(data)
    except Exception as e:
        logger.error(f"API error for pair {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Внутрішня помилка сервера"}), 500

@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []
    try:
        ranked_crypto_data = rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto', user_id=user_id)
        ranked_crypto = [{'ticker': p['ticker'], 'active': bool(p['score'] != -1)} for p in ranked_crypto_data]
        # --- ВИДАЛЕНО 'stocks' З ВІДПОВІДІ ---
        static_forex = { session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items() }
        return jsonify({ "watchlist": watchlist, "crypto": ranked_crypto, "forex": static_forex, "stocks": [] })
    except Exception as e:
        logger.error(f"API error for ranked pairs: {e}\n{traceback.format_exc()}")
        return jsonify({ "watchlist": watchlist, "crypto": [{'ticker': p, 'active': True} for p in CRYPTO_PAIRS_FULL], "forex": {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()}, "stocks": [], "error_message": "Помилка при сортуванні, показано стандартний список." })

@app.route("/api/get_mta", methods=["GET"])
def api_get_mta():
    pair = request.args.get("pair")
    user_id = _get_user_id_from_request(request)
    if not pair: return jsonify({"error": "pair is required"}), 400
    asset_type = 'stocks'
    if '/' in pair: asset_type = 'crypto' if 'USDT' in pair else 'forex'
    try:
        mta_data = get_api_mta_data(pair, asset_type, user_id=user_id)
        return jsonify(mta_data)
    except Exception as e:
        logger.error(f"API error for MTA on {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при розрахунку MTA"}), 500

@app.route("/api/toggle_watchlist", methods=["GET"])
def toggle_watchlist_route():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id or not pair: return jsonify({"success": False, "error": "Missing required parameters"}), 400
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

@app.route('/health')
def health_check():
    return "OK", 200

@app.route('/')
def serve_index():
    return send_from_directory('webapp', 'index.html')

@app.route('/<path:filename>')
def serve_webapp_files(filename):
    return send_from_directory('webapp', filename)

if __name__ != "__main__":
    with app.app_context():
        init_db()
        init_ctrader_token()
    telegram_ui.register_handlers(dp)
# --- БЛОК ДЛЯ НАЛАГОДЖЕННЯ ВИДАЛЕНО ---