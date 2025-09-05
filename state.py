# state.py
import logging
import queue
from typing import Dict, Any

logger = logging.getLogger(__name__)

# --- ГЛОБАЛЬНІ ОБ'ЄКТИ ---
client = None
updater = None # Об'єкт Telegram Updater

# --- СТАН ЗАВАНТАЖЕННЯ СИМВОЛІВ ---
all_symbol_names: list = []
symbol_cache: Dict[str, Any] = {}
SYMBOLS_LOADED: bool = False

# --- "ГАРЯЧИЙ" КЕШ В ПАМ'ЯТІ (замість Redis для швидкості) ---
# Для цін реального часу
live_prices: Dict[str, Dict[str, Any]] = {}
# Для відстеження сповіщень сканера, щоб не спамити
scanner_cooldown_cache: Dict[str, float] = {}
# Для кешування останнього повного аналізу
latest_analysis_cache: Dict[str, Dict[str, Any]] = {}
# Для кешування сигналів (використовується в telegram_ui)
SIGNAL_CACHE: Dict[str, Dict[str, Any]] = {}

# --- СТАН СКАНЕРІВ (керується з UI) ---
SCANNER_STATE: Dict[str, bool] = {
    "forex": True,
    "crypto": False,
    "commodities": False
}

# --- ЧЕРГА ДЛЯ ВЕБ-ІНТЕРФЕЙСУ (Server-Sent Events) ---
sse_queue: queue.Queue = queue.Queue(maxsize=100)


# --- ФУНКЦІЇ-ХЕЛПЕРИ (зберігаємо існуючий інтерфейс) ---

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