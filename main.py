import logging
import os
from klein import Klein
from twisted.internet import reactor
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

import state
from telegram_ui import start, button_handler
from spotware_connect import SpotwareClient

# --- Налаштування логування ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Створення екземпляру веб-додатку Klein ---
app = Klein()

# --- Логіка ініціалізації ---

def register_bot_handlers():
    if not state.updater:
        logger.error("Updater не ініціалізовано.")
        return
    dispatcher = state.updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    logger.info("✅ Обробники Telegram зареєстровані.")

def on_symbols_loaded(symbols):
    temp_cache = {}
    for s in symbols:
        if "symbolName" in s:
            normalized_name = s["symbolName"].replace("/", "").strip()
            temp_cache[normalized_name] = s
    state.symbol_cache.update(temp_cache)
    logger.info("✅ Кеш символів заповнено (%s символів)", len(state.symbol_cache))
    register_bot_handlers()

def init_ctrader_client():
    api_key = os.getenv("CT_CLIENT_ID")
    api_secret = os.getenv("CT_CLIENT_SECRET")
    if not all([api_key, api_secret]):
        logger.critical("CT_CLIENT_ID або CT_CLIENT_SECRET не встановлено.")
        return

    state.client = SpotwareClient(api_key, api_secret)
    state.client.on("symbolsLoaded")(on_symbols_loaded)
    state.client.on("error")(lambda err: logger.error(f"Помилка cTrader: {err}"))
    state.client.connect()
    logger.info("Запущено підключення до cTrader API...")

def init_telegram_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("TELEGRAM_BOT_TOKEN не встановлено.")
        return
    state.updater = Updater(token)
    state.updater.start_polling()
    logger.info("Бот запущений в режимі polling.")

# --- Реєстрація подій Twisted ---

@app.handle_errors(Exception)
def handle_errors(request, failure):
    logger.error(f"Помилка обробки запиту: {failure.getErrorMessage()}")
    request.setResponseCode(500)
    return b"Internal Server Error"

@app.route("/")
def home(request):
    """Проста сторінка-заглушка для веб-інтерфейсу."""
    request.setHeader('Content-Type', 'text/html; charset=utf-8')
    return b"<h1>Telegram Bot and Web Service is running</h1>"

# --- Запуск сервісів при старті Twisted Reactor ---

# reactor.callWhenRunning реєструє функції, які мають виконатись,
# коли цикл подій Twisted буде запущено (тобто командою app.run()).
reactor.callWhenRunning(init_telegram_bot)
reactor.callWhenRunning(init_ctrader_client)