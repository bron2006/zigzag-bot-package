# main.py
import logging
from klein import Klein
from twisted.internet import reactor
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from spotware_connect import SpotwareConnect
from telegram_ui import TelegramUI
from state import AppState
from config import get_ct_client_id, get_ct_client_secret

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Ініціалізація компонентів ---
app = Klein()
app_state = AppState()
telegram_bot = TelegramUI(app_state)
client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())

@app.route("/")
def home(request):
    """Сторінка для перевірки стану."""
    status = "connected and authorized" if client.is_authorized else "running but not authorized"
    return f"cTrader client is {status}."

def on_ctrader_ready():
    """Викликається, коли клієнт cTrader готовий."""
    logger.info("cTrader Client готовий. Надсилаю сповіщення...")
    account_id = client._client.account_id
    telegram_bot.send_startup_message(account_id)
    
    deferred = client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    """Обробляє та зберігає список символів."""
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        app_state.set_symbols(symbols_response.symbol)
        
        count = len(app_state.get_symbols())
        logger.info(f"Успішно завантажено та збережено {count} символів.")
        telegram_bot.send_message(f"📚 Завантажено {count} символів.")
    except Exception as e:
        logger.error(f"Помилка обробки символів: {e}")
        telegram_bot.send_message(f"❌ Виникла помилка при обробці списку символів.")

def on_symbols_error(failure):
    """Обробляє помилку завантаження символів."""
    error_message = failure.getErrorMessage()
    logger.error(f"Не вдалося завантажити символи: {error_message}")
    telegram_bot.send_message(f"❌ Помилка завантаження символів: {error_message}")

# --- Запуск ---
client.on("ready", on_ctrader_ready)
reactor.callWhenRunning(client.start)
logger.info("Налаштування програми завершено. Klein запускає reactor.")