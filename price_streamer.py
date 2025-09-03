# price_streamer.py
import json
import logging
import os
import signal
import sys
import time
from typing import Dict, List

from twisted.internet import reactor
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

    def _on_symbols_error(self, failure):
        msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
        log.error(f"Failed to load symbols: {msg}")
        reactor.stop()

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

                payload = {
                    "symbol": norm_symbol,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "ts_ms": ts_ms,
                }

                # save last tick and publish
                self.redis.set(key, json.dumps(payload), ex=60)
                self.redis.publish(channel, json.dumps(payload))
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
