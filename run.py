import os
import logging
from twisted.internet import reactor
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource

from main import app, start_ctrader_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    # Обгортаємо Klein app у WSGI ресурс Twisted
    resource = WSGIResource(reactor, reactor.getThreadPool(), app.resource())
    site = Site(resource)

    # Слухаємо порт
    reactor.listenTCP(port, site)
    logger.info(f"Klein веб-сервер запущено на порту {port}")

    # Запускаємо cTrader клієнт після старту реактора
    reactor.callWhenRunning(start_ctrader_client)

    # Стартуємо головний цикл
    reactor.run()
