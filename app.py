# app.py
import logging
import os
import json
import time
import queue
import itertools
import signal
from functools import wraps

from twisted.internet import reactor, threads
from twisted.internet.task import LoopingCall
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource

from flask import Flask, jsonify, send_from_directory, Response, request
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

import state
import telegram_ui
import db
from auth import is_valid_init_data, get_user_id_from_init_data
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from analysis import get_api_detailed_signal_data
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from redis_client import get_redis

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("app")

# ---------------------------
# Flask (через Twisted WSGI)
# ---------------------------
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

# ---------------------------
# Глобальний стан програми
# ---------------------------
state.symbol_cache = {}
state.spotware_client = None
state.scanner_loop = None
state.last_alert_ts = {}
state.assets = []
state.updater = None
state.ready = False

# ---------------------------
# Допоміжні утиліти
# ---------------------------
def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def _flatten_assets():
    forex = set(a.replace("/", "") for a in itertools.chain.from_iterable(FOREX_SESSIONS.values()))
    crypto = set(a.replace("/", "") for a in CRYPTO_PAIRS)
    commod = set(a.replace("/", "") for a in COMMODITIES)
    return sorted(forex | crypto | commod)

def _category_of(symbol_no_slash: str) -> str:
    s = symbol_no_slash
    if any(s == a.replace("/", "") for a in itertools.chain.from_iterable(FOREX_SESSIONS.values())):
        return "forex"
    if any(s == a.replace("/", "") for a in CRYPTO_PAIRS):
        return "crypto"
    if any(s == a.replace("/", "") for a in COMMODITIES):
        return "commodities"
    return "forex"

def _scanner_enabled(cat: str) -> bool:
    r = get_redis()
    key = f"scanner_state:{cat}"
    val = r.get(key)
    return True if val == 'true' else False

def _set_scanner(cat: str, enabled: bool):
    r = get_redis()
    r.set(f"scanner_state:{cat}", 'true' if enabled else 'false')

def _cooldown_ok(pair: str) -> bool:
    last = state.last_alert_ts.get(pair, 0)
    return (time.time() - last) >= max(5, SCANNER_COOLDOWN_SECONDS)

def _mark_alert(pair: str):
    state.last_alert_ts[pair] = time.time()

# ---------------------------
# Flask маршрути
# ---------------------------
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
        logger.exception("home() failed")
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
        "forex": forex_data,
        "crypto": CRYPTO_PAIRS,
        "stocks": STOCK_TICKERS,
        "commodities": COMMODITIES,
        "watchlist": watchlist
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
    
    # --- ПОЧАТОК ЗМІН: Виправлено виклик функції ---
    d = get_api_detailed_signal_data(state.spotware_client, state.symbol_cache, pair_normalized, user_id, timeframe)
    # --- КІНЕЦЬ ЗМІН ---
    
    done_q = queue.Queue()
    d.addCallbacks(lambda res: done_q.put(res), lambda f: done_q.put({"error": str(f.value)}))
    try:
        result = done_q.get(timeout=8)
        return jsonify(result)
    except queue.Empty:
        return jsonify({"error": "Request timed out."}), 504

@app.route("/api/scanner/status")
@protected_route
def scanner_status():
    r = get_redis()
    keys = ["scanner_state:forex", "scanner_state:crypto", "scanner_state:commodities"]
    status = {k.split(":")[-1]: (r.get(k) == 'true') for k in keys}
    return jsonify(status)

@app.route("/api/scanner/toggle", methods=['POST'])
@protected_route
def scanner_toggle():
    category = request.args.get("category")
    if not category:
        return jsonify({}), 400
    new_state = not _scanner_enabled(category)
    _set_scanner(category, new_state)
    logger.info(f"Scanner for '{category}' toggled to: {new_state}")
    return scanner_status()

# ---------------------------
# Telegram бот
# ---------------------------
def _start_telegram():
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; bot disabled.")
        return None

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    reactor.callInThread(updater.start_polling)
    logger.info("Telegram bot polling started.")
    return updater

# ---------------------------
# cTrader клієнт
# ---------------------------
def _on_ct_symbols_loaded(raw_message):
    res = ProtoOASymbolsListRes()
    res.ParseFromString(raw_message.payload)
    state.symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
    state.assets = _flatten_assets()
    logger.info(f"Loaded {len(state.symbol_cache)} symbols; assets to scan: {len(state.assets)}")
    state.ready = True

    if state.scanner_loop is None:
        state.scanner_loop = LoopingCall(_scanner_tick)
        state.scanner_loop.start(60.0, now=False)
        logger.info("Market scanner started (LoopingCall every 60s).")

def _on_ct_ready():
    logger.info("cTrader client ready, loading symbols...")
    d = state.spotware_client.get_all_symbols()
    d.addCallbacks(_on_ct_symbols_loaded, lambda f: logger.error(f"Failed to load symbols: {f}"))

def _start_ctrader():
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.spotware_client = client
    client.on("ready", _on_ct_ready)
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client connecting...")

# ---------------------------
# Фоновий сканер
# ---------------------------
def _scanner_tick():
    if not state.ready or not state.assets:
        logger.info("Scanner waiting for symbols...")
        return

    timeframe = "5m"
    threshold = max(50, min(IDEAL_ENTRY_THRESHOLD, 100))

    def _handle_pair(pair):
        cat = _category_of(pair)
        if not _scanner_enabled(cat):
            return

        # --- ПОЧАТОК ЗМІН: Виправлено виклик функції ---
        d = get_api_detailed_signal_data(state.spotware_client, state.symbol_cache, pair, 0, timeframe)
        # --- КІНЕЦЬ ЗМІН ---

        def on_ok(res):
            if not isinstance(res, dict) or "bull_percentage" not in res:
                return
            score = int(res.get("bull_percentage", 50))
            strong = (score >= threshold) or (score <= (100 - threshold))
            if strong and _cooldown_ok(pair):
                try:
                    res['pair'] = res.get('pair', pair)
                    res['timeframe'] = timeframe
                    _mark_alert(pair)
                    if state.updater:
                        telegram_ui.send_scanner_notification(state.updater.bot, res)
                        logger.info(f"Scanner ALERT sent for {pair} ({score})")
                except Exception:
                    logger.exception("Failed to send Telegram notification")
        def on_err(f):
            logger.debug(f"scan {pair} error: {getattr(f, 'value', f)}")

        d.addCallbacks(on_ok, on_err)

    batch = state.assets[:80]
    for p in batch:
        reactor.callLater(0, _handle_pair, p)

# ---------------------------
# Старт програми
# ---------------------------
def _install_signal_handlers():
    def _graceful_stop(*_args):
        try:
            if state.updater:
                state.updater.stop()
            if reactor.running:
                reactor.stop()
        finally:
            os._exit(0)
    try:
        signal.signal(signal.SIGINT, _graceful_stop)
        signal.signal(signal.SIGTERM, _graceful_stop)
    except Exception:
        pass

def main():
    db.init_db()
    state.updater = _start_telegram()
    _start_ctrader()

    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    for cat in ("forex", "crypto", "commodities"):
        r = get_redis()
        key = f"scanner_state:{cat}"
        if r.get(key) not in ('true', 'false'):
            r.set(key, 'false')

    _install_signal_handlers()
    logger.info("Starting Twisted reactor.")
    reactor.run()

if __name__ == "__main__":
    main()