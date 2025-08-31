import logging
import os
import json
import time
import traceback
import itertools
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
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.task import LoopingCall
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
    """Захисна оболонка для запуску сканера, щоб уникнути падіння."""
    try:
        scan_markets()
    except Exception as e:
        logger.critical(f"SCANNER: CRITICAL FAILURE IN SCAN WRAPPER: {e}", exc_info=True)

@crochet.run_in_reactor
def scan_markets():
    if not state.SCANNER_ENABLED:
        return

    logger.info("SCANNER: Starting sequential market scan...")
    all_forex_pairs = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
    chat_id = get_chat_id()

    def on_analysis_done(result, pair_name):
        try:
            # --- ПОЧАТОК ЗМІН: Зберігаємо результат в кеш ---
            if not result.get("error"):
                state.latest_analysis_cache[pair_name] = result
            # --- КІНЕЦЬ ЗМІН ---

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
        
    ready_deferred = Deferred()
    set_client_ready_deferred(ready_deferred)

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.updater = updater
    state.client = client

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
    forex_data = [
        {"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs}
        for name, pairs in FOREX_SESSIONS.items()
    ]
    return jsonify({
        "forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS,
        "commodities": COMMODITIES, "watchlist": watchlist
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
        success = toggle_watchlist(user_id, pair_normalized)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Failed to write to database"}), 500
    except Exception as e:
        logger.error(f"Error in toggle_watchlist for user {user_id}: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500

# --- ПОЧАТОК ЗМІН: Повністю переписана логіка /api/signal ---
@app.route("/api/signal")
@protected_route
def api_signal():
    pair = request.args.get("pair")
    # Таймфрейм більше не потрібен, оскільки сканер працює на 5m,
    # але ми залишаємо його для сумісності
    timeframe = request.args.get("timeframe", "5m") 
    
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    pair_normalized = pair.replace("/", "")
    
    # Миттєво беремо дані з кешу, замість запуску нового аналізу
    cached_result = state.latest_analysis_cache.get(pair_normalized)
    
    if cached_result:
        return jsonify(cached_result)
    else:
        # Якщо даних ще немає (сканер ще не дійшов до цієї пари)
        return jsonify({
            "error": "Дані для цього активу ще аналізуються сканером. Спробуйте за хвилину."
        }), 404
# --- КІНЕЦЬ ЗМІН ---

@app.route("/api/scanner/status")
@protected_route
def get_scanner_status():
    return jsonify({"enabled": state.SCANNER_ENABLED})

@app.route("/api/scanner/toggle")
@protected_route
def toggle_scanner_status():
    state.SCANNER_ENABLED = not state.SCANNER_ENABLED
    logger.info(f"Scanner status toggled via API. New status: {state.SCANNER_ENABLED}")
    return jsonify({"enabled": state.SCANNER_ENABLED})

@app.route("/api/signal-stream")
@protected_route
def signal_stream():
    def generate():
        while True:
            try:
                signal_data = state.sse_queue.get(timeout=None)
                sse_data = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n"
                yield sse_data
            except Exception:
                continue
    return Response(generate(), mimetype='text/event-stream')

if __name__ != "__main__":
    start_background_services()