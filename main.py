import logging
from klein import Klein
from twisted.internet import reactor
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import telegram_ui  # Імпортуємо модуль з вашими обробниками
from state import state # Імпортуємо глобальний модуль стану
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret, get_chat_id
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

@app.route("/")
def home(request):
    """Сторінка для перевірки стану, яку бачить fly.io."""
    status = "авторизований" if state.client and state.client.is_authorized else "не авторизований"
    return f"cTrader клієнт запущено, статус: {status}."

def on_ctrader_ready():
    """Викликається, коли клієнт cTrader готовий."""
    logger.info("cTrader клієнт готовий. Завантажую символи...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    """Обробляє та зберігає список символів у глобальному стані."""
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        # Зберігаємо символи у глобальному кеші state.py
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"Успішно завантажено та збережено {len(state.symbol_cache)} символів.")
    except Exception as e:
        logger.error(f"Помилка обробки символів: {e}")

def on_symbols_error(failure):
    """Обробляє помилку завантаження символів."""
    logger.error(f"Не вдалося завантажити символи: {failure.getErrorMessage()}")

def setup_and_run():
    """Налаштовує всі компоненти та запускає їх."""
    # 1. Налаштовуємо Telegram з вашими обробниками
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
    state.client = client  # Зберігаємо клієнт в глобальному стані
    client.on("ready", on_ctrader_ready)
    client.start()

# Запускаємо налаштування при старті реактора
reactor.callWhenRunning(setup_and_run)
logger.info("Налаштування програми завершено. Klein запускає reactor.")