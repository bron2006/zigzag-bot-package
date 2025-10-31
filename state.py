# state.py
import logging
import queue
from typing import Dict, Any
from config import IDEAL_ENTRY_THRESHOLD, get_ctrader_access_token
from telegram.error import BadRequest
from utils_message_cleanup import bot_track_message # <--- ІМПОРТ

logger = logging.getLogger(__name__)

class AppState:
    def __init__(self):
        # --- ВАШ ОРИГІНАЛЬНИЙ КОД (ЯКИЙ Я БІЛЬШЕ НЕ ЧІПАЮ) ---
        self.client = None
        self.updater = None # Заповнить bot.py
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
        self.access_token = get_ctrader_access_token()
        # --- КІНЕЦЬ ВАШОГО КОДУ ---

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

    # --- ДОДАНО send_telegram_alert (для сканера) ---
    def send_telegram_alert(self, chat_id: int, message: str, parse_mode='Markdown'):
        if not self.updater:
            logger.error("Updater is not initialized in AppState. Cannot send alert.")
            return
        try:
            sent_msg = self.updater.bot.send_message(
                chat_id=chat_id, text=message,
                parse_mode=parse_mode, disable_web_page_preview=True
            )
            if sent_msg and hasattr(self, 'updater') and self.updater.bot:
                bot_track_message(self.updater.bot.bot_data, chat_id, sent_msg.message_id)
        except BadRequest as e:
            logger.error(f"Telegram BadRequest sending alert to {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert to {chat_id}", exc_info=True)
    # --- КІНЕЦЬ ---

app_state = AppState()