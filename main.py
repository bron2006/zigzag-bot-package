import logging
import os
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from spotware_connect import SpotwareClient

from telegram_ui import start, button_handler

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

client: SpotwareClient = None
symbol_cache = {}

def init_client():
    global client, symbol_cache
    api_key = os.getenv("CT_CLIENT_ID")
    api_secret = os.getenv("CT_CLIENT_SECRET")

    client = SpotwareClient(api_key, api_secret)
    client.connect()

    @client.on("symbolsLoaded")
    def on_symbols(symbols):
        global symbol_cache
        symbol_cache = {s["symbolId"]: s for s in symbols}
        logger.info("✅ Symbol cache populated (%s symbols)", len(symbol_cache))


def main():
    global client
    init_client()

    updater = Updater(os.getenv("TELEGRAM_BOT_TOKEN"))
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
