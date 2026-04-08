# state.py
import logging
import queue
import threading
from typing import Any, Dict, List, Optional, Tuple

from telegram.error import BadRequest
from twisted.python.threadpool import ThreadPool

from config import IDEAL_ENTRY_THRESHOLD, get_ctrader_access_token

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self):
        self._state_lock = threading.RLock()
        self._listeners_lock = threading.RLock()

        self.client = None
        self.updater = None

        self.wsgi_pool: Optional[ThreadPool] = None
        self.blocking_pool: Optional[ThreadPool] = None

        self.background_tasks: List[Any] = []

        self.all_symbol_names: List[str] = []
        self.symbol_cache: Dict[str, Any] = {}
        self.symbol_id_map: Dict[int, str] = {}
        self.SYMBOLS_LOADED: bool = False

        self.live_prices: Dict[str, Dict[str, Any]] = {}
        self.scanner_cooldown_cache: Dict[str, float] = {}
        self.latest_analysis_cache: Dict[str, Dict[str, Any]] = {}
        self.SIGNAL_CACHE: Dict[str, Dict[str, Any]] = {}

        self.SCANNER_STATE: Dict[str, bool] = {
            "forex": False,
            "crypto": False,
            "commodities": False,
            "watchlist": False,
        }

        self.scan_in_progress: bool = False
        self.scan_generation: int = 0

        self.sse_queue: queue.Queue = queue.Queue(maxsize=2000)
        self._sse_listeners: Dict[int, queue.Queue] = {}
        self._next_listener_id: int = 1

        self.IDEAL_ENTRY_THRESHOLD = IDEAL_ENTRY_THRESHOLD
        self.access_token = get_ctrader_access_token()

    # ------------------------------------------------------------------
    # Thread pools / background tasks
    # ------------------------------------------------------------------

    def set_thread_pools(
        self,
        *,
        wsgi_pool: Optional[ThreadPool] = None,
        blocking_pool: Optional[ThreadPool] = None,
    ) -> None:
        with self._state_lock:
            self.wsgi_pool = wsgi_pool
            self.blocking_pool = blocking_pool

    def register_background_task(self, task: Any) -> None:
        with self._state_lock:
            self.background_tasks.append(task)

    def stop_background_tasks(self) -> None:
        with self._state_lock:
            tasks = list(self.background_tasks)
            self.background_tasks.clear()

        for task in tasks:
            try:
                if getattr(task, "running", False):
                    task.stop()
            except Exception:
                logger.exception("Не вдалося зупинити background task")

    # ------------------------------------------------------------------
    # Scanner state
    # ------------------------------------------------------------------

    def set_scanner_state(self, category: str, enabled: bool) -> None:
        with self._state_lock:
            if category in self.SCANNER_STATE:
                self.SCANNER_STATE[category] = enabled
                logger.info(f"Сканер '{category}' => {'ON' if enabled else 'OFF'}")

    def get_scanner_state(self, category: str) -> bool:
        with self._state_lock:
            return self.SCANNER_STATE.get(category, False)

    def get_scanner_state_snapshot(self) -> Dict[str, bool]:
        with self._state_lock:
            return dict(self.SCANNER_STATE)

    # ------------------------------------------------------------------
    # Symbol / price helpers
    # ------------------------------------------------------------------

    def mark_symbols_loaded(self, loaded: bool) -> None:
        with self._state_lock:
            self.SYMBOLS_LOADED = loaded

    def clear_symbol_state(self) -> None:
        with self._state_lock:
            self.symbol_cache.clear()
            self.symbol_id_map.clear()
            self.all_symbol_names = []
            self.SYMBOLS_LOADED = False

    def update_live_price(self, symbol: str, payload: Dict[str, Any]) -> None:
        with self._state_lock:
            self.live_prices[symbol] = payload

    def get_live_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._state_lock:
            return self.live_prices.get(symbol)

    def get_live_prices_snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._state_lock:
            return dict(self.live_prices)

    def get_symbol_details(self, pair: str):
        if not pair:
            return None

        norm = pair.replace("/", "").upper()
        with_slash = None
        if len(norm) >= 6:
            with_slash = f"{norm[:3]}/{norm[3:]}"

        candidates = [
            pair,
            pair.upper(),
            norm,
            with_slash,
            pair.replace("/", ""),
            pair.replace("/", "").upper(),
        ]

        with self._state_lock:
            for candidate in candidates:
                if candidate and candidate in self.symbol_cache:
                    return self.symbol_cache[candidate]
        return None

    # ------------------------------------------------------------------
    # Signal cache
    # ------------------------------------------------------------------

    def cache_signal(self, pair: str, timeframe: str, signal_data: dict) -> None:
        key = f"{pair}_{timeframe}"
        with self._state_lock:
            self.SIGNAL_CACHE[key] = signal_data
        logger.debug(f"Кеш оновлено: {key}")

    def get_cached_signal(self, pair: str, timeframe: str):
        key = f"{pair}_{timeframe}"
        with self._state_lock:
            return self.SIGNAL_CACHE.get(key)

    # ------------------------------------------------------------------
    # SSE
    # ------------------------------------------------------------------

    def publish_sse(self, payload: dict) -> bool:
        if payload is None:
            return False

        try:
            self.sse_queue.put_nowait(payload)
            return True
        except queue.Full:
            try:
                _ = self.sse_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self.sse_queue.put_nowait(payload)
                logger.warning("SSE queue була переповнена — найстаріший елемент видалено")
                return True
            except queue.Full:
                logger.warning("SSE queue переповнена — подію скинуто")
                return False

    def pop_pending_sse_events(self, limit: int = 500) -> List[dict]:
        events: List[dict] = []
        for _ in range(limit):
            try:
                events.append(self.sse_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def register_sse_listener(self, maxsize: int = 200) -> Tuple[int, queue.Queue]:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._listeners_lock:
            listener_id = self._next_listener_id
            self._next_listener_id += 1
            self._sse_listeners[listener_id] = q
            logger.info(f"SSE listener #{listener_id} підключено. Всього: {len(self._sse_listeners)}")
            return listener_id, q

    def unregister_sse_listener(self, listener_id: int) -> None:
        with self._listeners_lock:
            if listener_id in self._sse_listeners:
                self._sse_listeners.pop(listener_id, None)
                logger.info(f"SSE listener #{listener_id} відключено. Всього: {len(self._sse_listeners)}")

    def sse_listener_count(self) -> int:
        with self._listeners_lock:
            return len(self._sse_listeners)

    def broadcast_sse_message(self, message: str) -> None:
        with self._listeners_lock:
            listeners = list(self._sse_listeners.items())

        if not listeners:
            return

        stale_ids: List[int] = []

        for listener_id, listener_queue in listeners:
            try:
                listener_queue.put_nowait(message)
            except queue.Full:
                try:
                    _ = listener_queue.get_nowait()
                    listener_queue.put_nowait(message)
                except Exception:
                    stale_ids.append(listener_id)
            except Exception:
                stale_ids.append(listener_id)

        for listener_id in stale_ids:
            self.unregister_sse_listener(listener_id)

    # ------------------------------------------------------------------
    # Telegram helper
    # ------------------------------------------------------------------

    def send_telegram_alert(self, chat_id: int, message: str, parse_mode: str = "Markdown") -> None:
        if not self.updater:
            logger.error("Updater is not initialized in AppState. Cannot send alert.")
            return

        try:
            sent_msg = self.updater.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            try:
                self.updater.dispatcher.bot_data.setdefault("sent_messages_by_chat", {}) \
                    .setdefault(str(chat_id), []) \
                    .append(sent_msg.message_id)
            except Exception:
                logger.exception("Failed to record sent message in dispatcher.bot_data")
        except BadRequest as e:
            logger.error(f"Telegram BadRequest sending alert to {chat_id}: {e}")
        except Exception:
            logger.exception("Failed to send Telegram alert")


app_state = AppState()