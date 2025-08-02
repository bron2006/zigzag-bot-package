# api_clients.py
import ccxt
from config import logger

_binance_client = None

def get_binance_client():
    """
    Створює та повертає єдиний екземпляр клієнта Binance (патерн Singleton).
    Це запобігає збоям при старті додатку.
    """
    global _binance_client
    if _binance_client is None:
        try:
            logger.info("Initializing Binance client for the first time...")
            _binance_client = ccxt.binance({
                'enableRateLimit': True,
                'timeout': 15000,
            })
            logger.info("Binance client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}", exc_info=True)
            return None
    return _binance_client