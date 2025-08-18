import logging
import os
import json
from klein import Klein
from twisted.internet import reactor
from telegram import Update
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

# --- Ініціалізація Klein App ---
app = Klein()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def init_telegram_bot():
    """Ініціалізує Updater і зберігає його в спільному стані."""
    if not TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN не встановлено! Бот не може запуститись.")
        return
    # Створюємо екземпляр Updater. Він автоматично створює bot та dispatcher з воркерами.
    state.updater = Updater(TOKEN, use_context=True)
    logger.info("Telegram Updater успішно ініціалізовано.")

# --- Логіка ініціалізації cTrader ---
def register_bot_handlers():
    if not state.updater:
        logger.error("Updater не ініціалізовано.")
        return
    # Використовуємо dispatcher, який належить updater'у
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

# --- Веб-ручки (Web Routes) ---

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook_handler(request):
    """Приймає оновлення від Telegram."""
    if state.updater:
        try:
            update_data = json.loads(request.content.read().decode())
            update = Update.de_json(update_data, state.updater.bot)
            state.updater.dispatcher.process_update(update)
        except Exception as e:
            logger.error(f"Помилка обробки оновлення: {e}")
    return ""

@app.route("/")
def home(request):
    """Сторінка-заглушка."""
    return b"Telegram Bot and Web Service is running"

def setup_webhook():
    """Встановлює вебхук при запуску додатку."""
    app_name = os.getenv("FLY_APP_NAME")
    if app_name and state.updater:
        webhook_url = f"https://{app_name}.fly.dev/{TOKEN}"
        state.updater.bot.set_webhook(webhook_url)
        logger.info(f"Вебхук встановлено за адресою: {webhook_url}")
    else:
        logger.warning("Не вдалося встановити вебхук (FLY_APP_NAME або updater не знайдено).")


# --- Запуск сервісів ---
init_telegram_bot() # Ініціалізуємо бота до запуску reactor
reactor.callWhenRunning(setup_webhook)
reactor.callWhenRunning(init_ctrader_client)