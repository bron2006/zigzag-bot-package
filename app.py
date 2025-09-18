# app.py
import os
import sys
import time
import signal
import logging

from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from flask import Flask

from state import app_state
import scanner
import bot
import ctrader
import api
import ml_models

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("app")

# Flask app
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

def _start_background_services():
    """Запускає всі фонові сервіси, включаючи сканер."""
    logger.info("Starting all background services...")
    bot.start_telegram_bot()
    ctrader.start_ctrader_client()
    
    # Чекаємо, поки завантажаться символи, перш ніж запускати сканер
    def check_symbols_and_start_scanner():
        if app_state.SYMBOLS_LOADED:
            logger.info("Symbols loaded. Starting market scanner loop.")
            LoopingCall(scanner.scan_markets_once).start(60.0, now=True)
        else:
            logger.info("Symbols not loaded yet, checking again in 10 seconds.")
            reactor.callLater(10, check_symbols_and_start_scanner)
            
    reactor.callLater(10, check_symbols_and_start_scanner)
    
    # Ping для SSE з'єднання
    LoopingCall(lambda: (app_state.sse_queue.put_nowait({"_ping": int(time.time())}) if not app_state.sse_queue.full() else None)).start(20.0, now=False)

def main():
    api.register_routes(app)
    
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server listening on {port}")

    # Завантажуємо ML моделі
    ml_models.load_models()

    reactor.callWhenRunning(_start_background_services)

    def _sigterm(signum, frame):
        logger.info("SIGTERM received — stopping reactor")
        try:
            if app_state.updater:
                app_state.updater.stop()
        finally:
            if reactor.running:
                reactor.stop()
            sys.exit(0)
            
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    logger.info("Starting Twisted reactor for web app and scanner.")
    reactor.run()

if __name__ == "__main__":
    main()