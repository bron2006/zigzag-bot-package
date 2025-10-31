# state.py
import logging
from telegram.error import BadRequest
from asyncio import Queue

# --- ІНТЕГРАЦІЯ ЕКСПЕРТА (для очищення) ---
# Ми залишаємо це, оскільки інші файли це використовують
from utils_message_cleanup import bot_track_message
# --- КІНЕЦЬ ---

logger = logging.getLogger(__name__)

class AppState:
    def __init__(self):
        self.client = None
        self.updater = None # Потрібно для bot.py та очищення
        
        # --- ПОВЕРНЕННЯ КРИТИЧНИХ АТРИБУТІВ ---
        # (Я помилково видалив їх у попередній версії, що зламало cTrader)
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        self.sse_queue = Queue(maxsize=100) # Потрібно для app.py
        # --- КІНЕЦЬ ПОВЕРНЕННЯ ---

        self.SYMBOLS_LOADED = False
        self.all_symbol_names = set()
        self.symbol_cache = {}
        self.signal_cache = {}
        self.SCANNER_STATE = {
            "forex": False,
            "crypto": False,
            "commodities": False,
            "watchlist": False
        }

    def get_scanner_state(self, category_key: str) -> bool:
        return self.SCANNER_STATE.get(category_key, False)

    def set_scanner_state(self, category_key: str, state: bool):
        if category_key in self.SCANNER_STATE:
            self.SCANNER_STATE[category_key] = state
            logger.info(f"Scanner state for '{category_key}' set to {state}")
        else:
            logger.warning(f"Attempted to set unknown scanner state '{category_key}'")

    def cache_signal(self, symbol, timeframe, result):
        key = f"{symbol}_{timeframe}"
        self.signal_cache[key] = result
        logger.debug(f"Signal cached for {key}")

    def get_cached_signal(self, symbol, timeframe):
        key = f"{symbol}_{timeframe}"
        return self.signal_cache.get(key)
    
    def send_telegram_alert(self, chat_id: int, message: str, parse_mode='Markdown'):
        """
        Надсилає повідомлення та відстежує його ID у bot_data.
        (Інтеграція експерта)
        """
        if not self.updater:
            logger.error("Updater is not initialized in AppState. Cannot send alert.")
            return

        try:
            sent_msg = self.updater.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            
            # --- ІНТЕГРАЦІЯ ЕКСПЕРТА ---
            if sent_msg and hasattr(self, 'updater') and self.updater.bot:
                bot_track_message(self.updater.bot.bot_data, chat_id, sent_msg.message_id)
            # --- КІНЕЦЬ ---

        except BadRequest as e:
            logger.error(f"Telegram BadRequest sending alert to {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert to {chat_id}", exc_info=True)

# Створюємо єдиний екземпляр стану
app_state = AppState()