# redis_client.py
import os
import redis
import logging

logger = logging.getLogger(__name__)

# REDIS_URL буде автоматично взято з "секретів" на fly.io
REDIS_URL = os.getenv("REDIS_URL")

_redis = None

def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        if not REDIS_URL:
            raise RuntimeError("CRITICAL: REDIS_URL is not set in the environment!")
        try:
            logger.info("Connecting to Redis...")
            _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            _redis.ping() # Перевіряємо з'єднання
            logger.info("✅ Redis connection successful.")
        except redis.exceptions.ConnectionError as e:
            logger.critical(f"❌ Could not connect to Redis: {e}")
            raise
    return _redis