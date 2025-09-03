# price_streamer.py
import json
import logging
import os
import signal
import sys
import time
from typing import Dict, List
from datetime import datetime, timezone

from twisted.internet import reactor
from twisted.internet.task import LoopingCall # --- ПОЧАТОК ЗМІН ---
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq, ProtoOASymbolsListRes
)

from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES
from redis_client import get_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("price_streamer")

def _norm(pair: str) -> str:
    return pair.replace("/", "").upper()

def _flatten_assets() -> List[str]:
    pairs = []
    for sess in FOREX_SESSIONS.values():
        pairs.extend(sess)
    pairs.extend(CRYPTO_PAIRS)
    pairs.extend(COMMODITIES)
    uniq = sorted({ _norm(p) for p in pairs })
    return uniq

class PriceStreamer:
    def __init__(self):
        self.client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        self.symbol_cache: Dict[str, int] = {}
        self.subscribed_ids: List[int] = []
        self.redis = get_redis()
        self._stopping = False
        # --- ПОЧАТОК ЗМІН: Кеш для M1 свічок ---
        self.current_m1_candles: Dict[str, dict] = {}
        self.candle_publisher = LoopingCall(self._close_and_publish_candles)
        # --- КІНЕЦЬ ЗМІН ---


    def start(self):
        self.client.on("ready", self._on_ready)
        reactor.callWhenRunning(self.client.start)
        log.info("Connecting to cTrader...")
        reactor.run()

    def stop(self, *_):
        if self._stopping:
            return
        self._stopping = True
        try:
            if self.subscribed_ids:
                acc_id = self.client._client.account_id
                self.client.send(ProtoOAUnsubscribeSpotsReq(ctidTraderAccountId=acc_id, symbolId=self.subscribed_ids))
        except Exception as e:
            log.warning(f"Unsubscribe error: {e}")
        try:
            self.client.stop()
        except Exception:
            pass
        try:
            reactor.stop()
        except Exception:
            pass
        log.info("Stopped price_streamer")
        sys.exit(0)

    def _on_ready(self):
        log.info("cTrader ready, loading symbols...")
        d = self.client.get_all_symbols()
        d.addCallbacks(self._on_symbols_loaded, self._on_symbols_error)

    def _on_symbols_loaded(self, raw_message):
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)

        for s in res.symbol:
            name_norm = s.symbolName.replace("/", "").upper()
            self.symbol_cache[name_norm] = s.symbolId

        want = _flatten_assets()
        symbol_ids = [self.symbol_cache[n] for n in want if n in self.symbol_cache]
        symbol_ids = sorted(set(symbol_ids))

        if not symbol_ids:
            log.error("No matching symbols to subscribe. Check assets.json and broker symbols.")
            reactor.stop()
            return

        acc_id = self.client._client.account_id
        log.info(f"Subscribing {len(symbol_ids)} symbols for spots...")
        self.client.send(ProtoOASubscribeSpotsReq(ctidTraderAccountId=acc_id, symbolId=symbol_ids))
        self.subscribed_ids = symbol_ids

        # attach handlers
        for name_norm, sid in list(self.symbol_cache.items()):
            if sid in symbol_ids:
                event_name = f"spot_event_{sid}"
                self.client.on(event_name, self._make_spot_handler(name_norm))

        reactor.callLater(0, self._heartbeat)
        
        # --- ПОЧАТОК ЗМІН: Запуск таймера для закриття свічок ---
        # Вирівнюємо запуск по початку наступної хвилини
        now = datetime.now(timezone.utc)
        delay_to_next_minute = 60 - now.second
        log.info(f"Candle publisher will start in {delay_to_next_minute} seconds.")
        reactor.callLater(delay_to_next_minute, self.candle_publisher.start, 60.0)
        # --- КІНЕЦЬ ЗМІН ---

    def _on_symbols_error(self, failure):
        msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
        log.error(f"Failed to load symbols: {msg}")
        reactor.stop()
        
    # --- ПОЧАТОК ЗМІН: Логіка агрегації M1 свічок ---
    def _update_m1_candle(self, symbol: str, price: float, ts_sec: int):
        """Оновлює або створює M1 свічку на основі нового тіку."""
        candle_start_ts = (ts_sec // 60) * 60
        
        if symbol not in self.current_m1_candles:
            self.current_m1_candles[symbol] = {
                "symbol": symbol,
                "ts": candle_start_ts,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1, # Рахуємо кількість тіків
            }
        else:
            candle = self.current_m1_candles[symbol]
            # Якщо тік прийшов для нової хвилини, закриваємо стару і починаємо нову
            if candle_start_ts > candle['ts']:
                self._publish_candle(candle)
                self.current_m1_candles[symbol] = {
                    "symbol": symbol,
                    "ts": candle_start_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1,
                }
            else: # Оновлюємо поточну
                candle['high'] = max(candle['high'], price)
                candle['low'] = min(candle['low'], price)
                candle['close'] = price
                candle['volume'] += 1

    def _publish_candle(self, candle: dict):
        """Публікує готову свічку в Redis."""
        try:
            channel = "candles:M1"
            payload = json.dumps(candle)
            self.redis.publish(channel, payload)
        except Exception:
            log.exception(f"Failed to publish M1 candle for {candle['symbol']}")

    def _close_and_publish_candles(self):
        """Закриває всі поточні M1 свічки та публікує їх."""
        log.debug(f"Closing M1 candles for publishing. Found {len(self.current_m1_candles)} active candles.")
        candles_to_publish = list(self.current_m1_candles.values())
        self.current_m1_candles = {} # Очищуємо для наступної хвилини

        for candle in candles_to_publish:
            self._publish_candle(candle)
    # --- КІНЕЦЬ ЗМІН ---


    def _make_spot_handler(self, norm_symbol: str):
        key = f"tick:{norm_symbol}"
        channel = "ticks"

        def handler(spot_event):
            try:
                ts_ms = int(time.time() * 1000)
                bid = spot_event.bid / (10**5) if spot_event.HasField("bid") else None
                ask = spot_event.ask / (10**5) if spot_event.HasField("ask") else None
                mid = None
                if bid is not None and ask is not None:
                    mid = (bid + ask) / 2.0
                
                if mid is None: # Немає ціни - немає оновлення
                    return

                # --- ПОЧАТОК ЗМІН: Виклик агрегатора та оновлення публікації ---
                # Оновлюємо M1 свічку
                self._update_m1_candle(norm_symbol, mid, ts_ms // 1000)

                payload = {
                    "symbol": norm_symbol, "bid": bid, "ask": ask,
                    "mid": mid, "ts_ms": ts_ms,
                }
                
                # Зберігаємо останній тік і публікуємо (стара логіка залишається)
                self.redis.set(key, json.dumps(payload), ex=60)
                self.redis.publish(channel, json.dumps(payload))
                # --- КІНЕЦЬ ЗМІН ---
            except Exception:
                log.exception(f"Spot handler error for {norm_symbol}")

        return handler

    def _heartbeat(self):
        try:
            self.redis.set("streamer:heartbeat", int(time.time()), ex=120)
        except Exception:
            log.exception("Heartbeat error")
        if not self._stopping:
            reactor.callLater(10, self._heartbeat)

def main():
    ps = PriceStreamer()
    signal.signal(signal.SIGINT, ps.stop)
    signal.signal(signal.SIGTERM, ps.stop)
    ps.start()

if __name__ == "__main__":
    main()