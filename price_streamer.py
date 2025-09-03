# price_streamer.py
import json
import logging
import os
import signal
import sys
import time
from typing import Dict, List, Set

from twisted.internet import reactor
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq, ProtoOASymbolsListRes, 
    ProtoOASymbolsListReq, ProtoOASubscribeTrendbarsReq, ProtoOATrendbar
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES, get_ctrader_access_token, get_demo_account_id
from redis_client import get_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("price_streamer")

def _norm(pair: str) -> str:
    return pair.replace("/", "").upper()

def _flatten_assets() -> List[str]:
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
        self.subscribed_spot_ids: Set[int] = set()
        self.subscribed_trendbar_ids: Set[int] = set()
        self.redis = get_redis()
        self._stopping = False

    def start(self):
        self.client.on("ready", self._on_ready)
        reactor.callWhenRunning(self.client.start, 
                                "live.ctraderapi.com", 
                                5035, 
                                get_ctrader_access_token(), 
                                get_demo_account_id())
        log.info("Connecting to cTrader...")
        reactor.run()

    def stop(self, *_):
        if self._stopping: return
        self._stopping = True
        log.info("Stopping price streamer...")
        # Відписка не є критичною при зупинці, можна пропустити
        reactor.callLater(0.5, reactor.stop)

    def _on_ready(self):
        log.info("cTrader client is ready, loading symbols...")
        d = self.client.send(ProtoOASymbolsListReq(ctidTraderAccountId=self.client.account_id))
        d.addCallbacks(self._on_symbols_loaded, self._on_symbols_error)

    def _on_symbols_loaded(self, raw_message):
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)
        for s in res.symbol:
            norm_name = _norm(s.symbolName)
            self.symbol_cache[norm_name] = s.symbolId
            self.id_to_name_map[s.symbolId] = norm_name
        
        want_to_subscribe = _flatten_assets()
        symbol_ids_to_subscribe = sorted({self.symbol_cache[n] for n in want_to_subscribe if n in self.symbol_cache})

        if not symbol_ids_to_subscribe:
            log.error("No matching symbols found to subscribe.")
            self.stop()
            return

        acc_id = self.client.account_id
        
        # --- ПОЧАТОК ЗМІН: Додаємо підписку на свічки (trendbars) ---
        log.info(f"Subscribing to {len(symbol_ids_to_subscribe)} symbols for spots...")
        self.client.send(ProtoOASubscribeSpotsReq(ctidTraderAccountId=acc_id, symbolId=symbol_ids_to_subscribe))
        self.subscribed_spot_ids = set(symbol_ids_to_subscribe)
        
        log.info(f"Subscribing to {len(symbol_ids_to_subscribe)} symbols for M1 trendbars...")
        self.client.send(ProtoOASubscribeTrendbarsReq(ctidTraderAccountId=acc_id, symbolId=symbol_ids_to_subscribe, period=ProtoOATrendbarPeriod.M1))
        self.subscribed_trendbar_ids = set(symbol_ids_to_subscribe)
        # --- КІНЕЦЬ ЗМІН ---

        self.client.on("spot_event", self._spot_handler)
        # --- ПОЧАТОК ЗМІН: Підключаємо обробник свічок ---
        self.client.on("trendbar_event", self._trendbar_handler)
        # --- КІНЕЦЬ ЗМІН ---
        reactor.callLater(0, self._heartbeat)

    def _on_symbols_error(self, failure):
        msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
        log.error(f"Failed to load symbols: {msg}")
        self.stop()

    def _spot_handler(self, message):
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASpotEvent
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            norm_symbol = self.id_to_name_map.get(spot_event.symbolId)
            
            if not norm_symbol: return
            
            key = f"tick:{norm_symbol}"
            ts_ms = int(time.time() * 1000)
            
            bid = spot_event.bid / (10**5) if spot_event.HasField("bid") else None
            ask = spot_event.ask / (10**5) if spot_event.HasField("ask") else None
            mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
            
            payload = {"symbol": norm_symbol, "bid": bid, "ask": ask, "mid": mid, "ts_ms": ts_ms}
            self.redis.set(key, json.dumps(payload), ex=60)
        except Exception:
            log.exception("Spot handler error")
            
    # --- ПОЧАТОК ЗМІН: Новий обробник для свічок ---
    def _trendbar_handler(self, message):
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOATrendbarEvent
            event = ProtoOATrendbarEvent()
            event.ParseFromString(message.payload)
            norm_symbol = self.id_to_name_map.get(event.symbolId)
            if not norm_symbol: return

            bar = event.trendbar[0]
            key = f"candles:{norm_symbol}:m1"
            divisor = 10**5

            candle_data = {
                'ts': bar.utcTimestampInMinutes * 60,
                'Open': (bar.low + bar.deltaOpen) / divisor,
                'High': (bar.low + bar.deltaHigh) / divisor,
                'Low': bar.low / divisor,
                'Close': (bar.low + bar.deltaClose) / divisor,
                'Volume': bar.volume
            }
            
            # Додаємо нову свічку в список і обрізаємо його до 200 елементів
            self.redis.lpush(key, json.dumps(candle_data))
            self.redis.ltrim(key, 0, 199) # Залишаємо останні 200 свічок

        except Exception:
            log.exception("Trendbar handler error")
    # --- КІНЕЦЬ ЗМІН ---

    def _heartbeat(self):
        try:
            self.redis.set("streamer:heartbeat", int(time.time()), ex=30)
        except Exception as e:
            log.warning(f"Heartbeat to Redis failed: {e}")
        if not self._stopping:
            reactor.callLater(10, self._heartbeat)

def main():
    streamer = PriceStreamer()
    signal.signal(signal.SIGINT, streamer.stop)
    signal.signal(signal.SIGTERM, streamer.stop)
    streamer.start()

if __name__ == "__main__":
    main()