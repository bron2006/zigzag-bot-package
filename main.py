import logging
from klein import Klein
from twisted.internet import reactor
from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Створюємо екземпляр веб-додатку
app = Klein()

# Створюємо екземпляр клієнта cTrader
# Передаємо Client ID та Secret, як це було в оригінальному коді
client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())

@app.route("/")
def home(request):
    """Головна сторінка для перевірки стану."""
    logger.info("Web root requested.")
    if client.is_authorized:
        return "cTrader client is connected and authorized."
    else:
        return "cTrader client is running but not authorized yet."

def on_ctrader_ready():
    """Обробник події, коли клієнт готовий до роботи."""
    logger.info("cTrader Client is ready. Requesting symbols...")
    # Запитуємо символи і додаємо обробники результату
    deferred = client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(symbols_response):
    """Обробник успішного завантаження символів."""
    symbols = symbols_response.symbol
    logger.info(f"Successfully loaded {len(symbols)} symbols.")
    # Тут можна додати подальшу логіку

def on_symbols_error(failure):
    """Обробник помилки завантаження символів."""
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

# Підписуємось на подію 'ready' від клієнта
client.on("ready", on_ctrader_ready)

# Запускаємо підключення до cTrader при старті реактора
reactor.callWhenRunning(client.start)

logger.info("Application setup complete. Klein will start the reactor.")