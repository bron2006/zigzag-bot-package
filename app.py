import logging
import os
import json
import time
import traceback
import itertools
import queue
from functools import wraps
from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context

# --- ПОЧАТОК ЗМІН: Змінено імпорти для нової архітектури ---
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.task import LoopingCall
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource
from klein import Klein
# --- КІНЕЦЬ ЗМІН ---

import state
from auth import is_valid_init_data, get_user_id_from_init_data
from db import get_watchlist, toggle_watchlist
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

import telegram_ui
from analysis import get_api_detailed_signal_data, PERIOD_MAP

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

_client_ready_deferred = None

def set_client_ready_deferred(d):
    global _client_ready_deferred
    _client_ready_deferred = d

def wait_client_ready():
    from twisted.internet.defer import succeed
    return _client_ready_deferred if _client_ready_deferred is not None else succeed(True)

def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            logger.warning(f"Unauthorized API access attempt. Path: {request.path}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def scan_markets_wrapper():
    try:
        # Більше не потрібен @crochet.run_in_reactor, оскільки ми вже в потоці Twisted
        scan_markets()
    except Exception as e:
        logger.critical(f"SCANNER: CRITICAL FAILURE IN SCAN WRAPPER: {e}", exc_info=True)

def scan_markets():
    if not state.SCANNER_ENABLED:
        return

    logger.info("SCANNER: Starting sequential market scan...")
    all_forex_pairs = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
    chat_id = get_chat_id()

    if not chat_id:
        logger.warning("SCANNER: CHAT_ID is not set. Scanner will not send notifications.")
        
    def on_analysis_done(result, pair_name):
        try:
            if result.get("error"):
                return
            state.latest_analysis_cache[pair_name] = result
            score = result.get('bull_percentage', 50)
            if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                now = time.time()
                if (now - state.scanner_cooldown_cache.get(pair_name, 0)) > SCANNER_COOLDOWN_SECONDS:
                    logger.info(f"SCANNER: Ideal entry for {pair_name}. Notifying.")
                    state.sse_queue.put(result)
                    message = telegram_ui._format_signal_message(result, "5m")
                    keyboard = telegram_ui.get_main_menu_kb()
                    if chat_id:
                        state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                    state.scanner_cooldown_cache[pair_name] = now
        except Exception as e:
            logger.error(f"SCANNER: Error processing result for {pair_name}: {e}", exc_info=True)

    def process_next_pair(result, pairs_to_scan):
        if not pairs_to_scan:
            logger.info("SCANNER: Sequential scan finished.")
            return
        
        pair = pairs_to_scan.pop(0)
        norm_pair = pair.replace("/", "")
        
        d = get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
        d.addCallback(on_analysis_done, pair_name=norm_pair)
        d.addBoth(process_next_pair, pairs_to_scan=pairs_to_scan)
        return d

    process_next_pair(None, all_forex_pairs.copy())

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
        if _client_ready_deferred and not _client_ready_deferred.called:
            _client_ready_deferred.callback(True)
        
        logger.info("Starting market scanner loop...")
        scanner_loop = LoopingCall(scan_markets_wrapper)
        scanner_loop.start(60)

    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)


def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")
    if _client_ready_deferred and not _client_ready_deferred.called:
        _client_ready_deferred.errback(failure)

# --- Flask маршрути залишаються практично без змін ---
# ... (всі ваші @app.route(...) йдуть тут)

@app.route("/")
def home():
    # ... (код без змін)
    pass
    
# ... і так далі для всіх маршрутів ...

# --- ПОЧАТОК ЗМІН: Повністю переписаний запуск додатку ---

def start_background_services():
    """Ініціалізує Telegram та cTrader клієнти."""
    logger.info("Initializing background services (Telegram, cTrader)...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found!")
        return
        
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.updater = updater
    state.client = client

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    # ... (решта обробників)
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))

    updater.start_polling()
    logger.info("Telegram bot started.")

    client.on("ready", on_ctrader_ready)
    # Важливо: client.start() тепер викликається реактором Twisted
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client scheduled to start with reactor.")

if __name__ == "__main__":
    # 1. Запускаємо фонові сервіси (Telegram, cTrader)
    start_background_services()
    
    # 2. Створюємо ресурс Twisted для нашого Flask додатку
    wsgi_resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(wsgi_resource)
    
    # 3. Запускаємо Twisted сервер, який буде обслуговувати все
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Twisted server on port {port}...")
    reactor.listenTCP(port, site)
    reactor.run()
# --- КІНЕЦЬ ЗМІН ---