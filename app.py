# app.py
import logging
import os
import json
import time
import queue
import traceback
from functools import wraps

# Twisted + WSGI
# MODIFIED: Додаємо 'defer' для виправлення запуску
from twisted.internet import reactor, threads, defer
from twisted.internet.task import LoopingCall
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource

# Flask
from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context

# Telegram
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

# Local modules
import state
import telegram_ui
from auth import is_valid_init_data, get_user_id_from_init_data
from db import get_watchlist, toggle_watchlist
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from analysis import get_api_detailed_signal_data, PERIOD_MAP
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("app")

# Flask app
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

# Ensure state has required attributes
if not hasattr(state, "sse_queue"):
    state.sse_queue = queue.Queue()
if not hasattr(state, "scanner_cooldown_cache"):
    state.scanner_cooldown_cache = {}
if not hasattr(state, "latest_analysis_cache"):
    state.latest_analysis_cache = {}
if not hasattr(state, "SCANNER_ENABLED"):
    state.SCANNER_ENABLED = True

# Twisted-ready deferred flag for cTrader readiness
_client_ready = {"ready": False}

def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            logger.warning(f"Unauthorized API access attempt. Path: {request.path}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --------------- Scanner (uses analysis.get_api_detailed_signal_data) ---------------
def scan_markets_once():
    if not getattr(state, "SCANNER_ENABLED", False):
        logger.debug("Scanner disabled, skipping run.")
        return

    logger.info("SCANNER: Starting market scan...")
    all_forex_pairs = list(set([p for sess in FOREX_SESSIONS.values() for p in sess]))
    chat_id = get_chat_id()

    def _on_done(result, pair_name):
        try:
            if result.get("error"):
                logger.debug(f"SCANNER: analysis error for {pair_name}: {result.get('error')}")
                return
            score = result.get("bull_percentage", 50)
            is_signal = score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD)
            if is_signal:
                now = time.time()
                last = state.scanner_cooldown_cache.get(pair_name, 0)
                if (now - last) > SCANNER_COOLDOWN_SECONDS:
                    logger.info(f"SCANNER: Signal for {pair_name} (score {score}). Notifying.")
                    state.latest_analysis_cache[pair_name] = result
                    try:
                        state.sse_queue.put(result, block=False)
                    except queue.Full:
                        logger.warning("SSE queue full, dropping signal")
                    if chat_id and getattr(state, "updater", None):
                        try:
                            message = telegram_ui._format_signal_message(result, "5m")
                            keyboard = telegram_ui.get_main_menu_kb()
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                        except Exception as e:
                            logger.exception(f"Failed to send telegram notification: {e}")
                    state.scanner_cooldown_cache[pair_name] = now
                else:
                    logger.debug(f"SCANNER: {pair_name} on cooldown.")
        except Exception:
            logger.exception("SCANNER: error in _on_done")

    def worker():
        for pair in all_forex_pairs:
            norm = pair.replace("/", "")
            try:
                d = get_api_detailed_signal_data(state.client, state.symbol_cache, norm, 0, "5m")
                done_q = queue.Queue()
                def cb_success(res): done_q.put(res)
                def cb_err(f): done_q.put({"error": str(f)})
                d.addCallbacks(cb_success, cb_err)
                res = done_q.get(timeout=65)
                _on_done(res, norm)
            except Exception:
                logger.exception(f"SCANNER: Failed processing {norm}")
    threads.deferToThread(worker)

# --------------- cTrader event handlers ---------------
def on_ctrader_ready():
    logger.info("cTrader client ready — loading symbols")
    d = state.client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.all_symbol_names = [s.symbolName for s in symbols_response.symbol]
        state.SYMBOLS_LOADED = True
        logger.info(f"Loaded {len(state.symbol_cache)} symbols.")
        _client_ready["ready"] = True
        scanner_loop = LoopingCall(scan_markets_once)
        scanner_loop.start(60, now=False)
    except Exception:
        logger.exception("on_symbols_loaded error")

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")
    _client_ready["ready"] = False

# --------------- Flask routes ---------------
@app.route("/")
def home():
    try:
        with open(os.path.join(WEBAPP_DIR, "index.html"), "r", encoding="utf-8") as f:
            content = f.read()
        app_name = get_fly_app_name() or "zigzag-bot-package"
        api_base_url = f"https://{app_name}.fly.dev"
        cache_buster = int(time.time())
        content = content.replace("{{API_BASE_URL}}", api_base_url)
        content = content.replace("script.js", f"script.js?v={cache_buster}")
        content = content.replace("style.css", f"style.css?v={cache_buster}")
        return Response(content, mimetype='text/html')
    except Exception as e:
        logger.exception("Error serving index.html")
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

# ... (інші Flask-маршрути залишаються без змін)

# --------------- Startup (Twisted reactor integrates Flask WSGI) ---------------
def start_services():
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")
    else:
        logger.info("Starting Telegram Updater.")
        updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        state.updater = updater
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
        dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        
        # FIX 1: Запускаємо Telegram-бота напряму, без reactor.callInThread
        updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram updater started in its own thread.")

    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        state.client = client
        client.on("ready", on_ctrader_ready)
        
        # FIX 2: Використовуємо defer.ensureDeferred для безпечного запуску cTrader-клієнта
        reactor.callWhenRunning(lambda: defer.ensureDeferred(client.start()))
        logger.info("cTrader client scheduled to start.")
    except Exception:
        logger.exception("Failed to initialize cTrader client")

def main():
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    start_services()

    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()