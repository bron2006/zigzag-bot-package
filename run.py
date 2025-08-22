"""
Головна точка входу для Fly.io.
Запускає Twisted reactor та Klein-сервер із main.py
"""

import logging
from twisted.internet import reactor
import main  # Імпортує Klein app та setup_and_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("🚀 Запуск Twisted reactor...")
    # reactor.run блокує виконання та тримає процес живим
    reactor.run()
