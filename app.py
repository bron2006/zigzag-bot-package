# app.py
import os
import sys
import json
import time
import queue
import signal
import logging
import traceback
import inspect

from functools import wraps
from pathlib import Path

# Twisted + Flask WSGI
from twisted.internet import reactor, threads
from twisted.internet.task import LoopingCall
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site

from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

# Local modules (project files you already have)
import state
import telegram_ui
import db
from auth import is_valid_init_data, get_user_id_from_init_data
import analysis as analysis_module
from redis_client import get_redis
from spotware_connect import SpotwareConnect
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("app")

# Flask app config
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

# Ensure state has required attributes
if not hasattr(state, "sse_queue"):
    state.sse_queue = queue.Queue(maxsize=100)
if not hasattr(state, "scanner_cooldown_cache"):
    state.scanner_cooldown_cache = {}
if not hasattr(state, "latest_analysis_cache"):
    state.latest_analysis_cache = {}
if not hasattr(state, "SYMBOLS_LOADED"):
    state.SYMBOLS_LOADED = False
if not hasattr(state, "symbol_cache"):
    state.symbol_cache = {}
if not hasattr(state, "SCANNER_STATE"):
    # default scanner states
    state.SCANNER_STATE = {"forex": True, "crypto": False, "commodities": False}

# helper: protected route for Telegram WebApp initData
def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            logger.warning(f"Unauthorized API access attempt. Path: {request.path}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --------------------------
# Adaptive wrapper for analysis.get_api_detailed_signal_data
# This makes the rest of the code robust to different signatures of analysis.get_api_detailed_signal_data
# (some versions had: (client, symbol_cache, symbol, user_id, timeframe)
# others had: (client, symbol_cache, symbol, period, count=...)
# others: (client, symbol_cache, symbol, timeframe))
# --------------------------
_orig_get_api = getattr(analysis_module, "get_api_detailed_signal_data", None)
if _orig_get_api is None:
    raise RuntimeError("analysis.get_api_detailed_signal_data not found")

def _unified_get_api_detailed_signal_data(client, symbol_cache, symbol, *args, **kwargs):
    """
    Try to call original with best-fit signature.
    Returns a Twisted Deferred (whatever the original returns) or raises.
    """
    sig = inspect.signature(_orig_get_api)
    params = list(sig.parameters.keys())
    # heuristics:
    # if 'user' or 'user_id' exists -> assume signature (client, symbol_cache, symbol, user_id, timeframe)
    if len(params) >= 4 and any(p in params[3] for p in ('user', 'user_id', 'uid')):
        # args might be (user_id, timeframe) or just (timeframe) depending on callers.
        # prefer: user_id from args if int, else 0
        user_id = 0
        timeframe = kwargs.get('timeframe') or (args[1] if len(args) >= 2 else (args[0] if len(args) == 1 and isinstance(args[0], int) else '15m'))
        if len(args) >= 1 and isinstance(args[0], int):
            user_id = args[0]
            if len(args) >= 2:
                timeframe = args[1]
        return _orig_get_api(client, symbol_cache, symbol, user_id, timeframe)
    # else assume period/timeframe is the 4th positional param
    try:
        # if caller passed timeframe in args, use it; else default '15m'
        if len(args) >= 1:
            return _orig_get_api(client, symbol_cache, symbol, args[0])
        return _orig_get_api(client, symbol_cache, symbol, kwargs.get('timeframe', '15m'))
    except TypeError:
        # fallback: try (client, symbol_cache, symbol, timeframe, count)
        try:
            timeframe = args[0] if len(args) >= 1 else kwargs.get('timeframe', '15m')
            count = args[1] if len(args) >= 2 else kwargs.get('count', 500)
            return _orig_get_api(client, symbol_cache, symbol, timeframe, count)
        except Exception:
            raise

# Monkeypatch analysis module so other modules (telegram_ui) calling it also use unified version
analysis_module.get_api_detailed_signal_data = _unified_get_api_detailed_signal_data

# Local alias
get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data

# --------------------------
# Scanner logic
# --------------------------
def _collect_assets_to_scan():
    assets = []
    if state.SCANNER_STATE.get("forex"):
        # flatten all FOREX_SESSIONS lists
        for session_pairs in FOREX_SESSIONS.values():
            assets.extend(session_pairs)
    if state.SCANNER_STATE.get("crypto"):
        assets.extend(CRYPTO_PAIRS)
    if state.SCANNER_STATE.get("commodities"):
        assets.extend(COMMODITIES)
    # dedupe preserving order
    seen = set()
    out = []
    for a in assets:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out

def _handle_analysis_result(pair_norm, result):
    """
    Called when analysis result is ready (dict).
    Publishes to SSE queue, saves to state cache and sends telegram if configured.
    """
    try:
        if not result or result.get("error"):
            return
        # unify keys: some versions use 'score' or 'bull_percentage'
        score = result.get("bull_percentage") or result.get("score") or 50
        bull = int(score)
        is_signal = bull >= IDEAL_ENTRY_THRESHOLD or bull <= (100 - IDEAL_ENTRY_THRESHOLD)
        if not is_signal:
            return

        now = time.time()
        last_ts = state.scanner_cooldown_cache.get(pair_norm, 0)
        if (now - last_ts) < SCANNER_COOLDOWN_SECONDS:
            logger.debug(f"{pair_norm} on cooldown, skip notify")
            return

        # add to SSE queue (non-blocking)
        try:
            state.sse_queue.put_nowait(result)
        except Exception:
            logger.warning("SSE queue full - dropping")

        # store latest analysis
        state.latest_analysis_cache[pair_norm] = result

        # send Telegram notification if chat configured and bot present
        chat_id = get_chat_id()
        if chat_id and getattr(state, "updater", None):
            try:
                message = telegram_ui._format_signal_message(result, "5m") if hasattr(telegram_ui, "_format_signal_message") else json.dumps(result, ensure_ascii=False)
                kb = telegram_ui.get_main_menu_kb() if hasattr(telegram_ui, "get_main_menu_kb") else None
                if kb:
                    state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=kb)
                else:
                    state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            except Exception:
                logger.exception("Failed to send telegram notification")

        state.scanner_cooldown_cache[pair_norm] = now
        logger.info(f"SCANNER: Notified for {pair_norm} (score {bull})")
    except Exception:
        logger.exception("Error handling analysis result")

def _scan_worker(assets_to_scan):
    """
    Runs in a threadpool (threads.deferToThread). For each asset does analysis and handles result.
    Blocks waiting for each Deferred using a threading.Queue that Deferred callbacks fill.
    """
    for pair in assets_to_scan:
        try:
            pair_norm = pair.replace("/", "")
            # ensure symbols loaded
            if not state.SYMBOLS_LOADED:
                logger.debug("Symbols not loaded yet, skipping scan")
                return
            # call analysis (Deferred)
            d = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_norm, "5m")
            done_q = queue.Queue(maxsize=1)
            def on_success(res):
                try:
                    done_q.put(res)
                except Exception:
                    pass
            def on_err(f):
                try:
                    # try extracting message
                    msg = f.getErrorMessage() if hasattr(f, "getErrorMessage") else str(f)
                except Exception:
                    msg = "Unknown analysis error"
                done_q.put({"error": msg})
            d.addCallbacks(on_success, on_err)
            try:
                res = done_q.get(timeout=70)
            except queue.Empty:
                logger.warning(f"Analysis timeout for {pair_norm}")
                continue
            # res expected to be dict
            _handle_analysis_result(pair_norm, res)
            # small sleep between pairs to avoid bursting API
            time.sleep(0.1)
        except Exception:
            logger.exception(f"Exception in scan worker for {pair}")

def scan_markets_once():
    try:
        if not any(state.SCANNER_STATE.values()):
            logger.debug("All scanners disabled; skipping scan loop")
            return
        assets = _collect_assets_to_scan()
        if not assets:
            logger.info("No assets configured for scanning")
            return
        logger.info(f"SCANNER: Starting market scan for enabled categories: {[k for k,v in state.SCANNER_STATE.items() if v]}")
        # run worker in threadpool so reactor isn't blocked
        threads.deferToThread(_scan_worker, assets)
    except Exception:
        logger.exception("scan_markets_once error")

# --------------------------
# cTrader handlers
# --------------------------
def _on_symbols_loaded(raw_message):
    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
        state.all_symbol_names = [s.symbolName for s in res.symbol]
        state.SYMBOLS_LOADED = True
        logger.info(f"Loaded {len(state.symbol_cache)} symbols from cTrader.")
    except Exception:
        logger.exception("on_symbols_loaded error")

def _on_symbols_error(failure):
    try:
        msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
    except Exception:
        msg = str(failure)
    logger.error(f"Failed to load symbols: {msg}")
    state.SYMBOLS_LOADED = False

def on_ctrader_ready():
    logger.info("cTrader client ready — requesting symbol list")
    try:
        d = state.client.get_all_symbols()
        d.addCallbacks(_on_symbols_loaded, _on_symbols_error)
    except Exception:
        logger.exception("on_ctrader_ready error")

# --------------------------
# Flask routes (API + SSE)
# --------------------------
@app.route("/")
def home():
    try:
        index_path = os.path.join(WEBAPP_DIR, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                content = f.read()
            app_name = get_fly_app_name() or "zigzag-bot-package"
            api_base_url = f"https://{app_name}.fly.dev"
            content = content.replace("{{API_BASE_URL}}", api_base_url)
            cache_buster = int(time.time())
            content = content.replace("script.js", f"script.js?v={cache_buster}")
            content = content.replace("style.css", f"style.css?v={cache_buster}")
            return Response(content, mimetype='text/html')
        return "Web UI not found", 404
    except Exception:
        logger.exception("Error serving index")
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

@app.route("/api/get_pairs")
@protected_route
def get_pairs():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    watchlist = db.get_watchlist(user_id) if user_id else []
    forex_data = [
        {"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs}
        for name, pairs in FOREX_SESSIONS.items()
    ]
    return jsonify({
        "forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS,
        "commodities": COMMODITIES, "watchlist": watchlist
    })

@app.route("/api/signal")
@protected_route
def api_signal():
    pair = request.args.get("pair")
    timeframe = request.args.get("timeframe", "15m")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    pair_normalized = pair.replace("/", "")
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    logger.info(f"On-demand analysis request for {pair_normalized} timeframe {timeframe}")

    # Run analysis and wait for Deferred result (safe to block in WSGI thread)
    try:
        d = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_normalized, timeframe)
        done_q = queue.Queue()
        def cb_success(res): done_q.put(res)
        def cb_err(f):
            try:
                msg = f.getErrorMessage() if hasattr(f, "getErrorMessage") else str(f)
            except Exception:
                msg = str(f)
            done_q.put({"error": msg})
        d.addCallbacks(cb_success, cb_err)
        result = done_q.get(timeout=30)
        if result.get("error"):
            logger.error(f"On-demand analysis failed for {pair_normalized}: {result.get('error')}")
            return jsonify(result), 500
        # store latest analysis in state cache
        state.latest_analysis_cache[pair_normalized] = result
        return jsonify(result)
    except queue.Empty:
        logger.error(f"On-demand analysis timeout for {pair_normalized}")
        return jsonify({"error": "Request timed out."}), 504
    except Exception:
        logger.exception("api_signal critical error")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/scanner/status")
@protected_route
def scanner_status():
    return jsonify(state.SCANNER_STATE)

@app.route("/api/scanner/toggle", methods=['POST'])
@protected_route
def scanner_toggle():
    category = request.args.get("category")
    if not category or category not in state.SCANNER_STATE:
        return jsonify({"error": "Invalid category"}), 400
    state.SCANNER_STATE[category] = not state.SCANNER_STATE[category]
    logger.info(f"Scanner for '{category}' toggled to {state.SCANNER_STATE[category]}")
    return jsonify(state.SCANNER_STATE)

@app.route("/api/signal-stream")
@protected_route
def signal_stream():
    def generate():
        while True:
            try:
                data = state.sse_queue.get(timeout=20)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except queue.Empty:
                # keepalive
                yield ": ping\n\n"
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

# --------------------------
# Startup: Telegram + cTrader + Scanner loop
# --------------------------
def start_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram disabled")
        return
    try:
        updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        state.updater = updater
        dp = updater.dispatcher
        # register handlers from telegram_ui if available
        try:
            dp.add_handler(CommandHandler("start", telegram_ui.start))
            if hasattr(telegram_ui, "symbols_command"):
                dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
            dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
            dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
            dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        except Exception:
            logger.exception("Failed to register telegram handlers (telegram_ui mismatch?)")
        reactor.callInThread(updater.start_polling)
        logger.info("Telegram bot started (polling in background thread).")
    except Exception:
        logger.exception("Failed to start Telegram bot")

def start_ctrader_client():
    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        state.client = client
        client.on("ready", on_ctrader_ready)
        # also hook a ready-to-load-symbols handler
        reactor.callWhenRunning(client.start)
        logger.info("cTrader client scheduled to start")
    except Exception:
        logger.exception("Failed to initialize cTrader client")

def _start_background_services():
    # Telegram
    start_telegram_bot()
    # cTrader
    start_ctrader_client()
    # Start scanner loop (only start once symbols loaded)
    # We start it anyway - it will skip work until symbols are loaded.
    LoopingCall(scan_markets_once).start(60.0, now=False)
    # SSE keepalive pings
    LoopingCall(lambda: (state.sse_queue.put_nowait({"_ping": int(time.time())}) if not state.sse_queue.full() else None)).start(20.0, now=False)

# --------------------------
# Twisted + Flask integration and main
# --------------------------
def main():
    # create WSGI resource & listen
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    # start background services after reactor starts
    reactor.callWhenRunning(_start_background_services)

    # handle SIGTERM gracefully
    def _sigterm(signum, frame):
        logger.info("SIGTERM received — stopping reactor")
        try:
            if getattr(state, "updater", None):
                try:
                    state.updater.stop()
                except Exception:
                    pass
        finally:
            reactor.stop()
            sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()
