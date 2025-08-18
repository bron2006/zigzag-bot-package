import logging
import os
import json
from klein import Klein
from twisted.internet import reactor
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
)

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

# --- Telegram Application ---
if not TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN не встановлено! Бот не може запуститись.")
    raise SystemExit(1)

state.application = Application.builder().token(TOKEN).build()


def register_bot_handlers():
    if not state.application:
        logger.error("Application не ініціалізовано.")
        return
    state.application.add_handler(CommandHandler("start", start))
    state.application.add_handler(CallbackQueryHandler(button_handler))
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
@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook_handler(request):
    """Приймає оновлення від Telegram і передає їх у application."""
    try:
        raw_data = await request.content.read()
        data = json.loads(raw_data.decode("utf-8"))
        update = Update.de_json(data, state.application.bot)
        await state.application.update_queue.put(update)
        logger.debug(f"Отримано оновлення: {data}")
    except Exception as e:
        logger.error(f"Помилка обробки оновлення: {e}")
    return b""


@app.route("/")
def home(request):
    return b"Telegram Bot and Web Service is running"


def setup_webhook():
    """Встановлює вебхук при запуску додатку."""
    app_name = os.getenv("FLY_APP_NAME")
    if app_name and state.application:
        webhook_url = f"https://{app_name}.fly.dev/{TOKEN}"
        reactor.callInThread(state.application.bot.set_webhook, url=webhook_url)
        logger.info(f"Вебхук встановлено за адресою: {webhook_url}")
    else:
        logger.warning("Не вдалося встановити вебхук (FLY_APP_NAME або application не знайдено).")


# --- Запуск сервісів ---
# Application працює як фоновий процес у власному asyncio loop
reactor.callWhenRunning(lambda: state.application.run_polling(stop_signals=None))
reactor.callWhenRunning(setup_webhook)
reactor.callWhenRunning(init_ctrader_client)
