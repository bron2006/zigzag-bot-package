# bot.py
import traceback
import json
from urllib.parse import parse_qs, urlencode
from concurrent.futures import ThreadPoolExecutor
from flask import request, jsonify, render_template
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler
import requests

from config import (
    app, bot, dp, WEBHOOK_SECRET, logger,
    CT_CLIENT_ID, CT_CLIENT_SECRET, CT_REDIRECT_URI,
    CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCK_TICKERS, FOREX_PAIRS_MAP
)
from db import (
    init_db, get_watchlist, toggle_watch, get_signal_history,
    save_ctrader_token, create_oauth_state, get_user_id_by_state
)
from analysis import get_api_detailed_signal_data, rank_assets_for_api, get_api_mta_data
import telegram_ui

CORS(app)

# ... (функція _get_user_id_from_request залишається без змін) ...
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

def connect_ctrader(update, context):
    user_id = update.message.from_user.id
    state = create_oauth_state(user_id)
    
    auth_params = {
        'client_id': CT_CLIENT_ID,
        'redirect_uri': CT_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'trading',
        'state': state
    }
    auth_url = f"https://connect.spotware.com/oauth/v2/auth?{urlencode(auth_params)}"
    
    keyboard = [[InlineKeyboardButton("✅ Увійти через cTrader", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "Натисніть кнопку нижче, щоб безпечно підключити свій акаунт cTrader:",
        reply_markup=reply_markup
    )
dp.add_handler(CommandHandler("connect", connect_ctrader))


@app.route('/callback')
def callback():
    code = request.args.get("code")
    state = request.args.get("state")

    # --- ПОЧАТОК ЗМІН: Робимо state необов'язковим для тестування ---
    if not code:
        return "Authorization code not found.", 400

    user_id = None
    if state:
        user_id = get_user_id_by_state(state)

    if not user_id:
        logger.warning(f"State parameter was not found or was invalid. Falling back to mock_user_id for testing.")
        user_id = 12345 # Повертаємо mock_user_id для тестування
    else:
        logger.info(f"State validated. User ID {user_id} is being authorized.")
    # --- КІНЕЦЬ ЗМІН ---

    token_url = "https://connect.spotware.com/oauth/v2/token"
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': CT_REDIRECT_URI,
        'client_id': CT_CLIENT_ID,
        'client_secret': CT_CLIENT_SECRET
    }

    try:
        response = requests.post(token_url, data=payload)
        response.raise_for_status()

        token_data = response.json()
        access_token = token_data.get('accessToken')
        refresh_token = token_data.get('refreshToken')
        expires_in = token_data.get('expiresIn')

        logger.info(f"Successfully exchanged code for access token for user {user_id}")

        save_ctrader_token(user_id, access_token, refresh_token, expires_in)
        logger.info(f"Token for user {user_id} saved to DB.")

        return (f"<h1>Success!</h1>"
                f"<p>Your token has been securely saved. You can close this window.</p>")

    except requests.exceptions.RequestException as e:
        logger.error(f"Error exchanging code for token for user {user_id}: {e}")
        return f"Error exchanging code for token: {e}", 500


# ... (решта API маршрутів залишається без змін) ...
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

@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []

    try:
        ranked_crypto_data = rank_assets_for_api(CRYPTO_PAIRS_FULL, 'crypto')
        ranked_crypto = [{'ticker': p['ticker'], 'active': bool(p['score'] != -1)} for p in ranked_crypto_data]

        static_stocks = [{'ticker': p, 'active': True} for p in STOCK_TICKERS]
        static_forex = {
            session: [{'ticker': p, 'active': True} for p in pairs]
            for session, pairs in FOREX_SESSIONS.items()
        }

        return jsonify({
            "watchlist": watchlist,
            "crypto": ranked_crypto,
            "forex": static_forex,
            "stocks": static_stocks
        })
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
    if not user_id:
        return jsonify({"error": "Not authorized"}), 401
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    try:
        history = get_signal_history(user_id, pair)
        return jsonify(history)
    except Exception as e:
        logger.error(f"API error for signal history on {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при отриманні історії"}), 500

@app.route('/')
def homepage():
    return render_template('index.html')

if __name__ != "__main__":
    init_db()