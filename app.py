# app.py
import logging
import os
import json
import time
import queue
import traceback
from functools import wraps

# Twisted + WSGI
from twisted.internet import reactor, threads
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
import db
from auth import is_valid_init_data, get_user_id_from_init_data
# --- ПОЧАТОК ЗМІН: Імпортуємо новий обробник ---
from spotware_connect import SpotwareConnect, central_spot_event_handler
# --- КІНЕЦЬ ЗМІН ---
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, 
    get_chat_id, get_ctrader_access_token, get_demo_account_id, get_fly_app_name
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
if not hasattr(state, "sse_queue"): state.sse_queue = queue.Queue()
if not hasattr(state, "scanner_cooldown_cache"): state.scanner_cooldown_cache = {}
if not hasattr(state, "latest_analysis_cache"): state.latest_analysis_cache = {}

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

def scan_markets_once():
    if not any(state.SCANNER_STATE.values()):
        logger.debug("All scanners are disabled, skipping run.")
        return
    logger.info(f"SCANNER: Starting scan for: {[cat for cat, on in state.SCANNER_STATE.items() if on]}")
    assets_to_scan = []
    if state.SCANNER_STATE.get("forex"):
        assets_to_scan.extend(list(set([p for sess in FOREX_SESSIONS.values() for p in sess])))
    if state.SCANNER_STATE.get("crypto"):
        assets_to_scan.extend(CRYPTO_PAIRS)
    if state.SCANNER_STATE.get("commodities"):
        assets_to_scan.extend(COMMODITIES)
    if not assets_to_scan:
        logger.info("No assets to scan.")
        return
    chat_id = get_chat_id()
    def _on_done(result, pair_name):
        try:
            if result.get("error"): return
            score = result.get("bull_percentage", 50)
            is_signal = score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD)
            if is_signal:
                now = time.time()
                last = state.scanner_cooldown_cache.get(pair_name, 0)
                if (now - last) > SCANNER_COOLDOWN_SECONDS:
                    logger.info(f"SCANNER: Signal for {pair_name} (score {score}). Notifying.")
                    state.latest_analysis_cache[pair_name] = result
                    try: state.sse_queue.put(result, block=False)
                    except queue.Full: logger.warning("SSE queue full, dropping signal")
                    if chat_id and getattr(state, "updater", None):
                        try:
                            message = telegram_ui._format_signal_message(result, "5m")
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=telegram_ui.get_main_menu_kb())
                        except Exception as e:
                            logger.exception(f"Failed to send telegram notification: {e}")
                    state.scanner_cooldown_cache[pair_name] = now
        except Exception:
            logger.exception("SCANNER: error in _on_done")
    def worker():
        for pair in assets_to_scan:
            norm = pair.replace("/", "")
            try:
                d = get_api_detailed_signal_data(state.client, state.symbol_cache, norm, 0, "5m")
                done_q = queue.Queue()
                d.addCallbacks(lambda res: done_q.put(res), lambda f: done_q.put({"error": str(f)}))
                res = done_q.get(timeout=65)
                _on_done(res, norm)
            except Exception:
                logger.exception(f"SCANNER: Failed processing {norm}")
    threads.deferToThread(worker)

def on_ctrader_ready():
    logger.info("cTrader client ready — loading symbols")
    d = state.client.send(ProtoOASymbolsListReq(ctidTraderAccountId=state.client.account_id))
    d.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.all_symbol_names = [s.symbolName for s in symbols_response.symbol]
        
        # --- ПОЧАТОК ЗМІН: Створюємо "зворотний" кеш і підключаємо обробник ---
        state.symbol_id_to_name_map = {s.symbolId: s.symbolName.replace("/", "") for s in symbols_response.symbol}
        state.client.on("spot_event", central_spot_event_handler)
        logger.info("Central spot event handler connected.")
        # --- КІНЕЦЬ ЗМІН ---

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

@app.route("/")
def home():
    try:
        with open(os.path.join(WEBAPP_DIR, "index.html"), "r", encoding="utf-8") as f: content = f.read()
        api_base_url = f"https://{get_fly_app_name() or 'zigzag-bot-package'}.fly.dev"
        cache_buster = int(time.time())
        content = content.replace("{{API_BASE_URL}}", api_base_url).replace("script.js", f"script.js?v={cache_buster}").replace("style.css", f"style.css?v={cache_buster}")
        return Response(content, mimetype='text/html')
    except Exception:
        logger.exception("Error serving index.html")
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename): return send_from_directory(WEBAPP_DIR, filename)

@app.route("/api/get_pairs")
@protected_route
def get_pairs():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    watchlist = db.get_watchlist(user_id) if user_id else []
    forex_data = [{"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs} for name, pairs in FOREX_SESSIONS.items()]
    return jsonify({"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist})

@app.route("/api/toggle_watchlist")
@protected_route
def toggle_watchlist_route():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    pair = request.args.get("pair")
    if not user_id or not pair: return jsonify({"success": False, "error": "Missing parameters"}), 400
    try:
        return jsonify({"success": db.toggle_watchlist(user_id, pair.replace("/", ""))})
    except Exception:
        logger.exception("toggle_watchlist failed")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/api/signal")
@protected_route
def api_signal():
    pair = request.args.get("pair")
    timeframe = request.args.get("timeframe", "15m")
    if timeframe not in PERIOD_MAP: return jsonify({"error": "Invalid timeframe"}), 400
    if not pair: return jsonify({"error": "pair is required"}), 400
    pair_normalized = pair.replace("/", "")
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    logger.info(f"Signal request [FORCED FRESH] for {pair_normalized} TF {timeframe}")
    try:
        d = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_normalized, user_id, timeframe)
        done_q = queue.Queue()
        d.addCallbacks(lambda res: done_q.put(res), lambda f: done_q.put({"error": str(f.value)}))
        result = done_q.get(timeout=25)
        if result.get("error"):
            logger.error(f"On-demand analysis failed for {pair_normalized}: {result['error']}")
            return jsonify(result), 500
        return jsonify(result)
    except queue.Empty:
        logger.error(f"On-demand analysis for {pair_normalized} timed out.")
        return jsonify({"error": "Запит тривав занадто довго."}), 504
    except Exception:
        logger.exception(f"Critical error in on-demand analysis for {pair_normalized}")
        return jsonify({"error": "Критична помилка сервера."}), 500

@app.route("/api/scanner/status")
@protected_route
def scanner_status(): return jsonify(state.SCANNER_STATE)

@app.route("/api/scanner/toggle", methods=['POST'])
@protected_route
def scanner_toggle():
    category = request.args.get("category")
    if category and category in state.SCANNER_STATE:
        state.SCANNER_STATE[category] = not state.SCANNER_STATE[category]
        logger.info(f"Scanner for '{category}' toggled via API to: {state.SCANNER_STATE[category]}")
    return jsonify(state.SCANNER_STATE)

@app.route("/api/signal-stream")
@protected_route
def signal_stream():
    def generate():
        while True:
            try:
                data = state.sse_queue.get(timeout=20)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except queue.Empty: yield ": ping\n\n"
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

def start_services():
    if TELEGRAM_BOT_TOKEN:
        logger.info("Starting Telegram Updater.")
        updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        state.updater = updater
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        reactor.callInThread(updater.start_polling)
    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        state.client = client
        client.on("ready", on_ctrader_ready)
        # --- ПОЧАТОК ЗМІН: Передаємо конфігурацію в метод start ---
        reactor.callWhenRunning(client.start, "live.ctraderapi.com", 5035, get_ctrader_access_token(), get_demo_account_id())
        # --- КІНЕЦЬ ЗМІН ---
        logger.info("cTrader client scheduled to start.")
    except Exception:
        logger.exception("Failed to initialize cTrader client")

def main():
    db.init_db()
    logger.info("Database initialized.")
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")
    start_services()
    LoopingCall(lambda: state.sse_queue.put_nowait({"_ping": int(time.time())}) if not state.sse_queue.full() else None).start(20)
    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()