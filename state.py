# state.py
import logging
import queue
from typing import Dict, Any

logger = logging.getLogger(__name__)

class AppState:
    def __init__(self):
        # --- ГЛОБАЛЬНІ ОБ'ЄКТИ ---
        self.client = None
        self.updater = None  # Об'єкт Telegram Updater

        # --- СТАН ЗАВАНТАЖЕННЯ СИМВОЛІВ ---
        self.all_symbol_names: list = []
        self.symbol_cache: Dict[str, Any] = {}
        self.symbol_id_map: Dict[int, str] = {}
        self.SYMBOLS_LOADED: bool = False

        # --- "ГАРЯЧИЙ" КЕШ В ПАМ'ЯТІ ---
        self.live_prices: Dict[str, Dict[str, Any]] = {}
        self.scanner_cooldown_cache: Dict[str, float] = {}
        self.latest_analysis_cache: Dict[str, Dict[str, Any]] = {}
        self.SIGNAL_CACHE: Dict[str, Dict[str, Any]] = {}

        # --- СТАН СКАНЕРІВ ---
        self.SCANNER_STATE: Dict[str, bool] = {
            "forex": False,
            "crypto": False,
            "commodities": False,
            "watchlist": False
        }

        # --- ЧЕРГА ДЛЯ ВЕБ-ІНТЕРФЕЙСУ ---
        self.sse_queue: queue.Queue = queue.Queue()

    def set_scanner_state(self, category: str, enabled: bool):
        """Встановити стан сканера."""
        if category in self.SCANNER_STATE:
            self.SCANNER_STATE[category] = enabled
            logger.info(f"Сканер '{category}' => {'ON' if enabled else 'OFF'}")

    def get_scanner_state(self, category: str) -> bool:
        """Отримати стан сканера."""
        return self.SCANNER_STATE.get(category, False)

    def cache_signal(self, pair: str, timeframe: str, signal_data: dict):
        """Зберегти сигнал у кеш."""
        key = f"{pair}_{timeframe}"
        self.SIGNAL_CACHE[key] = signal_data
        logger.debug(f"Кеш оновлено: {key}")

    def get_cached_signal(self, pair: str, timeframe: str):
        """Отримати останній сигнал з кешу."""
        key = f"{pair}_{timeframe}"
        return self.SIGNAL_CACHE.get(key)

# Створюємо єдиний екземпляр стану для всього додатку
app_state = AppState()