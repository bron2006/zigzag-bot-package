import os
import logging
from klein import Klein
from twisted.internet import reactor
from twisted.internet.endpoints import clientFromString
from twisted.web.server import Site
from ctrader_open_api.factory import Factory
from spotware_connect import SpotwareConnect
# Імпортуємо змінні з уніфікованими іменами з config.py
from config import host, port, CT_CLIENT_ID, CT_CLIENT_SECRET, DEMO_ACCOUNT_ID, CTRADER_ACCESS_TOKEN

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ініціалізація веб-додатку Klein
app = Klein()

@app.route("/")
def index(request):
    """Головна сторінка, яка підтверджує, що сервіс працює."""
    logger.info("Web root requested.")
    return b"Hello, cTrader bot is running!"

def start_ctrader_client():
    """Функція для запуску cTrader клієнта."""
    logger.info("Ініціалізація cTrader клієнта...")
    try:
        client = clientFromString(reactor, f"ssl:{host}:{port}")
        factory = Factory()

        # Використовуємо змінні, імпортовані з config.py
        spotware_connect = SpotwareConnect(
            reactor,
            client,
            factory,
            CT_CLIENT_ID,
            CT_CLIENT_SECRET,
            DEMO_ACCOUNT_ID,
            CTRADER_ACCESS_TOKEN,
        )

        spotware_connect.start()
        logger.info("Процес підключення до cTrader запущено.")

    except Exception as e:
        logger.critical(f"Критична помилка під час ініціалізації cTrader: {e}", exc_info=True)
        if reactor.running:
            reactor.stop()

def main():
    """Головна функція для налаштування та запуску сервісів."""
    try:
        web_port = int(os.environ.get("PORT", 8080))
        site = Site(app.resource())
        reactor.listenTCP(web_port, site, interface='0.0.0.0')
        logger.info(f"Веб-сервер запущено на порту {web_port}")

        reactor.callWhenRunning(start_ctrader_client)

        logger.info("Запуск головного циклу reactor...")
        reactor.run()

    except Exception as e:
        logger.critical(f"Помилка під час запуску main: {e}", exc_info=True)
        if reactor.running:
            reactor.stop()

if __name__ == "__main__":
    main()