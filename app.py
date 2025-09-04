# app.py
import logging
import os
import json
import time
import queue
import traceback
from functools import wraps

from twisted.internet import reactor
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource

from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context

from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

import state
import telegram_ui
import db
from auth import is_valid_init_data, get_user_id_from_init_data
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, get_chat_id
)
from analysis import PERIOD_MAP

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("app")

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

if not hasattr(state, "sse_queue"):
    state.sse_queue = queue.Queue()

def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            logger.warning(f"Unauthorized API access attempt. Path: {request.path}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

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

@app.route("/api/toggle_watchlist")
@protected_route
def toggle_watchlist_route():
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    pair = request.args.get("pair")
    if not user_id or not pair:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
    try:
        pair_normalized = pair.replace("/", "")
        success = db.toggle_watchlist(user_id, pair_normalized)
        return jsonify({"success": success})
    except Exception:
        logger.exception("toggle_watchlist failed")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/api/signal")
@protected_route
def api_signal():
    from analysis import get_api_detailed_signal_data
    pair = request.args.get("pair")
    timeframe = request.args.get("timeframe", "15m")
    if timeframe not in PERIOD_MAP:
        return jsonify({"error": "Invalid timeframe"}), 400
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    pair_normalized = pair.replace("/", "")
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    logger.info(f"Signal request for {pair_normalized} timeframe {timeframe}")

    try:
        d = get_api_detailed_signal_data(state.client, state.symbol_cache, pair_normalized, user_id, timeframe)
        done_q = queue.Queue()
        def cb_success(res): done_q.put(res)
        def cb_err(f):
            try:
                error_message = f.getErrorMessage() if hasattr(f, 'getErrorMessage') else str(f.value)
                done_q.put({"error": error_message})
            except Exception as e:
                done_q.put({"error": f"Unknown error: {e}"})
        d.addCallbacks(cb_success, cb_err)
        result = done_q.get(timeout=5)
        if result.get("error"):
            return jsonify(result), 500
        return jsonify(result)
    except queue.Empty:
        return jsonify({"error": "Request timed out."}), 504
    except Exception as e:
        logger.exception(f"Critical error in signal request for {pair_normalized}")
        return jsonify({"error": f"Server error: {e}"}), 500

@app.route("/api/scanner/status")
@protected_route
def scanner_status():
    return jsonify(state.SCANNER_STATE)

@app.route("/api/scanner/toggle", methods=['POST'])
@protected_route
def scanner_toggle():
    category = request.args.get("category")
    if category and category in state.SCANNER_STATE:
        state.SCANNER_STATE[category] = not state.SCANNER_STATE[category]
        logger.info(f"Scanner for '{category}' toggled via API to: {state.SCANNER_STATE[category]}")
        # Тут можна буде надсилати команду в Redis для processor-а
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
                yield ": ping\n\n"
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

# --------------- Startup ---------------
def main():
    db.init_db()
    logger.info("Database initialized.")

    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    if TELEGRAM_BOT_TOKEN:
        logger.info("Starting Telegram Updater.")
        updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        state.updater = updater
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
        dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        reactor.callInThread(updater.start_polling)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")

    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()