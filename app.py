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


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    prices     = app_state.live_prices
    now        = time.time()
    stale      = [p for p, d in prices.items() if now - d.get("ts", 0) > 300]
    err_stats  = get_error_stats()
    status     = "ok" if not stale else "degraded"

    return jsonify({
        "status":          status,
        "symbols_loaded":  app_state.SYMBOLS_LOADED,
        "live_prices":     len(prices),
        "stale_prices":    len(stale),
        "telegram_alive":  app_state.updater is not None,
        "error_counters":  err_stats,
    })


# ---------------------------------------------------------------------------
# Запуск фонових сервісів
# ---------------------------------------------------------------------------

def _start_background_services():
    # Telegram bot
    try:
        bot.start_telegram_bot()
    except ConfigError as e:
        logger.critical(f"Конфіг помилка при запуску Telegram bot: {e}")
        notify_bot_failed(str(e))
    except Exception as e:
        logger.exception("Не вдалося запустити Telegram bot")
        notify_bot_failed(str(e))

    # cTrader
    try:
        ctrader.start_ctrader_client()
    except ConfigError as e:
        logger.critical(f"Конфіг помилка при запуску cTrader: {e}")
        notify_bot_failed(str(e))
    except Exception as e:
        logger.exception("Не вдалося запустити cTrader client")

    # Scanner loop
    LoopingCall(scanner.scan_markets_once).start(60.0, now=False)

    # SSE ping
    def _sse_ping():
        try:
            if not app_state.sse_queue.full():
                app_state.sse_queue.put_nowait({"_ping": int(time.time())})
        except Exception:
            pass
    LoopingCall(_sse_ping).start(20.0, now=False)


# ---------------------------------------------------------------------------
# SIGTERM / SIGINT
# ---------------------------------------------------------------------------

def _sigterm(signum, frame):
    logger.info("SIGTERM/SIGINT отримано — зупиняємо reactor")
    try:
        if app_state.updater:
            app_state.updater.stop()
    finally:
        if reactor.running:
            reactor.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT,  _sigterm)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api.register_routes(app)

    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site     = Site(resource)
    port     = int(os.environ.get("PORT", "8080"))

    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted WSGI server слухає на порті {port}")

    if config.APP_MODE == "full":
        logger.info("APP_MODE=full. Завантажуємо ML моделі...")
        ml_models.load_models()
    else:
        logger.info("APP_MODE=light. ML моделі не завантажуємо.")

    reactor.callWhenRunning(_start_background_services)

    logger.info("Запускаємо Twisted reactor.")
    reactor.run()


if __name__ == "__main__":
    main()
