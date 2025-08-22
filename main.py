import logging
import os
from klein import Klein
from twisted.internet import reactor
from twisted.web.server import Site
from twisted.web.static import File
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import state
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

# --- Статичні файли ---
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

@app.route("/")
def home(request):
    index_path = os.path.join(WEBAPP_DIR, "index.html")
    try:
        with open(index_path, "rb") as f:
            request.setHeader(b"content-type", b"text/html; charset=utf-8")
            return f.read()
    except Exception as e:
        logger.error(f"Не вдалося відкрити index.html: {e}")
        return b"Помилка завантаження сторінки."

# /static/* → папка webapp
app.resource().putChild(b"static", File(WEBAPP_DIR.encode()))

# --- API endpoint для статусу ---
@app.route("/status")
def status(request):
    status = "авторизований" if state.client and state.client.is_authorized else "не авторизований"
    request.setHeader(b"content-type", b"application/json; charset=utf-8")
    return f'{{"status": "{status}"}}'

def on_ctrader_ready():
    logger.info("cTrader client is ready. Loading symbols...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Successfully loaded {len(state.symbol_cache)} light symbols.")
    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

def setup_and_run():
    logger.info("Initializing components...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found!"); return

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.updater = updater
    state.client = client
    
    import telegram_ui
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    
    updater.start_polling()
    logger.info("Telegram bot started.")

    client.on("ready", on_ctrader_ready)
    client.start()
    logger.info("cTrader client started.")

# --- Запуск Klein-сервера ---
site = Site(app.resource())
reactor.listenTCP(8080, site, interface="0.0.0.0")

reactor.callWhenRunning(setup_and_run)
logger.info("Application setup complete. Reactor will run.")
