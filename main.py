# main.py
import logging
from klein import Klein
from twisted.internet import reactor
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import state
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret
# <-- Імпортуємо правильний тип відповіді
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetSymbolsRes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

@app.route("/")
def home(request):
    status = "авторизований" if state.client and state.client.is_authorized else "не авторизований"
    return f"cTrader клієнт запущено, статус: {status}."

def on_ctrader_ready():
    """Викликається, коли клієнт cTrader готовий. Завантажує ПОВНІ символи."""
    logger.info("cTrader клієнт готовий. Завантажую повний список символів...")
    # <-- ВИКЛИКАЄМО НОВИЙ МЕТОД
    deferred = state.client.get_all_symbols_full() 
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    """Обробляє та зберігає ПОВНИЙ список символів у глобальному стані."""
    try:
        # <-- ВИКОРИСТОВУЄМО ПРАВИЛЬНИЙ ТИП ВІДПОВІДІ
        symbols_response = ProtoOAGetSymbolsRes()
        symbols_response.ParseFromString(raw_message.payload)
        
        # Зберігаємо символи у глобальному кеші. Тепер це будуть повні ProtoOASymbol
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Успішно завантажено та збережено {len(state.symbol_cache)} повних символів.")
    except Exception as e:
        logger.error(f"Помилка обробки символів: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Не вдалося завантажити символи: {failure.getErrorMessage()}")

def setup_and_run():
    logger.info("Ініціалізація компонентів...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не знайдено!"); return

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.updater = updater; state.client = client
    
    import telegram_ui
    logger.info("Модуль telegram_ui імпортовано.")

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    logger.info("Обробники Telegram зареєстровано.")
    
    updater.start_polling()
    logger.info("Telegram bot запущено в режимі polling.")

    client.on("ready", on_ctrader_ready)
    client.start()
    logger.info("cTrader клієнт запущено.")

reactor.callWhenRunning(setup_and_run)
logger.info("Налаштування програми завершено. Klein запускає reactor.")