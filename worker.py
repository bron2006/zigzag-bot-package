# worker.py
import logging
import time
import signal
import sys
from twisted.internet import reactor
from twisted.internet.task import LoopingCall

# Налаштовуємо логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

# Імпортуємо необхідні модулі
import db
import ctrader
import ml_models
import scanner
from state import app_state

def _start_worker_services():
    """Запускає всі сервіси, необхідні для роботи сканера."""
    logger.info("Worker process starting services...")
    # Ініціалізуємо базу даних
    try:
        db.initialize_database()
    except Exception as e:
        logger.error(f"Worker failed to initialize database: {e}")
        # Можна або зупинити, або продовжити без БД
    
    # Запускаємо клієнт cTrader
    ctrader.start_ctrader_client()

    # Чекаємо, поки завантажаться символи, перш ніж запускати сканер
    def check_symbols_and_start_scanner():
        if app_state.SYMBOLS_LOADED:
            logger.info("Symbols loaded. Starting market scanner loop.")
            LoopingCall(scanner.scan_markets_once).start(60.0, now=True)
        else:
            logger.info("Symbols not loaded yet, checking again in 5 seconds.")
            reactor.callLater(5, check_symbols_and_start_scanner)
    
    # Починаємо перевірку через 5 секунд після запуску реактора
    reactor.callLater(5, check_symbols_and_start_scanner)

def main():
    logger.info("Starting worker process...")
    
    # Завантажуємо ML моделі при старті
    ml_models.load_models()

    # Запускаємо сервіси, коли реактор готовий
    reactor.callWhenRunning(_start_worker_services)

    # Обробка сигналів для коректної зупинки
    def _sigterm(signum, frame):
        logger.info("SIGTERM received — stopping worker reactor")
        if reactor.running:
            reactor.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    
    # Запускаємо головний цикл
    logger.info("Starting Twisted reactor for worker.")
    reactor.run()

if __name__ == "__main__":
    main()