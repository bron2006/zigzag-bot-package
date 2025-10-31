# state.py
import logging
import queue
from typing import Dict, Any
# --- ПОЧАТОК ЗМІН ---
from config import IDEAL_ENTRY_THRESHOLD, get_ctrader_access_token
# --- КІНЕЦЬ ЗМІН ---

logger = logging.getLogger(__name__)

class AppState:
    def __init__(self):
        # ... (попередні атрибути без змін)
        self.client = None
        self.updater = None
        self.all_symbol_names: list = []
        self.symbol_cache: Dict[str, Any] = {}
        self.symbol_id_map: Dict[int, str] = {}
        self.SYMBOLS_LOADED: bool = False
        self.live_prices: Dict[str, Dict[str, Any]] = {}
        self.scanner_cooldown_cache: Dict[str, float] = {}
        self.latest_analysis_cache: Dict[str, Dict[str, Any]] = {}
        self.SIGNAL_CACHE: Dict[str, Dict[str, Any]] = {}
        self.SCANNER_STATE: Dict[str, bool] = {
            "forex": False, "crypto": False, "commodities": False, "watchlist": False
        }
        self.sse_queue: queue.Queue = queue.Queue()
        self.IDEAL_ENTRY_THRESHOLD = IDEAL_ENTRY_THRESHOLD
        
        # --- ПОЧАТОК ЗМІН: Додаємо поле для токена ---
        self.access_token = get_ctrader_access_token()
        # --- КІНЕЦЬ ЗМІН ---

    def set_scanner_state(self, category: str, enabled: bool):
        if category in self.SCANNER_STATE:
            self.SCANNER_STATE[category] = enabled
            logger.info(f"Сканер '{category}' => {'ON' if enabled else 'OFF'}")

    def get_scanner_state(self, category: str) -> bool:
        return self.SCANNER_STATE.get(category, False)

    def cache_signal(self, pair: str, timeframe: str, signal_data: dict):
        key = f"{pair}_{timeframe}"
        self.SIGNAL_CACHE[key] = signal_data
        logger.debug(f"Кеш оновлено: {key}")

    def get_cached_signal(self, pair: str, timeframe: str):
        key = f"{pair}_{timeframe}"
        return self.SIGNAL_CACHE.get(key)

app_state = AppState()