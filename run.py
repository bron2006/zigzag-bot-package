import os
import logging
from klein import Klein
from twisted.internet import reactor, ssl
from twisted.internet.endpoints import clientFromString
from twisted.web.server import Site
from ctrader_open_api.factory import Factory
from spotware_connect import SpotwareConnect
from config import host, port, client_id, client_secret, ctid, access_token

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
        # Створення клієнтського ендпоінту Twisted
        client = clientFromString(reactor, f"ssl:{host}:{port}")

        # Створення фабрики для Open API
        factory = Factory()

        # Ініціалізація нашого кастомного клієнта
        spotware_connect = SpotwareConnect(
            reactor,
            client,
            factory,
            client_id,
            client_secret,
            ctid,
            access_token,
        )

        # Запускаємо процес підключення
        spotware_connect.start()
        logger.info("Процес підключення до cTrader запущено.")

    except Exception as e:
        logger.critical(f"Критична помилка під час ініціалізації cTrader: {e}", exc_info=True)
        # У випадку помилки, зупиняємо reactor, щоб контейнер перезапустився
        if reactor.running:
            reactor.stop()

def main():
    """Головна функція для налаштування та запуску сервісів."""
    try:
        # Налаштування веб-сервера
        web_port = int(os.environ.get("PORT", 8080))
        site = Site(app.resource())
        reactor.listenTCP(web_port, site, interface='0.0.0.0')
        logger.info(f"Веб-сервер запущено на порту {web_port}")

        # Реєструємо функцію запуску cTrader клієнта для виконання,
        # коли reactor вже запущено. Це не блокує старт веб-сервера.
        reactor.callWhenRunning(start_ctrader_client)

        # Запуск головного циклу Twisted
        logger.info("Запуск головного циклу reactor...")
        reactor.run()

    except Exception as e:
        logger.critical(f"Помилка під час запуску main: {e}", exc_info=True)
        # Переконуємось, що reactor зупиниться у випадку помилки
        if reactor.running:
            reactor.stop()

if __name__ == "__main__":
    main()