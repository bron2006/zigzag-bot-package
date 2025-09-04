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
        LoopingCall(self._log_scanner_status).start(30)
        reactor.callLater(1, self._priming_worker)
        for symbol in ALL_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                self.priming_queue.put((symbol, tf))

    def stop(self, *args):
        logger.info("Stopping Indicator Processor...")
        self._stopping = True
        if reactor.running:
            reactor.stop()
        sys.exit(0)

    def _heartbeat(self):
        try:
            self.redis.set("processor:heartbeat", int(time.time()), ex=60)
        except Exception:
            pass

    def _log_scanner_status(self):
        try:
            r = get_redis()
            keys = r.keys("scanner_state:*")
            active_scanners = [k.split(":")[-1] for k in keys if r.get(k) == 'true']
            if active_scanners:
                logger.info(f"SCANNER ACTIVE for: {', '.join(active_scanners)}. Awaiting strong signals...")
            else:
                logger.info("All scanners are disabled.")
        except Exception:
            pass

    def _listen_for_candles(self):
        pubsub = self.redis.pubsub()
        pubsub.subscribe("candles:M1")
        logger.info("Subscribed to 'candles:M1' channel.")
        for message in pubsub.listen():
            if self._stopping: break
            if message['type'] != 'message': continue
            try:
                self._process_m1_candle(json.loads(message['data']))
            except Exception:
                logger.exception("Error processing M1 candle")

    def _process_m1_candle(self, m1_candle: dict):
        symbol = m1_candle['symbol']
        ts = int(m1_candle['ts'])
        for tf in SUPPORTED_TIMEFRAMES:
            period = PERIOD_SECONDS[tf]
            candle_start_ts = (ts // period) * period
            if candle_start_ts > self.agg_candles[tf].get(symbol, {}).get('ts', 0):
                if symbol in self.agg_candles[tf]:
                    closed_candle = self.agg_candles[tf][symbol]
                    if symbol not in self.candle_buffers[tf]:
                        self.candle_buffers[tf][symbol] = deque(maxlen=200)
                    self.candle_buffers[tf][symbol].append(closed_candle)
                    reactor.callFromThread(self._analyze_timeframe, symbol, tf)
                self.agg_candles[tf][symbol] = {k: v for k, v in m1_candle.items() if k != 'symbol'}
                self.agg_candles[tf][symbol]['ts'] = candle_start_ts
            else:
                if symbol in self.agg_candles[tf]:
                    current = self.agg_candles[tf][symbol]
                    current['High'] = max(current.get('High', 0), m1_candle['High'])
                    current['Low'] = min(current.get('Low', 999999), m1_candle['Low'])
                    current['Close'] = m1_candle['Close']
                    current['Volume'] += m1_candle.get('Volume', 0)

    def _sleep(self, seconds):
        d = defer.Deferred()
        reactor.callLater(seconds, d.callback, None)
        return d

    @defer.inlineCallbacks
    def _priming_worker(self):
        logger.info("Starting priming worker...")
        while not self._stopping:
            try:
                symbol, tf = yield self.priming_queue.get()
                if self.candle_buffers[tf].get(symbol) and len(self.candle_buffers[tf][symbol]) >= 21:
                    continue
                
                logger.info(f"WORKER: Processing priming task for {symbol}:{tf}")
                try:
                    df = yield self._get_historical_data(symbol, tf, 200)
                    if df is None or len(df) < 21:
                        logger.error(f"WORKER: Not enough data for {symbol}:{tf}. Skipping.")
                        continue
                    self.candle_buffers[tf][symbol] = deque(df.to_dict('records'), maxlen=200)
                    logger.info(f"WORKER: Priming successful for {symbol}:{tf}")
                    reactor.callFromThread(self._analyze_timeframe, symbol, tf)
                except Exception as e:
                    logger.error(f"WORKER: Failed to prime {symbol}:{tf}: {e}")
                
                yield self._sleep(0.5)
            except Exception as e:
                logger.exception(f"Critical error in priming worker: {e}")

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
        d = defer.Deferred()
        symbol_details = self.symbol_cache.get(symbol)
        if not symbol_details:
            d.errback(Exception(f"Symbol {symbol} not in cache"))
            return d
        
        now = int(time.time() * 1000)
        from_ts = now - (count * PERIOD_SECONDS[timeframe] * 2000)
        request = ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=self.client._client.account_id,
            symbolId=symbol_details.symbolId, period=PERIOD_MAP[timeframe],
            fromTimestamp=from_ts, toTimestamp=now
        )
        api_call = self.client.send(request, timeout=60)
        def on_ok(msg):
            res = ProtoOAGetTrendbarsRes(); res.ParseFromString(msg.payload)
            divisor = 10**5
            bars = [{'ts': bar.utcTimestampInMinutes * 60, 'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor, 'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor, 'Volume': bar.volume} for bar in res.trendbar]
            df = pd.DataFrame(bars)
            if df.empty:
                d.callback(df)
                return
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        def on_err(f):
            d.errback(f)
        api_call.addCallbacks(on_ok, on_err)
        return d

def main():
    processor = IndicatorProcessor()
    signal.signal(signal.SIGINT, processor.stop)
    signal.signal(signal.SIGTERM, processor.stop)
    processor.start()

if __name__ == "__main__":
    main()