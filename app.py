import os
import sys
import time
import signal
import logging
from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from flask import Flask, jsonify
from state import app_state
import scanner
import bot
import ctrader
import api
import ml_models
import config
from errors import ConfigError, ZigZagError, get_error_stats
from notifier import notify_bot_failed

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("app")

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

@app.route("/health")
def health():
    prices = app_state.live_prices
    now = time.time()
    stale = [p for p, d in prices.items() if now - d.get("ts", 0) > 300]
    err_stats = get_error_stats()
    status = "ok" if not stale else "degraded"

    # Повертаємо дані українською мовою
    return jsonify({
        "статус": status,
        "символи_завантажені": app_state.SYMBOLS_LOADED,
        "активні_ціни": len(prices),
        "застарілі_ціни": len(stale),
        "телеграм_активний": app_state.updater is not None,
        "лічильники_помилок": err_stats,
    })

def _start_background_services():
    try:
        bot.start_telegram_bot()
    except ConfigError as e:
        logger.critical(f"Конфіг помилка: {e}")
        notify_bot_failed(str(e))
    except Exception as e:
        logger.exception("Помилка Telegram")
        notify_bot_failed(str(e))

    try:
        ctrader.start_ctrader_client()
    except ConfigError as e:
        logger.critical(f"Конфіг помилка cTrader: {e}")
    except Exception as e:
        logger.exception("Помилка cTrader")

    LoopingCall(scanner.scan_markets_once).start(60.0, now=False)

    def _sse_ping():
        try:
            if not app_state.sse_queue.full():
                app_state.sse_queue.put_nowait({"_ping": int(time.time())})
        except: pass
    LoopingCall(_sse_ping).start(20.0, now=False)

def _sigterm(signum, frame):
    logger.info("Зупинка реактора...")
    try:
        if app_state.updater: app_state.updater.stop()
    finally:
        if reactor.running: reactor.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT,  _sigterm)

def main():
    api.register_routes(app)
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    port = int(os.environ.get("PORT", "8080"))
    reactor.listenTCP(port, site, interface="0.0.0.0")
    
    if config.APP_MODE == "full":
        ml_models.load_models()
    
    reactor.callWhenRunning(_start_background_services)
    reactor.run()

if __name__ == "__main__":
    main()
