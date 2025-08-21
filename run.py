import os
import logging
from klein import Klein
from twisted.internet import reactor
from spotware_connect import SpotwareConnect

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Klein()
ctrader_client = SpotwareConnect()

@app.route("/")
def index(request):
    logger.info("Web root requested.")
    return b"Hello, cTrader bot is running!"

def on_ctrader_ready():
    logger.info("cTrader Client готовий. Запитую символи...")
    d = ctrader_client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(response):
    symbols = response.symbol
    logger.info(f"Завантажено {len(symbols)} символів.")
    # Тут буде подальша логіка...

def on_symbols_error(failure):
    logger.error(f"Не вдалося завантажити символи: {failure.getErrorMessage()}")

def start_services():
    try:
        web_port = int(os.environ.get("PORT", 8080))
        reactor.listenTCP(web_port, app.resource(), interface='0.0.0.0')
        logger.info(f"Веб-сервер запущено на порту {web_port}")
        
        # Підписуємось на подію 'ready' від клієнта
        ctrader_client.on("ready", on_ctrader_ready)
        # Запускаємо підключення
        ctrader_client.start()

        logger.info("Запуск головного циклу reactor...")
        reactor.run()
    except Exception as e:
        logger.critical(f"Помилка під час запуску сервісів: {e}", exc_info=True)
        if reactor.running:
            reactor.stop()

if __name__ == "__main__":
    start_services()