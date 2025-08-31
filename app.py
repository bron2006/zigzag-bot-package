# app.py
import logging
import os
import json
import time
from functools import wraps
import itertools

# Twisted imports
from twisted.internet import reactor, threads
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.task import LoopingCall
from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.static import File # NEW: For serving static files

# Klein import - REPLACES FLASK
from klein import Klein

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

app = Klein()

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")
_client_ready_deferred = Deferred()

# --- Native Klein SSE and Broadcast Implementation ---

def broadcast_sse_signal(signal_data):
    sse_formatted_data = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n".encode('utf-8')
    for client_request in list(state.sse_clients):
        reactor.callFromThread(client_request.write, sse_formatted_data)

# --- Helper Functions ---
def set_client_ready_deferred(d):
    global _client_ready_deferred
    _client_ready_deferred = d

def wait_client_ready():
    return _client_ready_deferred

def protected_route(f):
    @wraps(f)
    def decorated_function(instance, request, *args, **kwargs):
        init_data_list = request.args.get(b"initData")
        init_data = init_data_list[0].decode('utf-8') if init_data_list else None
        if not is_valid_init_data(init_data):
            request.setResponseCode(401)
            request.setHeader('Content-Type', 'application/json')
            return json.dumps({"success": False, "error": "Unauthorized"})
        return f(instance, request, *args, **kwargs)
    return decorated_function

# --- Scanner Logic (Twisted Native) ---
def scan_markets():
    with state.scanner_lock:
        is_enabled = state.SCANNER_ENABLED
    
    if not is_enabled:
        return

    logger.info("SCANNER: Starting sequential market scan...")
    assets_to_scan = CRYPTO_PAIRS
    logger.info(f"SCANNER: Weekend mode. Scanning crypto pairs: {assets_to_scan}")
    
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
                        broadcast_sse_signal(result)
                        if chat_id:
                            message = telegram_ui._format_signal_message(result, "5m")
                            keyboard = telegram_ui.get_main_menu_kb()
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                        state.scanner_cooldown_cache[pair_name] = now
        except Exception as e:
            logger.error(f"SCANNER: Error in on_analysis_done for {pair_name}: {e}", exc_info=True)

    @inlineCallbacks
    def process_all_pairs():
        for pair in assets_to_scan:
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

# --- Klein Routes (Replaces Flask Routes) ---

# MODIFIED: Повністю перероблена логіка маршрутизації для надійності
# NEW: Окремий, чіткий маршрут для головної сторінки
@app.route("/", methods=['GET'])
def home(request):
    filepath = os.path.join(WEBAPP_DIR, 'index.html')
    try:
        with open(filepath, "r", encoding="utf-8") as f: content = f.read()
        app_name = get_fly_app_name() or "zigzag-bot-package"
        api_base_url = f"https://{app_name}.fly.dev"
        cache_buster = int(time.time())
        content = content.replace("{{API_BASE_URL}}", api_base_url)
        content = content.replace("script.js", f"script.js?v={cache_buster}")
        content = content.replace("style.css", f"style.css?v={cache_buster}")
        request.setHeader('Content-Type', 'text/html; charset=utf-8')
        return content.encode('utf-8')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}", exc_info=True)
        request.setResponseCode(500)
        return b"Internal Server Error"

# NEW: Окремий маршрут для всіх інших статичних файлів (style.css, script.js)
@app.route("/<path:filename>", methods=['GET'])
def static_files(request, filename):
    filepath = os.path.join(WEBAPP_DIR, filename)
    if os.path.isfile(filepath):
        return File(filepath)
    else:
        # Якщо файл не знайдено, повертаємо 404
        request.setResponseCode(404)
        return b"Not Found"


@app.route("/api/get_pairs")
@protected_route
def get_pairs(request):
    init_data_list = request.args.get(b"initData")
    init_data = init_data_list[0].decode('utf-8') if init_data_list else None
    
    user_id = get_user_id_from_init_data(init_data)
    watchlist = get_watchlist(user_id) if user_id else []
    forex_data = [{"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs} for name, pairs in FOREX_SESSIONS.items()]
    
    response_data = {"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist}
    
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    return json.dumps(response_data, ensure_ascii=False)

@app.route("/api/toggle_watchlist")
@protected_route
def toggle_watchlist_route(request):
    init_data_list = request.args.get(b"initData")
    init_data = init_data_list[0].decode('utf-8') if init_data_list else None
    user_id = get_user_id_from_init_data(init_data)

    pair_list = request.args.get(b"pair")
    pair = pair_list[0].decode('utf-8') if pair_list else None
    
    request.setHeader('Content-Type', 'application/json')
    if not user_id or not pair:
        request.setResponseCode(400)
        return json.dumps({"success": False, "error": "Missing parameters"})

    success = toggle_watchlist(user_id, pair.replace("/", ""))
    return json.dumps({"success": success})

@app.route("/api/signal")
@protected_route
def api_signal(request):
    pair_list = request.args.get(b"pair")
    pair_normalized = pair_list[0].decode('utf-8').replace("/", "") if pair_list else None

    request.setHeader('Content-Type', 'application/json')
    if not pair_normalized:
        request.setResponseCode(400)
        return json.dumps({"error": "pair is required"})
    
    cached_result = state.latest_analysis_cache.get(pair_normalized)
    if cached_result:
        return json.dumps(cached_result, ensure_ascii=False)
    else:
        request.setResponseCode(404)
        return json.dumps({"error": "Дані для цього активу ще аналізуються сканером. Спробуйте за хвилину."})

@app.route("/api/scanner/status")
@protected_route
def get_scanner_status(request):
    with state.scanner_lock:
        is_enabled = state.SCANNER_ENABLED
    request.setHeader('Content-Type', 'application/json')
    return json.dumps({"enabled": is_enabled})

@app.route("/api/scanner/toggle")
@protected_route
def toggle_scanner_status(request):
    with state.scanner_lock:
        state.SCANNER_ENABLED = not state.SCANNER_ENABLED
        new_status = state.SCANNER_ENABLED
    logger.info(f"Scanner status toggled via API. New status: {new_status}")
    request.setHeader('Content-Type', 'application/json')
    return json.dumps({"enabled": new_status})

@app.route("/api/signal-stream")
@protected_route
def signal_stream(request):
    request.setHeader(b'Content-Type', b'text/event-stream; charset=utf-8')
    request.setHeader(b'Cache-Control', b'no-cache')
    request.setHeader(b'Connection', b'keep-alive')
    request.setHeader(b'X-Accel-Buffering', b'no')
    request.setHeader(b'Content-Encoding', b'identity')
    
    state.sse_clients.append(request)
    logger.info(f"SSE client connected. Total clients: {len(state.sse_clients)}")

    def on_disconnect(_):
        if request in state.sse_clients:
            state.sse_clients.remove(request)
        logger.info(f"SSE client disconnected. Total clients: {len(state.sse_clients)}")

    request.notifyFinish().addErrback(on_disconnect)
    return NOT_DONE_YET

# --- Main Application Startup ---
if __name__ == "__main__":
    # 1. Initialize Telegram Bot
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
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
    
    site = Site(app.resource())
    
    port = int(os.environ.get("PORT", 8080))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Starting Klein server on port {port}...")
    reactor.run()