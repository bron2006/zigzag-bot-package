# indicator_processor.py
import logging
import json
import time
import signal
import sys
from datetime import datetime, timezone
from collections import deque
import itertools

import pandas as pd
from twisted.internet import reactor, threads, defer
from twisted.internet.defer import DeferredQueue
from twisted.internet.task import LoopingCall

from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret, FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES, IDEAL_ENTRY_THRESHOLD
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from redis_client import get_redis
from indicators import prime_indicators, calculate_final_signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("indicator_processor")

SUPPORTED_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1day"]
PERIOD_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1day": 86400}
PERIOD_MAP = {"5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}

ALL_ASSETS = sorted({a.replace("/", "") for a in list(itertools.chain(*[p for p in FOREX_SESSIONS.values()], CRYPTO_PAIRS, COMMODITIES))})
ASSET_TO_CATEGORY = {}
for session in FOREX_SESSIONS.values():
    for asset in session:
        ASSET_TO_CATEGORY[asset.replace("/", "")] = 'forex'
ASSET_TO_CATEGORY.update({asset.replace("/", ""): 'crypto' for asset in CRYPTO_PAIRS})
ASSET_TO_CATEGORY.update({asset.replace("/", ""): 'commodities' for asset in COMMODITIES})


class IndicatorProcessor:
    def __init__(self):
        self.redis = get_redis()
        self.pubsub_thread = None
        self._stopping = False
        self.client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        self.symbol_cache = {}
        self.agg_candles = {tf: {} for tf in SUPPORTED_TIMEFRAMES}
        self.candle_buffers = {tf: {} for tf in SUPPORTED_TIMEFRAMES}
        self.priming_queue = DeferredQueue()

    def start(self):
        logger.info("Starting Indicator Processor...")
        self.client.on("ready", self._on_ready)
        reactor.callWhenRunning(self.client.start)
        reactor.run()
    
    def _on_ready(self):
        logger.info("cTrader client ready, loading symbols...")
        d = self.client.get_all_symbols()
        d.addCallbacks(self._on_symbols_loaded, lambda f: logger.error(f"Failed to load symbols: {f}"))

    def _on_symbols_loaded(self, raw_message):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)
        self.symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
        self.pubsub_thread = threads.deferToThread(self._listen_for_candles)
        LoopingCall(self._heartbeat).start(10, now=True)
        reactor.callLater(1, self._priming_worker)
        for symbol in ALL_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                self.priming_queue.put((symbol, tf))

    def stop(self, *args):
        # ... (код без змін) ...

    def _heartbeat(self):
        # ... (код без змін) ...

    def _listen_for_candles(self):
        # ... (код без змін) ...

    def _process_m1_candle(self, m1_candle: dict):
        # ... (код без змін) ...

    def _sleep(self, seconds):
        d = defer.Deferred()
        reactor.callLater(seconds, d.callback, None)
        return d

    @defer.inlineCallbacks
    def _priming_worker(self):
        # ... (код без змін) ...

    @defer.inlineCallbacks
    def _analyze_timeframe(self, symbol: str, tf: str):
        result_key = f"analysis:result:{symbol}:{tf}"
        try:
            df = pd.DataFrame(list(self.candle_buffers[tf].get(symbol, [])))
            if len(df) < 21:
                yield self.priming_queue.put((symbol, tf)); return
            
            daily_df = pd.DataFrame(list(self.candle_buffers['1day'].get(symbol, [])))
            if len(daily_df) < 21:
                yield self.priming_queue.put((symbol, '1day'))
                reactor.callLater(10, self._analyze_timeframe, symbol, tf); return
            
            state = prime_indicators(df)
            current_price = df.iloc[-1]['Close']
            final_result = calculate_final_signal(state, df, daily_df, current_price)
            if final_result.get("error"): return

            final_result['pair'] = symbol
            final_result['timestamp'] = int(time.time())
            
            yield threads.deferToThread(self.redis.set, result_key, json.dumps(final_result), ex=3600*6)
            logger.info(f"SUCCESS: Analysis for {symbol}:{tf} saved. Score: {final_result.get('bull_percentage')}")
            
            score = final_result.get('bull_percentage', 50)
            if tf == "5m" and (score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD)):
                category = ASSET_TO_CATEGORY.get(symbol.replace("/", ""))
                if category:
                    scanner_state = yield threads.deferToThread(self.redis.get, f"scanner_state:{category}")
                    if scanner_state == 'true':
                        logger.info(f"SCANNER TRIGGER for {symbol}. Sending notification.")
                        yield threads.deferToThread(self.redis.publish, "telegram_notifications", json.dumps(final_result))
        except Exception as e:
            logger.exception(f"Failed to analyze {symbol}:{tf}: {e}")
    
    def _get_historical_data(self, symbol, timeframe, count) -> defer.Deferred:
        # ... (код без змін) ...

def main():
    processor = IndicatorProcessor()
    signal.signal(signal.SIGINT, processor.stop)
    signal.signal(signal.SIGTERM, processor.stop)
    processor.start()

if __name__ == "__main__":
    main()