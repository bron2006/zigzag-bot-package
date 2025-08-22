# main.py
import logging
from klein import Klein
from twisted.internet import reactor
from twisted.web.static import File
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import state
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

@app.route("/")
def home(request):
    status = "авторизований" if state.client and state.client.is_authorized else "не авторизований"
    return f"cTrader bot status: {status}."

# --- КЛЮЧОВА ЗМІНА: ДОДАЄМО ВІДДАЧУ СТАТИЧНИХ ФАЙЛІВ ---
@app.route("/webapp/", branch=True)
def webapp_files(request):
    logger.info(f"Serving static files from ./webapp/ for request: {request.uri.decode()}")
    return File("./webapp/")
# --- КІНЕЦЬ ЗМІНИ ---

def on_ctrader_ready():
    logger.info("cTrader client ready. Loading symbols...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Loaded {len(state.symbol_cache)} symbols.")
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
    state.updater = updater; state.client = client
    
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

# Запускаємо налаштування при старті реактора
reactor.callWhenRunning(setup_and_run)
logger.info("Application setup complete. Reactor will be started by run.py.")