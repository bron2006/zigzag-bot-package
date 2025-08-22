import logging, os, json, time
from klein import Klein
from twisted.internet import reactor
from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.static import File
# --- ЗМІНА: Ці імпорти більше не потрібні для setup_and_run ---
# from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
# from spotware_connect import SpotwareConnect
import state
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS
# from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

# --- шляхи до фронтенду ---
WEB_DIR = os.path.join(os.path.dirname(__file__), "webapp")
INDEX_FILE = os.path.join(WEB_DIR, "index.html")

@app.route("/")
def home(request):
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

@app.route("/<path:filename>")
def static_files(request, filename):
    return File(WEB_DIR).render(request)

@app.route("/api/get_pairs", methods=['GET'])
def get_pairs(request):
    logger.info("API call received for /api/get_pairs")
    response_data = {
        "forex": FOREX_SESSIONS,
        "watchlist": [],
        "crypto": [],
        "stocks": []
    }
    logger.info(f"Sending pair data: {response_data}")
    json_bytes = json.dumps(response_data, ensure_ascii=False).encode('utf-8')
    request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
    request.setHeader(b'Content-Length', str(len(json_bytes)).encode('utf-8'))
    request.write(json_bytes)
    request.finish()
    return NOT_DONE_YET

# --- ЦІ ФУНКЦІЇ ЗАРАЗ НЕ ВИКОРИСТОВУЮТЬСЯ ---
def on_ctrader_ready():
    pass
def on_symbols_loaded(raw_message):
    pass
def on_symbols_error(failure):
    pass
# --- КІНЕЦЬ НЕВИКОРИСТОВУВАНИХ ФУНКЦІЙ ---

# --- ПОЧАТОК ЗМІН: Тимчасово вимикаємо все, крім веб-сервера ---
def setup_and_run():
    """
    ДІАГНОСТИЧНИЙ РЕЖИМ: Запускаємо тільки Klein Web Server.
    Ініціалізація Telegram Bot та cTrader Client тимчасово вимкнена.
    """
    logger.info("DIAGNOSTIC MODE: Initializing Klein Web Server ONLY.")
    # --- КОД НИЖЧЕ ТИМЧАСОВО ВИМКНЕНО ---
    # logger.info("Initializing components...")
    # if not TELEGRAM_BOT_TOKEN:
    #     logger.error("TELEGRAM_BOT_TOKEN not found!"); return
    # updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    # client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    # state.updater = updater
    # state.client = client
    # import telegram_ui
    # dp = updater.dispatcher
    # dp.add_handler(CommandHandler("start", telegram_ui.start))
    # dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    # dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    # dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    # updater.start_polling()
    # logger.info("Telegram bot started.")
    # client.on("ready", on_ctrader_ready)
    # client.start()
    # logger.info("cTrader client started.")
# --- КІНЕЦЬ ЗМІН ---

# --- Klein сервер ---
site = Site(app.resource())
reactor.listenTCP(8080, site, interface="0.0.0.0")

reactor.callWhenRunning(setup_and_run)
logger.info("Application setup complete. Reactor will run.")