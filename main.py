import logging
from klein import Klein
from twisted.internet import reactor
# Імпортуємо конкретний тип відповіді, щоб "розпакувати" в нього
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from spotware_connect import SpotwareConnect
from telegram_ui import TelegramUI
from config import get_ct_client_id, get_ct_client_secret

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Ініціалізація основних компонентів ---
app = Klein()
telegram_bot = TelegramUI()
client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())

@app.route("/")
def home(request):
    logger.info("Web root requested.")
    if client.is_authorized:
        return "cTrader client is connected and authorized."
    else:
        return "cTrader client is running but not authorized yet."

def on_ctrader_ready():
    logger.info("cTrader Client is ready. Notifying user via Telegram.")
    account_id = client._client.account_id
    telegram_bot.send_startup_message(account_id)

    # Запитуємо символи
    deferred = client.get_all_symbols()
    # Прив'язуємо обробники до результату запиту
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    """Обробник успішного завантаження символів."""
    # --- КЛЮЧОВЕ ВИПРАВЛЕННЯ ---
    # 1. Створюємо порожній об'єкт-відповідь потрібного нам типу.
    symbols_response = ProtoOASymbolsListRes()
    # 2. "Розпаковуємо" вміст "конверта" (raw_message.payload) в наш об'єкт.
    symbols_response.ParseFromString(raw_message.payload)
    # 3. Тепер ми можемо безпечно звертатися до поля .symbol
    symbols = symbols_response.symbol
    # ---------------------------
    
    logger.info(f"Successfully loaded {len(symbols)} symbols.")
    telegram_bot.send_message(f"📚 Завантажено {len(symbols)} символів.")

def on_symbols_error(failure):
    """Обробник помилки завантаження символів."""
    error_message = failure.getErrorMessage()
    logger.error(f"Failed to load symbols: {error_message}")
    telegram_bot.send_message(f"❌ Помилка завантаження символів: {error_message}")

# --- Налаштування зв'язків та запуск ---
client.on("ready", on_ctrader_ready)
reactor.callWhenRunning(client.start)

logger.info("Application setup complete. Klein will start the reactor.")