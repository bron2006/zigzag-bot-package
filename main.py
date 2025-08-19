# main.py
import logging
import os
import json
import queue
import threading
from urllib.parse import parse_qs, unquote
from klein import Klein, NOT_DONE_YET
from twisted.internet import reactor, defer
from twisted.web.static import File
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

import state
from telegram_ui import start, menu, button_handler, reset_ui
from spotware_connect import SpotwareClient
from config import (
    get_telegram_token, get_ct_client_id, get_ct_client_secret, 
    get_fly_app_name, get_webhook_secret, FOREX_SESSIONS, CRYPTO_PAIRS_FULL, STOCKS_US_SYMBOLS
)
from db import get_watchlist, toggle_watch, get_signal_history, init_db
from analysis import get_api_detailed_signal_data
from mta_analysis import get_mta_signal

# --- Налаштування логування ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Ініціалізація ---
app = Klein()
TOKEN = get_telegram_token()
updates_queue = queue.Queue(maxsize=1000)

# --- Воркер для обробки оновлень ---
def dispatcher_worker():
    while True:
        try:
            update_data = updates_queue.get()
            if state.updater:
                update = Update.de_json(update_data, state.updater.bot)
                state.updater.dispatcher.process_update(update)
            updates_queue.task_done()
        except Exception as e:
            logger.exception(f"Помилка в воркері диспетчера: {e}")

# --- Ініціалізація Telegram ---
def init_telegram_bot():
    state.updater = Updater(TOKEN, use_context=True)
    dispatcher = state.updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, reset_ui))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    logger.info("✅ Обробники Telegram зареєстровані.")
    
    for _ in range(4):
        threading.Thread(target=dispatcher_worker, daemon=True).start()
    logger.info("✅ Воркери для обробки черги Telegram запущені.")

# --- Ініціалізація cTrader ---
def on_symbols_loaded(full_symbols):
    """Обробляє ПОВНИЙ список символів та коректно заповнює кеш."""
    temp_cache = {}
    
    for symbol_data in full_symbols:
        symbol_name = getattr(symbol_data, 'symbolName', None)
        symbol_id = getattr(symbol_data, 'symbolId', None)

        if not symbol_name or not symbol_id:
            continue

        normalized_name = symbol_name.replace("/", "").strip()
        
        temp_cache[normalized_name] = { "symbolId": symbol_id }
            
    state.symbol_cache.update(temp_cache)
    state.SYMBOLS_LOADED = True
    logger.info(f"✅ Кеш символів заповнено. Завантажено дані для {len(state.symbol_cache)} символів. Сервіс готовий.")


def init_ctrader_client():
    api_key = get_ct_client_id()
    api_secret = get_ct_client_secret()
    state.client = SpotwareClient(api_key, api_secret)
    state.client.on("fullSymbolsLoaded")(on_symbols_loaded)
    state.client.on("error")(lambda err: logger.error(f"Помилка cTrader: {err}"))
    state.client.connect()
    logger.info("Запущено підключення до cTrader API...")

# --- Допоміжна функція для WebApp ---
def parse_tg_init_data(init_data_str: str) -> dict | None:
    try:
        params = parse_qs(unquote(init_data_str))
        user_data_str = params.get('user', [None])[0]
        if user_data_str:
            return json.loads(user_data_str)
    except Exception as e:
        logger.error(f"Помилка парсингу initData: {e}")
    return None

# --- API ендпоінти для WebApp ---
@app.route('/api/get_ranked_pairs', methods=['GET'])
def get_ranked_pairs(request):
    request.setHeader('Content-Type', 'application/json')
    request.setHeader('Access-Control-Allow-Origin', '*')

    if not state.SYMBOLS_LOADED:
        return json.dumps({"status": "initializing"}).encode('utf-8')

    try:
        init_data = request.args.get(b'initData', [b''])[0].decode()
        user = parse_tg_init_data(init_data)
        watchlist = []
        if user and user.get('id'):
            watchlist = get_watchlist(user['id'])

        def format_pair(ticker):
            norm_ticker = ticker.replace("/", "").strip()
            return {"ticker": ticker, "active": norm_ticker in state.symbol_cache}

        response_data = {
            "watchlist": watchlist,
            "forex": {session: [format_pair(p) for p in pairs] for session, pairs in FOREX_SESSIONS.items()},
            "crypto": [format_pair(p) for p in CRYPTO_PAIRS_FULL],
            "stocks": [format_pair(p) for p in STOCKS_US_SYMBOLS]
        }
        
        return json.dumps({"status": "ready", "data": response_data}).encode('utf-8')
    except Exception:
        logger.exception("!!! ПОМИЛКА в /api/get_ranked_pairs")
        request.setResponseCode(500)
        return json.dumps({"status": "error", "error": "Internal Server Error"}).encode('utf-8')

@app.route('/api/toggle_watchlist', methods=['GET'])
def toggle_watchlist_api(request):
    init_data = request.args.get(b'initData', [b''])[0].decode()
    pair = request.args.get(b'pair', [b''])[0].decode()
    user = parse_tg_init_data(init_data)
    request.setHeader('Content-Type', 'application/json')
    request.setHeader('Access-Control-Allow-Origin', '*')
    if not user or not user.get('id') or not pair:
        request.setResponseCode(400)
        return json.dumps({"success": False, "error": "Invalid parameters"}).encode('utf-8')
    try:
        toggle_watch(user['id'], pair)
        return json.dumps({"success": True}).encode('utf-8')
    except Exception as e:
        logger.error(f"Помилка toggle_watchlist: {e}")
        request.setResponseCode(500)
        return json.dumps({"success": False, "error": "Database error"}).encode('utf-8')

@app.route('/api/signal', methods=['GET'])
def get_signal_api(request):
    pair = request.args.get(b'pair', [b''])[0].decode()
    init_data = request.args.get(b'initData', [b''])[0].decode()
    user = parse_tg_init_data(init_data)
    user_id = user.get('id') if user else None
    request.setHeader('Content-Type', 'application/json')
    request.setHeader('Access-Control-Allow-Origin', '*')
    if not pair:
        request.setResponseCode(400)
        return json.dumps({"error": "Pair parameter is required"}).encode('utf-8')
    
    d = get_api_detailed_signal_data(state.client, pair, user_id)
    def on_success(result):
        request.write(json.dumps(result).encode('utf-8'))
        request.finish()
    def on_error(failure):
        logger.error(f"API /api/signal: Помилка: {failure.getErrorMessage()}")
        request.setResponseCode(500)
        error_response = {"error": f"Внутрішня помилка сервера."}
        request.write(json.dumps(error_response).encode('utf-8'))
        request.finish()
    d.addCallbacks(on_success, on_error)
    
    return NOT_DONE_YET

@app.route('/api/get_mta', methods=['GET'])
def get_mta_api(request):
    pair = request.args.get(b'pair', [b''])[0].decode()
    request.setHeader('Content-Type', 'application/json')
    request.setHeader('Access-Control-Allow-Origin', '*')
    if not pair:
        request.setResponseCode(400)
        return json.dumps({"error": "Pair parameter is required"}).encode('utf-8')

    d = get_mta_signal(state.client, pair)
    def on_success(result):
        request.write(json.dumps(result).encode('utf-8'))
        request.finish()
    def on_error(failure):
        logger.error(f"API /api/get_mta: Помилка: {failure.getErrorMessage()}")
        request.setResponseCode(500)
        error_response = {"error": f"Внутрішня помилка сервера."}
        request.write(json.dumps(error_response).encode('utf-8'))
        request.finish()
    d.addCallbacks(on_success, on_error)

    return NOT_DONE_YET

@app.route('/api/signal_history', methods=['GET'])
def get_signal_history_api(request):
    init_data = request.args.get(b'initData', [b''])[0].decode()
    pair = request.args.get(b'pair', [b''])[0].decode()
    user = parse_tg_init_data(init_data)
    request.setHeader('Content-Type', 'application/json')
    request.setHeader('Access-Control-Allow-Origin', '*')
    if not user or not user.get('id') or not pair:
        request.setResponseCode(400)
        return json.dumps([]).encode('utf-8')
    history = get_signal_history(user['id'], pair)
    return json.dumps(history).encode('utf-8')

# --- Веб-ручки ---
@app.route(f"/{TOKEN}", methods=['POST'])
def webhook_handler(request):
    try:
        body = request.content.read()
        if request.getHeader("X-Telegram-Bot-Api-Secret-Token") != get_webhook_secret():
            request.setResponseCode(403)
            return b"Forbidden"
        update_data = json.loads(body.decode())
        updates_queue.put_nowait(update_data)
        request.setResponseCode(200)
        return b"OK"
    except queue.Full:
        request.setResponseCode(503)
        return b"Busy"
    except Exception:
        request.setResponseCode(400)
        return b"Bad Request"

@app.route("/health")
def health_check(request):
    request.setResponseCode(200)
    return b"OK"

@app.route("/")
def home(request):
    app_name = get_fly_app_name()
    if app_name:
        webapp_url = f"https://{app_name}.fly.dev/webapp/index.html"
        request.redirect(webapp_url.encode('utf-8'))
        request.finish()
        return b""
    else:
        return b"Telegram Bot and Web Service is running"

@app.route('/webapp/', branch=True)
def webapp_static(request):
    return File("./webapp")

def setup_webhook():
    app_name = get_fly_app_name()
    if app_name and state.updater:
        webhook_url = f"https://{app_name}.fly.dev/{TOKEN}"
        state.updater.bot.set_webhook(url=webhook_url, secret_token=get_webhook_secret())
        logger.info(f"Вебхук встановлено за адресою: {webhook_url}")
    else:
        logger.warning("Не вдалося встановити вебхук.")

# --- Запуск сервісів ---
init_db()
logger.info("✅ Базу даних ініціалізовано.")
init_telegram_bot()
reactor.callWhenRunning(setup_webhook)
reactor.callWhenRunning(init_ctrader_client)