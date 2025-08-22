import logging, os, json, time
from klein import Klein
from twisted.internet import reactor
from twisted.web.server import Site
from twisted.web.static import File
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import state
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

# --- шляхи до фронтенду ---
WEB_DIR = os.path.join(os.path.dirname(__file__), "webapp")
INDEX_FILE = os.path.join(WEB_DIR, "index.html")

@app.route("/")
def home(request):
    """
    Читає index.html, додає cache busting і віддає його клієнту,
    забороняючи кешування самої сторінки.
    """
    logger.info("Dynamic index.html page requested. Applying cache busting...")

    request.setHeader(b"content-type", b"text/html; charset=utf-8")
    request.setHeader(b"Cache-Control", b"no-cache, no-store, must-revalidate")
    
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        
        cache_buster = int(time.time())
        content = content.replace("script.js", f"script.js?v={cache_buster}")
        content = content.replace("style.css", f"style.css?v={cache_buster}")

        return content.encode("utf-8")
    except Exception as e:
        logger.error(f"Error serving index.html: {e}", exc_info=True)
        request.setResponseCode(500)
        return b"Internal Server Error"

# --- ПОЧАТОК ЗМІН: Спрощуємо віддачу статичних файлів ---
@app.route("/<path:filename>")
def static_files(request, filename):
    """
    Віддає статичні файли (js, css).
    Ми прибираємо ручну перевірку os.path.exists, оскільки вона не працює
    з параметрами запиту (cache busting). Довіряємо це Twisted.
    """
    return File(WEB_DIR).render(request)
# --- КІНЕЦЬ ЗМІН ---

# --- API ендпоінт для веб-додатку ---
@app.route("/api/get_pairs", methods=['GET'])
def get_pairs(request):
    """
    Віддає статичний список пар для WebApp.
    """
    logger.info("API call received for /api/get_pairs")
    request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
    
    response_data = {
        "forex": FOREX_SESSIONS,
        "watchlist": [],
        "crypto": [],
        "stocks": []
    }
    return json.dumps(response_data).encode('utf-8')

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

# --- Klein сервер ---
site = Site(app.resource())
reactor.listenTCP(8080, site, interface="0.0.0.0")

reactor.callWhenRunning(setup_and_run)
logger.info("Application setup complete. Reactor will run.")