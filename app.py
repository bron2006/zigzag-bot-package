# app.py
import logging
import os
import json
import time
import queue
from functools import wraps

from twisted.internet import reactor, threads
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource

from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

import state
import telegram_ui
import db
from auth import is_valid_init_data, get_user_id_from_init_data
from config import (
    TELEGRAM_BOT_TOKEN, FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS
)
from analysis import PERIOD_MAP
from redis_client import get_redis

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
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def _listen_for_notifications():
    logger.info("Starting Redis Pub/Sub listener for notifications...")
    r = get_redis()
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("telegram_notifications")
    for message in pubsub.listen():
        try:
            data = json.loads(message['data'])
            logger.info(f"Received signal for notification: {data.get('pair')}")
            if hasattr(state, "updater"):
                telegram_ui.send_scanner_notification(state.updater.bot, data)
        except Exception as e:
            logger.exception(f"Error processing notification: {e}")

@app.route("/")
def home():
    try:
        with open(os.path.join(WEBAPP_DIR, "index.html"), "r", encoding="utf-8") as f:
            content = f.read()
        app_name = get_fly_app_name() or "zigzag-bot-package"
        api_base_url = f"https://{app_name}.fly.dev"
        content = content.replace("{{API_BASE_URL}}", api_base_url)
        return Response(content, mimetype='text/html')
    except Exception:
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
    from analysis import get_api_detailed_signal_data
    pair = request.args.get("pair")
    timeframe = request.args.get("timeframe", "15m")
    if not pair: return jsonify({"error": "pair is required"}), 400
    
    pair_normalized = pair.replace("/", "")
    user_id = get_user_id_from_init_data(request.args.get("initData"))
    
    d = get_api_detailed_signal_data(None, None, pair_normalized, user_id, timeframe)
    done_q = queue.Queue()
    def cb_success(res): done_q.put(res)
    def cb_err(f): done_q.put({"error": str(f.value)})
    d.addCallbacks(cb_success, cb_err)
    try:
        result = done_q.get(timeout=5)
        return jsonify(result)
    except queue.Empty:
        return jsonify({"error": "Request timed out."}), 504

@app.route("/api/scanner/status")
@protected_route
def scanner_status():
    r = get_redis()
    keys = ["scanner_state:forex", "scanner_state:crypto", "scanner_state:commodities"]
    status = {k.split(":")[-1]: r.get(k) == 'true' for k in keys}
    return jsonify(status)

@app.route("/api/scanner/toggle", methods=['POST'])
@protected_route
def scanner_toggle():
    category = request.args.get("category")
    if not category: return jsonify({}), 400
    r = get_redis()
    key = f"scanner_state:{category}"
    current_state = r.get(key) == 'true'
    new_state = not current_state
    r.set(key, 'true' if new_state else 'false')
    logger.info(f"Scanner for '{category}' toggled via WEB APP to: {new_state}")
    
    keys = ["scanner_state:forex", "scanner_state:crypto", "scanner_state:commodities"]
    status = {k.split(":")[-1]: r.get(k) == 'true' for k in keys}
    return jsonify(status)

def main():
    db.init_db()
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    if TELEGRAM_BOT_TOKEN:
        updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        state.updater = updater
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
        reactor.callInThread(updater.start_polling)
        reactor.callInThread(_listen_for_notifications)

    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()