# api_clients.py
import ccxt
from config import logger

_binance_client = None

def get_binance_client():
    global _binance_client
    if _binance_client is None:
        try:
            logger.info("🔄 Ініціалізація Binance клієнта вперше...")
            _binance_client = ccxt.binance({
                'enableRateLimit': True,
                'timeout': 15000,
                'options': {
                    'adjustForTimeDifference': True  # ⏱ авто-синхронізація часу
                }
            })
            logger.info("✅ Binance клієнт успішно ініціалізовано.")
        except Exception as e:
            logger.error(f"❌ Помилка ініціалізації Binance клієнта: {e}", exc_info=True)
            _binance_client = None  # Гарантуємо, що не збережеться частково створений клієнт
    return _binance_client