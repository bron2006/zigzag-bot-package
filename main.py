import logging
from twisted.internet import reactor, defer
from spotware_connect import SpotwareClient
from telegram_ui import app

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

client = None


def on_client_ready():
    """Коли клієнт готовий до роботи."""
    logger.info("✅ cTrader клієнт успішно підключився та готовий.")


def on_client_error(failure):
    """Колбек для критичних помилок клієнта."""
    error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
    logger.critical(f"❌ Критична помилка cTrader клієнта: {error_message}.")
    # РАНІШЕ: if reactor.running: reactor.stop()
    # Тепер НЕ зупиняємо весь процес, щоб не падала машина на Fly.io.
    # Можна додати retry-логіку, якщо треба перепідключення.


@defer.inlineCallbacks
def main():
    global client
    logger.info("🚀 Запуск бота ZigZag...")

    # 1. Ініціалізація клієнта Spotware
    client = SpotwareClient()
    client.on_ready.addCallback(lambda _: on_client_ready())
    client.on_error.addErrback(on_client_error)

    yield client.connect()

    # 2. Klein вебсервер вже стартує у run.py через reactor.listenTCP
    logger.info("🌍 Вебсервер Klein очікує підключень...")


if __name__ == "__main__":
    d = main()
    d.addErrback(on_client_error)
    reactor.run()
