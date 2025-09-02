# price_streamer.py
# --- ПОЧАТОК ЗМІН: Діагностичний блок для перевірки REDIS_URL ---
import os
import sys
import logging

# Проста конфігурація логера на випадок, якщо основний не встигне завантажитись
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("streamer_diag")

log.info("--- DIAGNOSTIC START ---")
redis_url_value = os.getenv("REDIS_URL")
log.info(f"--- The value of REDIS_URL is: '{redis_url_value}' ---")
log.info(f"--- Type of REDIS_URL is: {type(redis_url_value)} ---")
log.info("--- DIAGNOSTIC END: Exiting now. ---")
sys.exit(0) # Завершуємо роботу після виводу діагностики
# --- КІНЕЦЬ ЗМІН ---


# Весь інший код залишається без змін, але не буде виконаний через sys.exit(0)
import json
import signal
import time
from typing import Dict, List

from twisted.internet import reactor
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq, ProtoOASymbolsListRes, ProtoOASymbolsListReq
)

from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES, get_ctrader_access_token, get_demo_account_id
from redis_client import get_redis

def _norm(pair: str) -> str:
    """Нормалізує назву пари, як у вашому основному коді."""
    return pair.replace("/", "").upper()

def _flatten_assets() -> List[str]:
    """Збирає всі активи з конфігурації в один список."""
    pairs = []
    for sess in FOREX_SESSIONS.values():
        pairs.extend(sess)
    pairs.extend(CRYPTO_PAIRS)
    pairs.extend(COMMODITIES)
    return sorted({_norm(p) for p in pairs})

class PriceStreamer:
    def __init__(self):
        self.client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        self.symbol_cache: Dict[str, int] = {}
        self.id_to_name_map: Dict[int, str] = {}
        self.subscribed_ids: List[int] = []
        self.redis = get_redis()
        self._stopping = False

    def start(self):
        """Запускає клієнт і реактор Twisted."""
        self.client.on("ready", self._on_ready)
        reactor.callWhenRunning(self.client.start, 
                                "live.ctraderapi.com", 
                                5035, 
                                get_ctrader_access_token(), 
                                get_demo_account_id())
        log.info("Connecting to cTrader...")
        reactor.run()

    def stop(self, *_):
        """Коректно зупиняє стрімер."""
        if self._stopping: return
        self._stopping = True
        log.info("Stopping price streamer...")
        try:
            if self.subscribed_ids:
                acc_id = self.client.account_id
                self.client.send(ProtoOAUnsubscribeSpotsReq(ctidTraderAccountId=acc_id, symbolId=self.subscribed_ids))
                log.info(f"Unsubscribed from {len(self.subscribed_ids)} symbols.")
        except Exception as e:
            log.warning(f"Unsubscribe error: {e}")
        
        reactor.callLater(1, reactor.stop)

    def _on_ready(self):
        """Викликається, коли клієнт cTrader готовий до роботи."""
        log.info("cTrader client is ready, loading symbols...")
        d = self.client.send(ProtoOASymbolsListReq(ctidTraderAccountId=self.client.account_id))
        d.addCallbacks(self._on_symbols_loaded, self._on_symbols_error)

    def _on_symbols_loaded(self, raw_message):
        """Обробляє список символів і підписується на потрібні."""
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)
        for s in res.symbol:
            norm_name = _norm(s.symbolName)
            self.symbol_cache[norm_name] = s.symbolId
            self.id_to_name_map[s.symbolId] = norm_name
        
        want_to_subscribe = _flatten_assets()
        symbol_ids_to_subscribe = sorted({self.symbol_cache[n] for n in want_to_subscribe if n in self.symbol_cache})

        if not symbol_ids_to_subscribe:
            log.error("No matching symbols found to subscribe. Check assets.json.")
            self.stop()
            return

        acc_id = self.client.account_id
        log.info(f"Subscribing to {len(symbol_ids_to_subscribe)} symbols for spot prices...")
        self.client.send(ProtoOASubscribeSpotsReq(ctidTraderAccountId=acc_id, symbolId=symbol_ids_to_subscribe))
        self.subscribed_ids = symbol_ids_to_subscribe

        self.client.on("spot_event", self._spot_handler)
        reactor.callLater(0, self._heartbeat)

    def _on_symbols_error(self, failure):
        msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
        log.error(f"Failed to load symbols: {msg}")
        self.stop()

    def _spot_handler(self, message):
        """Обробляє нові тіки (ціни) і публікує їх в Redis."""
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASpotEvent
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            norm_symbol = self.id_to_name_map.get(spot_event.symbolId)
            
            if not norm_symbol: return
            
            key = f"tick:{norm_symbol}"
            channel = "ticks_channel"
            ts_ms = int(time.time() * 1000)
            
            bid = spot_event.bid / (10**5) if spot_event.HasField("bid") else None
            ask = spot_event.ask / (10**5) if spot_event.HasField("ask") else None
            mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
            
            payload = {"symbol": norm_symbol, "bid": bid, "ask": ask, "mid": mid, "ts_ms": ts_ms}
            payload_json = json.dumps(payload)

            self.redis.set(key, payload_json, ex=60)
            self.redis.publish(channel, payload_json)
        except Exception:
            log.exception(f"Spot handler error")

    def _heartbeat(self):
        """Оновлює ключ в Redis, щоб показати, що сервіс живий."""
        try:
            self.redis.set("streamer:heartbeat", int(time.time()), ex=30)
        except Exception as e:
            log.warning(f"Heartbeat to Redis failed: {e}")
        if not self._stopping:
            reactor.callLater(10, self._heartbeat)

def main():
    """Головна функція для запуску стрімера."""
    streamer = PriceStreamer()
    signal.signal(signal.SIGINT, streamer.stop)
    signal.signal(signal.SIGTERM, streamer.stop)
    streamer.start()

if __name__ == "__main__":
    main()