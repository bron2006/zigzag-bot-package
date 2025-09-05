# state.py
import logging

logger = logging.getLogger(__name__)

# --- СТАН КЛІЄНТА ТА СИМВОЛІВ ---
client = None
all_symbol_names = []
symbol_cache = {}
SYMBOLS_LOADED = False

# --- СТАН СКАНЕРІВ (у пам'яті, а не в Redis) ---
SCANNER_STATE = {
    "forex": False,
    "crypto": False,
    "commodities": False
}

# --- КЕШ СИГНАЛІВ (у пам'яті) ---
# Структура: { "EURUSD_1m": { "verdict": "Buy", "price": 1.23456, ... } }
SIGNAL_CACHE = {}

def set_scanner_state(category: str, enabled: bool):
    """Встановити стан сканера."""
    if category in SCANNER_STATE:
        SCANNER_STATE[category] = enabled
        logger.info(f"Сканер '{category}' => {'ON' if enabled else 'OFF'}")

def get_scanner_state(category: str) -> bool:
    """Отримати стан сканера."""
    return SCANNER_STATE.get(category, False)

def cache_signal(pair: str, timeframe: str, signal_data: dict):
    """Зберегти сигнал у кеш."""
    key = f"{pair}_{timeframe}"
    SIGNAL_CACHE[key] = signal_data
    logger.debug(f"Кеш оновлено: {key}")

def get_cached_signal(pair: str, timeframe: str):
    """Отримати останній сигнал з кешу."""
    key = f"{pair}_{timeframe}"
    return SIGNAL_CACHE.get(key)
