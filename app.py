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

# Local modules
import state
import telegram_ui
import db
from auth import is_valid_init_data, get_user_id_from_init_data
import analysis as analysis_module
# --- ПОЧАТОК ЗМІН: Видаляємо імпорт redis_client ---
# from redis_client import get_redis 
# --- КІНЕЦЬ ЗМІН ---
from spotware_connect import SpotwareConnect
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListRes, ProtoOASubscribeSpotsReq, ProtoOASpotEvent
)
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

get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data

# --------------------------
# Scanner logic
# --------------------------
def _collect_assets_to_scan():
    assets = []
    if state.SCANNER_STATE.get("forex"):
        for session_pairs in FOREX_SESSIONS.values():
            assets.extend(session_pairs)
    if state.SCANNER_STATE.get("crypto"):
        assets.extend(CRYPTO_PAIRS)
    if state.SCANNER_STATE.get("commodities"):
        assets.extend(COMMODITIES)
    seen = set()
    out = [a for a in assets if not (a in seen or seen.add(a))]
    return out

def _handle_analysis_result(pair_norm, result):
    try:
        if not result or result.get("error"):
            return
        
        score = result.get("bull_percentage", 50)
        
        lower_bound = 100 - IDEAL_ENTRY_THRESHOLD
        logger.info(f"[SCANNER_DIAG] Pair: {pair_norm}, Score: {score}%. Checking against threshold: >= {IDEAL_ENTRY_THRESHOLD}% or <= {lower_bound}%.")

        is_signal = score >= IDEAL_ENTRY_THRESHOLD or score <= lower_bound
        
        if not is_signal:
            logger.info(f"[SCANNER_DIAG] Signal for {pair_norm} IGNORED due to low score.")
            return

        now = time.time()
        last_ts = state.scanner_cooldown_cache.get(pair_norm, 0)
        if (now - last_ts) < SCANNER_COOLDOWN_SECONDS:
            logger.debug(f"{pair_norm} on cooldown, skip notify")
            return
        
        logger.info(f"[SCANNER_DIAG] Signal for {pair_norm} PASSED filter. Notifying.")

        try:
            state.sse_queue.put_nowait(result)
        except queue.Full:
            logger.warning("SSE queue full - dropping")

        state.latest_analysis_cache[pair_norm] = result

        chat_id = get_chat_id()
        if chat_id and state.updater:
            try:
                message = telegram_ui._format_signal_message(result, "5m")
                kb = telegram_ui.get_main_menu_kb()
                state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=kb)
            except Exception:
                logger.exception("Failed to send telegram notification")

        state.scanner_cooldown_cache[pair_norm] = now
        logger.info(f"SCANNER: Notified for {pair_norm} (score {score})")
    except Exception:
        logger.exception("Error handling analysis result")

def _scan_worker(assets_to_scan):
    for pair in assets_to_scan:
        try:
            pair_norm = pair.replace("/", "")
            if not state.SYMBOLS_LOADED:
                logger.debug("Symbols not loaded yet, skipping scan")
                return

            d = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_norm, 0, "5m")
            done_q = queue.Queue(maxsize=1)
            d.addCallbacks(lambda res: done_q.put(res), lambda err: done_q.put({"error": str(err)}))

            try:
                res = done_q.get(timeout=70)
                if not res or res.get("error"):
                    logger.warning(f"Analysis failed or empty for {pair_norm}: {res.get('error')}")
                    continue
                _handle_analysis_result(pair_norm, res)
            except queue.Empty:
                logger.warning(f"Analysis timeout for {pair_norm}")
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
        logger.info(f"SCANNER: Starting scan for: {[k for k,v in state.SCANNER_STATE.items() if v]}")
        threads.deferToThread(_scan_worker, assets)
    except Exception:
        logger.exception("scan_markets_once error")

def _on_spot_event(event: ProtoOASpotEvent):
    try:
        if not (event.HasField("bid") or event.HasField("ask")):
            return

        symbol_name = state.symbol_id_map.get(event.symbolId)
        if not symbol_name:
            return

        divisor = 10**5
        bid = event.bid / divisor if event.HasField("bid") else None
        ask = event.ask / divisor if event.HasField("ask") else None
        mid = (bid + ask) / 2.0 if bid and ask else None

        state.live_prices[symbol_name] = {
            "bid": bid, "ask": ask, "mid": mid, "ts": time.time()
        }
        logger.debug(f"Tick {symbol_name}: Mid Price = {mid}")

    except Exception:
        logger.exception("Error processing spot event")

def start_price_subscriptions():
    logger.info("Starting price subscriptions for all scannable assets...")
    assets_to_subscribe = _collect_assets_to_scan()
    assets_to_subscribe.extend(STOCK_TICKERS)
    assets_to_subscribe = sorted(list(set(assets_to_subscribe)))

    for i, pair in enumerate(assets_to_subscribe):
        def subscribe_pair(p):
            try:
                pair_norm = p.replace("/", "")
                symbol_details = state.symbol_cache.get(pair_norm)
                if not symbol_details:
                    logger.warning(f"Cannot subscribe to {pair_norm}: not found in symbol cache.")
                    return

                req = ProtoOASubscribeSpotsReq(
                    ctidTraderAccountId=state.client._client.account_id,
                    symbolId=[symbol_details.symbolId]
                )
                d = state.client.send(req)
                d.addCallbacks(
                    lambda _, p=pair_norm: logger.info(f"✅ Subscribed to price stream for {p}"),
                    lambda err, p=pair_norm: logger.error(f"❌ Failed to subscribe to {p}: {err.getErrorMessage()}")
                )
                state.client.on(f"spot_event_{symbol_details.symbolId}", _on_spot_event)

            except Exception:
                logger.exception(f"Error during subscription schedule for {p}")

        reactor.callLater(i * 0.2, subscribe_pair, pair)

# --------------------------
# cTrader handlers
# --------------------------
def _on_symbols_loaded(raw_message):
    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
        state.symbol_id_map = {s.symbolId: s.symbolName.replace("/", "") for s in res.symbol}
        state.all_symbol_names = [s.symbolName for s in res.symbol]
        state.SYMBOLS_LOADED = True
        logger.info(f"Loaded {len(state.symbol_cache)} symbols from cTrader.")
        start_price_subscriptions()
    except Exception:
        logger.exception("on_symbols_loaded error")

def _on_symbols_error(failure):
    msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
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
    logger.info(f"On-demand analysis for {pair_normalized} timeframe {timeframe}")

    try:
        d = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_normalized, user_id, timeframe)
        done_q = queue.Queue()
        d.addCallbacks(lambda res: done_q.put(res), lambda f: done_q.put({"error": str(f)}))
        result = done_q.get(timeout=30)
        if result.get("error"):
            logger.error(f"On-demand analysis failed for {pair_normalized}: {result.get('error')}")
            return jsonify(result), 500
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
    state.set_scanner_state(category, not state.get_scanner_state(category))
    logger.info(f"Scanner for '{category}' toggled to {state.SCANNER_STATE[category]}")
    return jsonify(state.SCANNER_STATE)

@app.route("/api/signal-stream")
@protected_route
def signal_stream():
    def generate():
        logger.info("DEBUG: Web client connected to SSE stream. Waiting for signals...")
        while True:
            try:
                data = state.sse_queue.get(timeout=20)
                logger.info(f"DEBUG: Signal for {data.get('pair')} GOT from SSE queue. Sending to web client.")
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except queue.Empty:
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
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
        dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        reactor.callInThread(updater.start_polling)
        logger.info("Telegram bot started (polling in background thread).")
    except Exception:
        logger.exception("Failed to start Telegram bot")

def start_ctrader_client():
    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        state.client = client
        client.on("ready", on_ctrader_ready)
        reactor.callWhenRunning(client.start)
        logger.info("cTrader client scheduled to start")
    except Exception:
        logger.exception("Failed to initialize cTrader client")

def _start_background_services():
    start_telegram_bot()
    start_ctrader_client()
    LoopingCall(scan_markets_once).start(60.0, now=False)
    LoopingCall(lambda: (state.sse_queue.put_nowait({"_ping": int(time.time())}) if not state.sse_queue.full() else None)).start(20.0, now=False)

# --------------------------
# Twisted + Flask integration and main
# --------------------------
def main():
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    reactor.callWhenRunning(_start_background_services)

    def _sigterm(signum, frame):
        logger.info("SIGTERM received — stopping reactor")
        try:
            if state.updater:
                state.updater.stop()
        finally:
            reactor.stop()
            sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()