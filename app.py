import logging
import os
import json
import time
import threading
import traceback
from functools import wraps
from flask import Flask, jsonify, send_from_directory, Response, request
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

import crochet
crochet.setup()

import state
from auth import is_valid_init_data, get_user_id_from_init_data
from db import get_watchlist, toggle_watchlist
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret, 
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS # <-- НОВИЙ ІМПОРТ
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

from twisted.internet import reactor
from analysis import get_api_detailed_signal_data, PERIOD_MAP

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            logger.warning(f"Unauthorized API access attempt. Path: {request.path}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def on_ctrader_ready():
    logger.info("cTrader client is ready. Loading symbols...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.all_symbol_names = [s.symbolName for s in symbols_response.symbol]
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Successfully loaded {len(state.symbol_cache)} light symbols.")
    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

def symbols_command(update: Update, context: CallbackContext):
    if not state.SYMBOLS_LOADED or not hasattr(state, 'all_symbol_names'):
        update.message.reply_text("Список символів ще не завантажено. Спробуйте за хвилину.")
        return
    
    forex = sorted([s for s in state.all_symbol_names if "/" in s and len(s) < 8 and "USD" not in s.upper()])
    crypto_usd = sorted([s for s in state.all_symbol_names if "/USD" in s.upper()])
    crypto_usdt = sorted([s for s in state.all_symbol_names if "/USDT" in s.upper()])
    others = sorted([s for s in state.all_symbol_names if "/" not in s])

    message = "**Доступні символи від брокера:**\n\n"
    if forex: message += f"**Forex:**\n`{', '.join(forex)}`\n\n"
    if crypto_usd: message += f"**Crypto (USD):**\n`{', '.join(crypto_usd)}`\n\n"
    if crypto_usdt: message += f"**Crypto (USDT):**\n`{', '.join(crypto_usdt)}`\n\n"
    if others: message += f"**Indices/Stocks/Commodities:**\n`{', '.join(others)}`"
    
    for i in range(0, len(message), 4096):
        update.message.reply_text(message[i:i + 4096], parse_mode='Markdown')

def start_background_services():
    logger.info("Initializing background services (Telegram, cTrader)...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found!")
        return

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.updater = updater
    state.client = client

    import telegram_ui
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(CommandHandler("symbols", symbols_command))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))

    updater.start_polling()
    logger.info("Telegram bot started.")

    client.on("ready", on_ctrader_ready)
    client.start()
    logger.info("cTrader client started.")

@app.route("/")
def home():
    try:
        with open(os.path.join(WEBAPP_DIR, "index.html"), "r", encoding="utf-8") as f:
            content = f.read()
        app_name = get_fly_app_name()
        if not app_name:
            app_name = "zigzag-bot-package"
        api_base_url = f"https://{app_name}.fly.dev"
        cache_buster = int(time.time())
        content = content.replace("{{API_BASE_URL}}", api_base_url)
        content = content.replace("script.js", f"script.js?v={cache_buster}")
        content = content.replace("style.css", f"style.css?v={cache_buster}")
        return Response(content, mimetype='text/html')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}", exc_info=True)
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

@app.route("/api/get_pairs")
@protected_route
def get_pairs():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    watchlist = get_watchlist(user_id) if user_id else []

    # --- ПОЧАТОК ЗМІН: Змінюємо структуру відповіді для Forex ---
    forex_data = [
        {
            "title": f"{name} {TRADING_HOURS.get(name, '')}".strip(),
            "pairs": pairs
        }
        for name, pairs in FOREX_SESSIONS.items()
    ]
    # --- КІНЕЦЬ ЗМІН ---

    return jsonify({
        "forex": forex_data, 
        "crypto": CRYPTO_PAIRS, 
        "stocks": STOCK_TICKERS,
        "commodities": COMMODITIES, 
        "watchlist": watchlist 
    })

@app.route("/api/toggle_watchlist")
@protected_route
def toggle_watchlist_route():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    pair = request.args.get("pair")

    if not user_id or not pair:
        return jsonify({"success": False, "error": "Missing parameters"}), 400

    try:
        pair_normalized = pair.replace("/", "")
        toggle_watchlist(user_id, pair_normalized)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in toggle_watchlist for user {user_id}: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/api/signal")
@protected_route
def api_signal():
    pair = request.args.get("pair")
    timeframe = request.args.get("timeframe", "15m")
    
    if timeframe not in PERIOD_MAP:
        return jsonify({"error": "Invalid timeframe"}), 400

    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    pair_normalized = pair.replace("/", "")
    user_id = get_user_id_from_init_data(request.args.get("initData"))

    if not state.client or not state.client.is_authorized:
        return jsonify({"error": "cTrader client is not connected..."}), 503
        
    if not state.SYMBOLS_LOADED or pair_normalized not in state.symbol_cache:
        return jsonify({"error": f"Symbol data not loaded or '{pair}' not found..."}), 503

    logger.info(f"Received signal request for pair: {pair}, timeframe: {timeframe}")

    @crochet.run_in_reactor
    def do_analysis_and_get_result():
        deferred = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_normalized, user_id, timeframe)
        return deferred

    try:
        result = do_analysis_and_get_result().wait(timeout=30)
        return jsonify(result)
    except crochet.TimeoutError:
        logger.error(f"Request timed out for pair: {pair}")
        return jsonify({"error": "Request timed out"}), 504
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"Error in signal API for {pair}: {e}\n{tb_str}")
        return jsonify({
            "error": "Internal server error", "details": str(e), "traceback": tb_str
        }), 500

if __name__ != "__main__":
    start_background_services()