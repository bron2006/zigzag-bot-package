# app.py
import logging
import os
import json
import time
import queue
from functools import wraps
import itertools

# Twisted imports
from twisted.internet import reactor, threads
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.task import LoopingCall
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource

# Flask imports
from flask import Flask, jsonify, send_from_directory, Response, request

# Telegram imports
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

# Local imports
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
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data, PERIOD_MAP

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")
_client_ready_deferred = Deferred()

# --- Helper Functions ---
def set_client_ready_deferred(d):
    global _client_ready_deferred
    _client_ready_deferred = d

def wait_client_ready():
    return _client_ready_deferred

def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- Scanner Logic (Twisted Native) ---
def scan_markets():
    # MODIFIED: Використовуємо блокування для безпечного читання стану сканера
    with state.scanner_lock:
        is_enabled = state.SCANNER_ENABLED
    
    if not is_enabled:
        return

    logger.info("SCANNER: Starting sequential market scan...")
    all_forex_pairs = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
    chat_id = get_chat_id()
        
    def on_analysis_done(result, pair_name):
        try:
            if not result.get("error"):
                state.latest_analysis_cache[pair_name] = result
                score = result.get('bull_percentage', 50)
                if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                    now = time.time()
                    if (now - state.scanner_cooldown_cache.get(pair_name, 0)) > SCANNER_COOLDOWN_SECONDS:
                        logger.info(f"SCANNER: Ideal entry for {pair_name}. Notifying.")
                        state.sse_queue.put(result)
                        if chat_id:
                            message = telegram_ui._format_signal_message(result, "5m")
                            keyboard = telegram_ui.get_main_menu_kb()
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                        state.scanner_cooldown_cache[pair_name] = now
        except Exception as e:
            logger.error(f"SCANNER: Error in on_analysis_done for {pair_name}: {e}", exc_info=True)

    @inlineCallbacks
    def process_all_pairs():
        for pair in all_forex_pairs:
            norm_pair = pair.replace("/", "")
            try:
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
                on_analysis_done(result, norm_pair)
            except Exception as e:
                logger.error(f"SCANNER: Error analyzing {norm_pair}: {e}")
        logger.info("SCANNER: Sequential scan finished.")

    threads.deferToThread(process_all_pairs)

# --- cTrader Event Handlers (Twisted Native) ---
def on_ctrader_ready():
    logger.info("cTrader client is ready. Loading symbols...")
    d = state.client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.all_symbol_names = [s.symbolName for s in symbols_response.symbol]
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Successfully loaded {len(state.symbol_cache)} light symbols.")
        
        scanner_loop = LoopingCall(scan_markets)
        scanner_loop.start(60, now=True)
        _client_ready_deferred.callback(True)
    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)
        _client_ready_deferred.errback(e)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")
    _client_ready_deferred.errback(failure)

# --- Flask Routes ---
@app.route("/")
def home():
    try:
        with open(os.path.join(WEBAPP_DIR, "index.html"), "r", encoding="utf-8") as f: content = f.read()
        app_name = get_fly_app_name() or "zigzag-bot-package"
        api_base_url = f"https://{app_name}.fly.dev"
        cache_buster = int(time.time())
        content = content.replace("{{API_BASE_URL}}", api_base_url)
        content = content.replace("script.js", f"script.js?v={cache_buster}")
        content = content.replace("style.css", f"style.css?v={cache_buster}")
        return Response(content, mimetype='text/html')
    except Exception as e:
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

@app.route("/api/get_pairs")
@protected_route
def get_pairs():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    watchlist = get_watchlist(user_id) if user_id else []
    forex_data = [{"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs} for name, pairs in FOREX_SESSIONS.items()]
    return jsonify({"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist})

@app.route("/api/toggle_watchlist")
@protected_route
def toggle_watchlist_route():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    pair = request.args.get("pair")
    if not user_id or not pair: return jsonify({"success": False, "error": "Missing parameters"}), 400
    success = toggle_watchlist(user_id, pair.replace("/", ""))
    return jsonify({"success": success})

@app.route("/api/signal")
@protected_route
def api_signal():
    pair_normalized = (request.args.get("pair") or "").replace("/", "")
    if not pair_normalized: return jsonify({"error": "pair is required"}), 400
    
    cached_result = state.latest_analysis_cache.get(pair_normalized)
    if cached_result:
        return jsonify(cached_result)
    else:
        return jsonify({"error": "Дані для цього активу ще аналізуються сканером. Спробуйте за хвилину."}), 404

@app.route("/api/scanner/status")
@protected_route
def get_scanner_status():
    # MODIFIED: Використовуємо блокування для безпечного читання
    with state.scanner_lock:
        is_enabled = state.SCANNER_ENABLED
    return jsonify({"enabled": is_enabled})

@app.route("/api/scanner/toggle")
@protected_route
def toggle_scanner_status():
    # MODIFIED: Використовуємо блокування для безпечної зміни стану
    with state.scanner_lock:
        state.SCANNER_ENABLED = not state.SCANNER_ENABLED
        new_status = state.SCANNER_ENABLED
    logger.info(f"Scanner status toggled via API. New status: {new_status}")
    return jsonify({"enabled": new_status})

@app.route("/api/signal-stream")
@protected_route
def signal_stream():
    def generate():
        while True:
            try:
                signal_data = state.sse_queue.get(timeout=20)
                yield f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield ": ping\n\n"
    
    # MODIFIED: Прибираємо stream_with_context та додаємо заголовок Content-Encoding
    # для запобігання буферизації на проксі-серверах (Fly.io)
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Content-Encoding'] = 'identity' # NEW
    return response

# --- Main Application Startup ---
if __name__ == "__main__":
    # 1. Initialize Telegram Bot
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    # --- ПОЧАТОК ЗМІН: Використовуємо функцію з telegram_ui ---
    dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
    # --- КІНЕЦЬ ЗМІН ---
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    
    reactor.callInThread(updater.start_polling)
    logger.info("Telegram bot scheduled to start in a background thread.")
    
    # 2. Initialize cTrader Client
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client scheduled to start.")
    
    # 3. Create a Twisted Web server resource for the Flask app
    wsgi_resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(wsgi_resource)
    
    # 4. Start the Twisted reactor and listen for web requests
    port = int(os.environ.get("PORT", 8080))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Starting Twisted server on port {port}...")
    reactor.run()