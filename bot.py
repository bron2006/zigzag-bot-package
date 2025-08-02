# bot.py
import traceback
import json
from urllib.parse import parse_qs
from flask import request, jsonify, g
from flask_cors import CORS
from telegram import Update
from telegram.ext import CommandHandler
import requests
import config # <-- Важливий імпорт

# Перший лог, як ви і пропонували
config.logger.info("⚙️ Bot module is being imported and initialized...")

from config import (
    app, bot, dp, WEBHOOK_SECRET,
    CT_CLIENT_ID, CT_CLIENT_SECRET, CT_REDIRECT_URI,
    CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS
)
from db import init_db, get_watchlist, toggle_watch, get_signal_history, save_ctrader_token
from analysis import get_api_detailed_signal_data, rank_assets_for_api, get_api_mta_data
import telegram_ui
from ctrader_api import get_trading_accounts, get_valid_access_token

CORS(app)

@app.before_request
def setup_and_log():
    if not hasattr(g, '_database_initialized'):
        config.logger.info("💾 Initializing database for the first time...")
        init_db()
        g._database_initialized = True
    config.logger.info(f"➡️ [{request.method}] {request.path} - args={request.args.to_dict()}")

def _get_user_id_from_request(req):
    init_data = req.args.get("initData")
    if not init_data: return None
    try:
        parsed = parse_qs(init_data)
        user_json_str = parsed.get("user", [None])[0]
        if user_json_str: return json.loads(user_json_str).get("id")
    except Exception as e:
        config.logger.warning(f"Failed to parse initData: {e}")
    return None

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dp.process_update(update)
    except Exception as e:
        config.logger.error(f"Webhook error: {e}\n{traceback.format_exc()}")
    return "OK", 200

@app.route('/callback')
def callback():
    code = request.args.get("code")
    if not code: return "Authorization code not found.", 400
    token_url = "https://connect.spotware.com/oauth/v2/token"
    payload = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': CT_REDIRECT_URI, 'client_id': CT_CLIENT_ID, 'client_secret': CT_CLIENT_SECRET}
    try:
        response = requests.post(token_url, data=payload, timeout=15)
        response.raise_for_status()
        token_data = response.json()
        user_id = 12345
        save_ctrader_token(user_id, token_data.get('accessToken'), token_data.get('refreshToken'), token_data.get('expiresIn'))
        config.logger.info(f"Token for user {user_id} saved to DB.")
        return "<h1>Success!</h1><p>Token saved. You can close this window.</p>"
    except requests.exceptions.RequestException as e:
        config.logger.error(f"Error exchanging code for token: {e}")
        return f"Error: {e}", 500

def my_accounts(update, context):
    user_id = 12345
    access_token = get_valid_access_token(user_id)
    if not access_token:
        update.message.reply_text("Токен доступу не знайдено.")
        return
    accounts = get_trading_accounts(access_token)
    if accounts is None: update.message.reply_text("Не вдалося отримати дані про рахунки.")
    elif not accounts: update.message.reply_text("На вашому акаунті не знайдено торгових рахунків.")
    else:
        message = "Ваші торгові рахунки:\n\n" + "\n".join([f"🔹 **ID:** `{acc.get('accountId')}`\n   **Брокер:** {acc.get('brokerName')}\n   **Баланс:** {acc.get('balance') / 100} {acc.get('currency')}\n" for acc in accounts])
        update.message.reply_text(message, parse_mode='Markdown')

dp.add_handler(CommandHandler("myaccounts", my_accounts))

@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    if not pair: return jsonify({"error": "pair is required"}), 400
    try:
        data = get_api_detailed_signal_data(pair)
        if "error" in data: return jsonify(data), 400
        return jsonify(data)
    except Exception as e:
        config.logger.error(f"API error for pair {pair}: {e}", exc_info=True)
        return jsonify({"error": "Внутрішня помилка сервера"}), 500

@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []
    try:
        ranked_crypto = [{'ticker': p['ticker'], 'active': p['score'] != -1} for p in rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto')]
        static_stocks = [{'ticker': p, 'active': True} for p in STOCK_TICKERS]
        static_forex = {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()}
        return jsonify({"watchlist": watchlist, "crypto": ranked_crypto, "forex": static_forex, "stocks": static_stocks})
    except Exception as e:
        config.logger.error(f"API error for ranked pairs: {e}", exc_info=True)
        return jsonify({"watchlist": watchlist, "crypto": [{'ticker': p, 'active': True} for p in CRYPTO_PAIRS_FULL], "forex": {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()}, "stocks": [{'ticker': p, 'active': True} for p in STOCK_TICKERS], "error_message": "Помилка сортування."})

@app.route("/api/get_mta", methods=["GET"])
def api_get_mta():
    pair = request.args.get("pair")
    if not pair: return jsonify({"error": "pair is required"}), 400
    asset_type = 'stocks' if '/' not in pair else ('crypto' if 'USDT' in pair else 'forex')
    try:
        return jsonify(get_api_mta_data(pair, asset_type))
    except Exception as e:
        config.logger.error(f"API error for MTA on {pair}: {e}", exc_info=True)
        return jsonify({"error": "Помилка розрахунку MTA"}), 500

@app.route("/api/toggle_watchlist", methods=["GET"])
def toggle_watchlist_route():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id or not pair: return jsonify({"success": False, "error": "Missing parameters"}), 400
    try:
        toggle_watch(user_id, pair)
        return jsonify({"success": True})
    except Exception as e:
        config.logger.error(f"Error in toggle_watchlist: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/api/signal_history", methods=["GET"])
def api_signal_history():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id: return jsonify({"error": "Not authorized"}), 401
    if not pair: return jsonify({"error": "pair is required"}), 400
    try:
        return jsonify(get_signal_history(user_id, pair))
    except Exception as e:
        config.logger.error(f"API error for signal history on {pair}: {e}", exc_info=True)
        return jsonify({"error": "Помилка отримання історії"}), 500

# --- ПОЧАТОК ЗМІН: Health check тепер залежить від прапора ---
@app.route('/')
def homepage():
    if config.HEALTH_READY:
        return "✅ Bot is ready", 200
    else:
        return "⏳ Still initializing...", 503 # Service Unavailable
# --- КІНЕЦЬ ЗМІН ---

# Запускаємо чергу завдань
dp.job_queue.start()

# --- ПОЧАТОК ЗМІН: Встановлюємо прапор готовності в кінці ініціалізації ---
config.HEALTH_READY = True
config.logger.info("✅ HEALTH_READY = True. Bot is fully operational.")
# --- КІНЕЦЬ ЗМІН ---