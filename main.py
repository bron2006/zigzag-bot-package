import logging
import os
import json
import queue
import threading
from urllib.parse import parse_qs, unquote
from klein import Klein
from twisted.internet import reactor, defer
from telegram import Update, KeyboardButton, WebAppInfo # Додано
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters # Додано

import state
from telegram_ui import start, button_handler, menu # Додано menu
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


# --- Воркер для обробки оновлень з черги ---
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
    
    # Додаємо всі обробники згідно з новою логікою
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))

    logger.info("✅ Обробники Telegram зареєстровані.")
    
    for _ in range(4):
        threading.Thread(target=dispatcher_worker, daemon=True).start()
    logger.info("✅ Воркери для обробки черги Telegram запущені.")


# --- Ініціалізація cTrader ---
def on_symbols_loaded(symbols):
    temp_cache = {}
    for s in symbols:
        if "symbolName" in s:
            normalized_name = s["symbolName"].replace("/", "").strip()
            temp_cache[normalized_name] = { "symbolId": s.get("symbolId") }
    state.symbol_cache.update(temp_cache)
    logger.info("✅ Кеш символів заповнено (%s символів)", len(state.symbol_cache))

def init_ctrader_client():
    api_key = get_ct_client_id()
    api_secret = get_ct_client_secret()
    state.client = SpotwareClient(api_key, api_secret)
    state.client.on("symbolsLoaded")(on_symbols_loaded)
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
    try:
        # ... (код залишається без змін)
        return json.dumps(response_data).encode('utf-8')
    except Exception:
        # ... (код залишається без змін)
        return json.dumps(error_response).encode('utf-8')


@app.route('/api/toggle_watchlist', methods=['GET'])
def toggle_watchlist_api(request):
    # ... (код залишається без змін)


@app.route('/api/signal', methods=['GET'])
def get_signal_api(request):
    """Основний ендпоінт для отримання детального сигналу."""
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
    
    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    def on_success(result):
        """Обробник успішного результату."""
        request.write(json.dumps(result).encode('utf-8'))
        request.finish()

    def on_error(failure):
        """Обробник помилки."""
        logger.error(f"API /api/signal: Помилка при отриманні сигналу для '{pair}': {failure.getErrorMessage()}")
        request.setResponseCode(500)
        error_response = {"error": f"Внутрішня помилка сервера при аналізі {pair}."}
        request.write(json.dumps(error_response).encode('utf-8'))
        request.finish()
        
    d.addCallbacks(on_success, on_error)
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
    
    return defer.SUCCESS


@app.route('/api/get_mta', methods=['GET'])
def get_mta_api(request):
    # ... (код залишається без змін)


@app.route('/api/signal_history', methods=['GET'])
def get_signal_history_api(request):
    # ... (код залишається без змін)


# --- Веб-ручки (Web Routes) ---

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook_handler(request):
    # ... (код залишається без змін)

@app.route("/health")
def health_check(request):
    # ... (код залишається без змін)

@app.route("/")
def home(request):
    # ... (код залишається без змін)

# Додаємо обслуговування статичних файлів для WebApp
from twisted.web.static import File
@app.route('/webapp/', branch=True)
def webapp_static(request):
    # Використовуємо відносний шлях до папки webapp
    return File("./webapp")


def setup_webhook():
    # ... (код залишається без змін)

# --- Запуск сервісів ---
init_db()
logger.info("✅ Базу даних ініціалізовано.")
init_telegram_bot()
reactor.callWhenRunning(setup_webhook)
reactor.callWhenRunning(init_ctrader_client)