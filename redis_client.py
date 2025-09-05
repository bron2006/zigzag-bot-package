# redis_client.py
import os
import json
import logging
import redis
from typing import Optional, Dict

logger = logging.getLogger("redis_client")
logger.setLevel(logging.INFO)

# --- ПОЧАТОК ЗМІН: Створюємо глобальну змінну для зберігання підключення ---
_redis_client = None
# --- КІНЕЦЬ ЗМІН ---

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)
REDIS_DB = int(os.environ.get("REDIS_DB", 0))


def get_redis() -> redis.Redis:
    """
    Повертає єдиний екземпляр клієнта Redis (singleton).
    Створює підключення лише один раз.
    """
    # --- ПОЧАТОК ЗМІН: Логіка для створення єдиного підключення ---
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    try:
        if REDIS_URL.startswith("rediss://"):
            logger.info(f"Creating new Redis TLS connection to {REDIS_URL}")
            _redis_client = redis.Redis.from_url(
                REDIS_URL,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True,
                ssl_cert_reqs=None
            )
        else:
            logger.info(f"Creating new Redis connection to {REDIS_URL}")
            _redis_client = redis.Redis.from_url(
                REDIS_URL,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True
            )
        # Перевірка з'єднання
        _redis_client.ping()
        logger.info("Redis connection successful.")
        return _redis_client
    except Exception as e:
        logger.critical(f"CRITICAL: Could not connect to Redis. Error: {e}")
        # Якщо не вдалося підключитися, повертаємо None, щоб уникнути падіння
        return None
    # --- КІНЕЦЬ ЗМІН ---


def set_tick(symbol: str, bid: float, ask: float, mid: Optional[float] = None) -> bool:
    """
    Ця функція більше не використовується в основному циклі,
    але залишена для можливої сумісності.
    """
    try:
        r = get_redis()
        if not r: return False # Додано перевірку, чи є з'єднання
        ts_ms = int(round(time.time() * 1000))
        if mid is None and bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
        data = {"ts_ms": ts_ms, "bid": bid, "ask": ask, "mid": mid}
        r.set(f"tick:{symbol}", json.dumps(data))
        return True
    except Exception as e:
        logger.exception(f"set_tick error for {symbol}: {e}")
        return False


def get_tick(symbol: str, stale_sec: int = 15) -> Optional[Dict]:
    """
    Ця функція більше не використовується в основному циклі,
    але залишена для можливої сумісності.
    """
    try:
        r = get_redis()
        if not r: return None # Додано перевірку
        raw = r.get(f"tick:{symbol}")
        if not raw:
            return None
        data = json.loads(raw)
        ts_ms = data.get("ts_ms")
        if ts_ms and (time.time() * 1000 - ts_ms) > stale_sec * 1000:
            return None
        return data
    except Exception as e:
        logger.exception(f"get_tick error for {symbol}: {e}")
        return None