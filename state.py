# state.py
import logging
import queue
import threading
import time
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
        self.user_status_cache: Dict[int, Dict[str, Any]] = {}
        self.last_manual_analysis_request_ts: float = 0.0

        self.SCANNER_STATE: Dict[str, bool] = {
            "forex": False,
            "crypto": False,
            "commodities": False,
            "watchlist": False,
        }

        self.scan_in_progress: bool = False
        self.scan_generation: int = 0

        self.signal_sse_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.price_sse_queue: queue.Queue = queue.Queue(maxsize=2000)

        self._sse_listeners: Dict[str, Dict[int, queue.Queue]] = {
            "signal": {},
            "price": {},
        }
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

    def clear_live_prices(self) -> None:
        with self._state_lock:
            self.live_prices.clear()

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

    def cache_signal(self, pair: str, timeframe: str, signal_data: dict, lang: str | None = None) -> None:
        key = f"{pair}_{timeframe}_{(lang or '').lower()}"
        payload = dict(signal_data or {})
        payload["_cached_at"] = time.time()
        with self._state_lock:
            self.SIGNAL_CACHE[key] = payload
        logger.debug(f"Кеш оновлено: {key}")

    def get_cached_signal(
        self,
        pair: str,
        timeframe: str,
        lang: str | None = None,
        max_age_seconds: int | None = None,
    ):
        key = f"{pair}_{timeframe}_{(lang or '').lower()}"
        with self._state_lock:
            cached = self.SIGNAL_CACHE.get(key)

        if not cached:
            return None

        if max_age_seconds is not None:
            cached_at = float(cached.get("_cached_at") or 0)
            if not cached_at or (time.time() - cached_at) > max_age_seconds:
                return None

        return dict(cached)

    def mark_manual_analysis_request(self) -> None:
        with self._state_lock:
            self.last_manual_analysis_request_ts = time.time()

    def last_manual_analysis_age(self) -> Optional[float]:
        with self._state_lock:
            ts = float(self.last_manual_analysis_request_ts or 0)

        if not ts:
            return None

        return max(0.0, time.time() - ts)

    # ------------------------------------------------------------------
    # User / subscription cache
    # ------------------------------------------------------------------

    def get_cached_user_status(self, user_id: int, max_age_seconds: int = 60) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None

        with self._state_lock:
            cached = self.user_status_cache.get(int(user_id))
            if not cached:
                return None

            refreshed_at = float(cached.get("refreshed_at") or 0)
            if time.time() - refreshed_at > max_age_seconds:
                return None

            return dict(cached)

    def set_cached_user_status(self, user_id: int, status: Dict[str, Any]) -> Dict[str, Any]:
        if not user_id:
            return dict(status or {})

        payload = dict(status or {})
        payload["refreshed_at"] = time.time()

        with self._state_lock:
            self.user_status_cache[int(user_id)] = payload

        return dict(payload)

    def invalidate_user_status(self, user_id: int) -> None:
        if not user_id:
            return

        with self._state_lock:
            self.user_status_cache.pop(int(user_id), None)

    def clear_user_status_cache(self) -> None:
        with self._state_lock:
            self.user_status_cache.clear()

    def get_cached_user_status_ids(self) -> List[int]:
        with self._state_lock:
            return list(self.user_status_cache.keys())

    # ------------------------------------------------------------------
    # SSE
    # ------------------------------------------------------------------

    @staticmethod
    def _queue_for_channel(channel: str):
        if channel == "price":
            return "price_sse_queue"
        return "signal_sse_queue"

    def _put_sse(self, channel: str, payload: dict) -> bool:
        if payload is None:
            return False

        q: queue.Queue = getattr(self, self._queue_for_channel(channel))

        try:
            q.put_nowait(payload)
            return True
        except queue.Full:
            try:
                _ = q.get_nowait()
            except queue.Empty:
                pass

            try:
                q.put_nowait(payload)
                logger.warning(f"{channel} SSE queue була переповнена — найстаріший елемент видалено")
                return True
            except queue.Full:
                logger.warning(f"{channel} SSE queue переповнена — подію скинуто")
                return False

    def publish_sse(self, payload: dict) -> bool:
        """
        Зворотна сумісність: старі виклики publish_sse() вважаємо сигналами.
        """
        return self._put_sse("signal", payload)

    def publish_signal_sse(self, payload: dict) -> bool:
        return self._put_sse("signal", payload)

    def publish_price_sse(self, payload: dict) -> bool:
        return self._put_sse("price", payload)

    def pop_pending_sse_events(self, channel: str, limit: int = 500) -> List[dict]:
        events: List[dict] = []
        q: queue.Queue = getattr(self, self._queue_for_channel(channel))

        for _ in range(limit):
            try:
                events.append(q.get_nowait())
            except queue.Empty:
                break

        return events

    def register_sse_listener(self, channel: str, maxsize: int = 200) -> Tuple[int, queue.Queue]:
        q: queue.Queue = queue.Queue(maxsize=maxsize)

        with self._listeners_lock:
            listener_id = self._next_listener_id
            self._next_listener_id += 1
            self._sse_listeners[channel][listener_id] = q
            logger.info(
                f"SSE listener #{listener_id} підключено до каналу '{channel}'. "
                f"Всього: {len(self._sse_listeners[channel])}"
            )
            return listener_id, q

    def unregister_sse_listener(self, channel: str, listener_id: int) -> None:
        with self._listeners_lock:
            if listener_id in self._sse_listeners[channel]:
                self._sse_listeners[channel].pop(listener_id, None)
                logger.info(
                    f"SSE listener #{listener_id} відключено від каналу '{channel}'. "
                    f"Всього: {len(self._sse_listeners[channel])}"
                )

    def sse_listener_count(self, channel: Optional[str] = None) -> int:
        with self._listeners_lock:
            if channel:
                return len(self._sse_listeners.get(channel, {}))
            return sum(len(v) for v in self._sse_listeners.values())

    def broadcast_sse_message(self, channel: str, message: str) -> None:
        with self._listeners_lock:
            listeners = list(self._sse_listeners[channel].items())

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
            self.unregister_sse_listener(channel, listener_id)

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
