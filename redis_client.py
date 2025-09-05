# redis_client.py
import os
import json
import logging
import redis
from typing import Optional, Dict

logger = logging.getLogger("redis_client")
logger.setLevel(logging.INFO)

# -------------------- Підключення до Redis --------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")  # можна rediss:// якщо TLS
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)
REDIS_DB = int(os.environ.get("REDIS_DB", 0))

def get_redis() -> redis.Redis:
    """
    Повертає клієнт Redis.
    Використовує TLS, якщо REDIS_URL починається з rediss://
    """
    if REDIS_URL.startswith("rediss://"):
        logger.info(f"Connecting to Redis (TLS) at {REDIS_URL}")
        return redis.Redis.from_url(
            REDIS_URL,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            decode_responses=True,
            ssl_cert_reqs=None  # якщо потрібна перевірка сертифікату, змінити
        )
    else:
        logger.info(f"Connecting to Redis at {REDIS_URL}")
        return redis.Redis.from_url(
            REDIS_URL,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            decode_responses=True
        )

# -------------------- Робота з тікерами --------------------
def set_tick(symbol: str, bid: float, ask: float, mid: Optional[float] = None) -> bool:
    """
    Записує останню ціну для символу в Redis.
    Ключ: tick:<SYMBOL>
    Значення:
        {
            "ts_ms": <timestamp в мс>,
            "bid": <bid>,
            "ask": <ask>,
            "mid": <mid>
        }
    """
    try:
        r = get_redis()
        ts_ms = int(round(time.time() * 1000))
        if mid is None and bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
        data = {
            "ts_ms": ts_ms,
            "bid": bid,
            "ask": ask,
            "mid": mid
        }
        r.set(f"tick:{symbol}", json.dumps(data))
        return True
    except Exception as e:
        logger.exception(f"set_tick error for {symbol}: {e}")
        return False

def get_tick(symbol: str, stale_sec: int = 15) -> Optional[Dict]:
    """
    Читає останню ціну з Redis.
    Якщо дані застаріли (>stale_sec), повертає None.
    """
    try:
        r = get_redis()
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

# -------------------- Додаткові утиліти --------------------
def list_all_ticks() -> Dict[str, Dict]:
    """
    Повертає всі ключі tick:* та їх значення
    """
    try:
        r = get_redis()
        keys = r.keys("tick:*")
        result = {}
        for key in keys:
            raw = r.get(key)
            if raw:
                result[key] = json.loads(raw)
        return result
    except Exception as e:
        logger.exception(f"list_all_ticks error: {e}")
        return {}
