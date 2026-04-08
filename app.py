# app.py
import logging
import os
import signal
import sys
import time

from flask import Flask
from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.python.threadpool import ThreadPool
from twisted.web.server import Site

import api
import bot
import config
import ctrader
import ml_models
import scanner
from errors import ConfigError
from notifier import notify_bot_failed
from state import app_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} не є числом, використовую {default}")
        return default


def _create_thread_pool(name: str, minthreads: int, maxthreads: int) -> ThreadPool:
    pool = ThreadPool(
        minthreads=minthreads,
        maxthreads=maxthreads,
        name=name,
    )
    pool.start()
    logger.info(f"Запущено ThreadPool '{name}' ({minthreads}..{maxthreads})")
    return pool


def _start_loop(interval: float, func, *, now: bool = False, name: str = "loop") -> None:
    loop = LoopingCall(func)
    d = loop.start(interval, now=now)
    app_state.register_background_task(loop)

    def _loop_failed(failure):
        logger.error(f"Background loop '{name}' завершився з помилкою: {failure.getErrorMessage()}")

    d.addErrback(_loop_failed)
    logger.info(f"Запущено LoopingCall '{name}' кожні {interval}s")


def _publish_sse_ping() -> None:
    app_state.publish_sse({"_ping": int(time.time())})


def _start_background_services() -> None:
    try:
        bot.start_telegram_bot()
    except ConfigError as e:
        logger.critical(f"Конфіг помилка при запуску Telegram bot: {e}")
        notify_bot_failed(str(e))
    except Exception as e:
        logger.exception("Не вдалося запустити Telegram bot")
        notify_bot_failed(str(e))

    try:
        ctrader.start_ctrader_client()
    except ConfigError as e:
        logger.critical(f"Конфіг помилка при запуску cTrader: {e}")
        notify_bot_failed(str(e))
    except Exception as e:
        logger.exception("Не вдалося запустити cTrader client")

    _start_loop(60.0, scanner.scan_markets_once, now=False, name="scanner")
    _start_loop(0.2, api.drain_sse_events, now=False, name="sse_drain")
    _start_loop(20.0, _publish_sse_ping, now=False, name="sse_ping")


def _shutdown() -> None:
    logger.info("Починаємо graceful shutdown...")

    try:
        app_state.stop_background_tasks()
    except Exception:
        logger.exception("Помилка при зупинці background tasks")

    try:
        if app_state.updater:
            logger.info("Зупиняємо Telegram updater...")
            app_state.updater.stop()
    except Exception:
        logger.exception("Не вдалося коректно зупинити Telegram updater")
    finally:
        app_state.updater = None

    for pool_name, pool in (
        ("wsgi_pool", app_state.wsgi_pool),
        ("blocking_pool", app_state.blocking_pool),
    ):
        if pool:
            try:
                logger.info(f"Зупиняємо {pool_name}...")
                pool.stop()
            except Exception:
                logger.exception(f"Не вдалося зупинити {pool_name}")


def _sigterm(signum, frame):
    logger.info(f"Отримано сигнал {signum} — зупиняємо reactor")
    if reactor.running:
        reactor.callFromThread(reactor.stop)


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT, _sigterm)


def main():
    api.register_routes(app)

    reactor_threads = _env_int("TWISTED_REACTOR_THREADS", 12)
    reactor.suggestThreadPoolSize(reactor_threads)
    logger.info(f"Twisted reactor thread pool size suggested: {reactor_threads}")

    wsgi_pool = _create_thread_pool(
        "zigzag-wsgi-pool",
        minthreads=_env_int("WSGI_POOL_MIN", 4),
        maxthreads=_env_int("WSGI_POOL_MAX", 20),
    )
    blocking_pool = _create_thread_pool(
        "zigzag-blocking-pool",
        minthreads=_env_int("BLOCKING_POOL_MIN", 2),
        maxthreads=_env_int("BLOCKING_POOL_MAX", 12),
    )
    app_state.set_thread_pools(wsgi_pool=wsgi_pool, blocking_pool=blocking_pool)

    root_resource = api.build_root_resource(app, reactor, wsgi_pool)
    site = Site(root_resource)

    port = _env_int("PORT", 8080)
    reactor.listenTCP(port, site, interface="0.0.0.0")
    logger.info(f"Twisted HTTP server слухає на порті {port}")

    if config.APP_MODE == "full":
        logger.info("APP_MODE=full. Завантажуємо ML моделі...")
        ml_models.load_models()
    else:
        logger.info("APP_MODE=light. ML моделі не завантажуємо.")

    reactor.addSystemEventTrigger("before", "shutdown", _shutdown)
    reactor.callWhenRunning(_start_background_services)

    logger.info("Запускаємо Twisted reactor.")
    reactor.run()
    logger.info("Twisted reactor зупинено.")
    sys.exit(0)


if __name__ == "__main__":
    main()