# app.py
import logging
import os
import json
import time
import threading
from flask import Flask, jsonify, send_from_directory, Response, request
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

# --- ПОЧАТОК ЗМІН: Інтегруємо crochet ---
import crochet
crochet.setup()
# --- КІНЕЦЬ ЗМІН ---

import state
from spotware_connect import SpotwareConnect
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS, get_fly_app_name
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

from twisted.internet import reactor
from analysis import get_api_detailed_signal_data
from mta_analysis import get_mta_signal

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

def on_ctrader_ready():
    logger.info("cTrader client is ready. Loading symbols...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Successfully loaded {len(state.symbol_cache)} light symbols.")
    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

# --- ПОЧАТОК ЗМІН: Спрощуємо запуск сервісів, crochet керує реактором ---
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
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))

    updater.start_polling()
    logger.info("Telegram bot started.")

    client.on("ready", on_ctrader_ready)
    # Запускаємо клієнт; crochet вже запустив реактор у фоні
    client.start()
    logger.info("cTrader client started.")
# --- КІНЕЦЬ ЗМІН ---

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
def get_pairs():
    return jsonify({
        "forex": FOREX_SESSIONS,
        "watchlist": [], "crypto": [], "stocks": []
    })

# --- ПОЧАТОК ЗМІН: Використовуємо crochet для безпечних асинхронних викликів ---
@app.route("/api/signal")
def api_signal():
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    logger.info(f"Received signal request for pair: {pair}")

    @crochet.run_in_reactor
    def do_analysis_and_get_result():
        # Ця функція тепер виконується в безпечному потоці Twisted
        deferred = get_api_detailed_signal_data(state.client, state.symbol_cache, pair, 0)
        return deferred

    try:
        # crochet.wait чекає на результат, не блокуючи GIL
        result = do_analysis_and_get_result(timeout=30)
        return jsonify(result)
    except crochet.TimeoutError:
        logger.error(f"Request timed out for pair: {pair}")
        return jsonify({"error": "Request timed out"}), 504
    except Exception as e:
        logger.error(f"Error in signal API for {pair}: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/get_mta")
def api_get_mta():
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "pair is required"}), 400

    @crochet.run_in_reactor
    def do_mta_and_get_result():
        deferred = get_mta_signal(state.client, pair)
        return deferred

    try:
        result = do_mta_and_get_result(timeout=5)
        return jsonify(result)
    except Exception:
        return jsonify([]), 200
# --- КІНЕЦЬ ЗМІН ---

if __name__ != "__main__":
    start_background_services()