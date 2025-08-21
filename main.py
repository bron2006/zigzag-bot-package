import logging
from klein import Klein
from twisted.internet import reactor
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import telegram_ui  # Імпортуємо модуль з обробниками
from state import state # Імпортуємо глобальний модуль стану
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Ініціалізація ---
app = Klein()

@app.route("/")
def home(request):
    status = "авторизований" if state.client and state.client.is_authorized else "не авторизований"
    return f"cTrader клієнт запущено, статус: {status}."

def on_ctrader_ready():
    logger.info("cTrader клієнт готовий. Завантажую символи...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"Успішно завантажено та збережено {len(state.symbol_cache)} символів.")
    except Exception as e: logger.error(f"Помилка обробки символів: {e}")

def on_symbols_error(failure):
    logger.error(f"Не вдалося завантажити символи: {failure.getErrorMessage()}")

def setup_and_run():
    """Налаштовує всі компоненти та запускає їх."""
    # 1. Налаштовуємо Telegram
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не знайдено!"); return
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.text("МЕНЮ"), telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    updater.start_polling()
    logger.info("Telegram bot запущено.")

    # 2. Налаштовуємо cTrader
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    client.start()

# --- Запуск ---
reactor.callWhenRunning(setup_and_run)
logger.info("Налаштування програми завершено. Klein запускає reactor.")