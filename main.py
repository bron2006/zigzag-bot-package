import logging
import os
import json
from klein import Klein
from twisted.internet import asyncioreactor
asyncioreactor.install()

import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

import state
from telegram_ui import start, button_handler
from spotware_connect import SpotwareClient

# --- Логування ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Klein App ---
app = Klein()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def init_telegram_bot():
    """Ініціалізує Application і зберігає його в state."""
    if not TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN не встановлено!")
        return

    state.application = Application.builder().token(TOKEN).build()
    state.application.add_handler(CommandHandler("start", start))
    state.application.add_handler(CallbackQueryHandler(button_handler))

    await state.application.initialize()
    await state.application.start()
    logger.info("Telegram Application успішно ініціалізовано і запущено.")


def on_symbols_loaded(symbols):
    temp_cache = {}
    for s in symbols:
        if "symbolName" in s:
            normalized_name = s["symbolName"].replace("/", "").strip()
            temp_cache[normalized_name] = s
    state.symbol_cache.update(temp_cache)
    logger.info("✅ Кеш символів заповнено (%s символів)", len(state.symbol_cache))


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


@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook_handler(request):
    """Приймає оновлення від Telegram і передає їх у Application."""
    try:
        raw = await request.content.read()
        data = json.loads(raw.decode("utf-8"))
        update = Update.de_json(data, state.application.bot)
        await state.application.update_queue.put(update)
    except Exception as e:
        logger.error(f"Помилка обробки оновлення: {e}")
    return b""


@app.route("/")
def home(request):
    return b"Telegram Bot and Web Service is running"


async def setup_webhook():
    app_name = os.getenv("FLY_APP_NAME")
    if app_name and state.application:
        webhook_url = f"https://{app_name}.fly.dev/{TOKEN}"
        await state.application.bot.set_webhook(webhook_url)
        logger.info(f"Вебхук встановлено за адресою: {webhook_url}")
    else:
        logger.warning("Не вдалося встановити вебхук.")


async def main():
    await init_telegram_bot()
    await setup_webhook()
    init_ctrader_client()

    from twisted.internet import reactor
    reactor.run(installSignalHandlers=False)


if __name__ == "__main__":
    asyncio.run(main())
