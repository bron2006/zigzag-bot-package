import logging
from twisted.internet import reactor, defer, task
from spotware_connect import SpotwareClient
from telegram_ui import app

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

client = None
RECONNECT_DELAY = 5  # секунд


def on_client_ready():
    """Коли клієнт готовий до роботи."""
    logger.info("✅ cTrader клієнт успішно підключився та готовий.")


def on_client_error(failure):
    """Колбек для критичних помилок клієнта."""
    error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
    logger.critical(f"❌ Критична помилка cTrader клієнта: {error_message}. Перепідключення через {RECONNECT_DELAY}с...")

    # Плануємо перепідключення
    reactor.callLater(RECONNECT_DELAY, reconnect_client)


@defer.inlineCallbacks
def start_client():
    """Старт підключення клієнта."""
    global client
    client = SpotwareClient()
    client.on_ready.addCallback(lambda _: on_client_ready())
    client.on_error.addErrback(on_client_error)

    yield client.connect()


def reconnect_client():
    """Перепідключення клієнта."""
    d = start_client()
    d.addErrback(on_client_error)


@defer.inlineCallbacks
def main():
    logger.info("🚀 Запуск бота ZigZag...")

    # 1. Запускаємо cTrader клієнт
    yield start_client()

    # 2. Klein вебсервер вже стартує у run.py через reactor.listenTCP
    logger.info("🌍 Вебсервер Klein очікує підключень...")


if __name__ == "__main__":
    d = main()
    d.addErrback(on_client_error)
    reactor.run()
