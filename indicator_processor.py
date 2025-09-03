# indicator_processor.py
import logging
import json
import time
import signal
import sys
from datetime import datetime, timezone
from collections import deque

import pandas as pd
from twisted.internet import reactor, threads, defer
from twisted.internet.task import LoopingCall

from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from redis_client import get_redis
from indicators import prime_indicators, calculate_final_signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("indicator_processor")

SUPPORTED_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1day"]
PERIOD_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1day": 86400}
PERIOD_MAP = {"5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}

class IndicatorProcessor:
    def __init__(self):
        self.redis = get_redis()
        self.pubsub_thread = None
        self._stopping = False
        self.client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        self.symbol_cache = {}
        self.agg_candles = {tf: {} for tf in SUPPORTED_TIMEFRAMES}
        self.candle_buffers = {tf: {} for tf in SUPPORTED_TIMEFRAMES}
        self.priming_in_progress = set()
        # --- ПОЧАТОК ЗМІН: Додано чергу для праймінгу ---
        self.priming_queue = defer.Queue()
        # --- КІНЕЦЬ ЗМІН ---

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
        logger.info(f"Loaded {len(self.symbol_cache)} symbols.")
        
        self.pubsub_thread = threads.deferToThread(self._listen_for_candles)
        LoopingCall(self._heartbeat).start(10, now=True)
        # --- ПОЧАТОК ЗМІН: Запуск "працівника", що обробляє чергу ---
        reactor.callLater(1, self._priming_worker)
        # --- КІНЕЦЬ ЗМІН ---

    def stop(self, *args):
        logger.info("Stopping Indicator Processor...")
        self._stopping = True
        if self.pubsub_thread and self.pubsub_thread.running:
            self.pubsub_thread.cancel()
        if reactor.running:
            reactor.stop()
        sys.exit(0)

    def _heartbeat(self):
        try:
            self.redis.set("processor:heartbeat", int(time.time()), ex=60)
        except Exception:
            logger.exception("Heartbeat failed")

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
                current = self.agg_candles[tf][symbol]
                current['high'] = max(current['high'], m1_candle['high'])
                current['low'] = min(current['low'], m1_candle['low'])
                current['close'] = m1_candle['close']
                current['volume'] += m1_candle['volume']

    # --- ПОЧАТОК ЗМІН: Новий метод-працівник для обробки черги ---
    @defer.inlineCallbacks
    def _priming_worker(self):
        """Обробляє чергу завдань на праймінг послідовно."""
        logger.info("Starting priming worker...")
        while not self._stopping:
            try:
                symbol, tf = yield self.priming_queue.get()
                
                # Перевірка, чи не був цей символ вже оброблений, поки чекали в черзі
                state_key = f"state:{symbol}:{tf}"
                is_primed = yield threads.deferToThread(self.redis.exists, state_key)
                if is_primed:
                    logger.info(f"WORKER: State for {symbol}:{tf} already exists. Skipping.")
                    continue

                logger.info(f"WORKER: Got priming task for {symbol}:{tf}")
                self.priming_in_progress.add((symbol, tf))
                
                try:
                    df = yield self._get_historical_data(symbol, tf, 200)
                    if df is None or df.empty or len(df) < 200:
                        logger.error(f"WORKER: Not enough data to prime {symbol}:{tf} ({len(df) if df is not None else 0} candles)")
                        continue
                    
                    self.candle_buffers[tf][symbol] = deque(df.to_dict('records'), maxlen=200)
                    state = prime_indicators(df)
                    if not state:
                        logger.error(f"WORKER: Failed to generate initial state for {symbol}:{tf}")
                        continue

                    yield threads.deferToThread(self.redis.set, state_key, json.dumps(state))
                    logger.info(f"WORKER: Priming successful for {symbol}:{tf}")

                    # Після успішного праймінгу, робимо перший аналіз
                    reactor.callFromThread(self._analyze_timeframe, symbol, tf)

                except Exception as e:
                    logger.error(f"WORKER: Failed to prime {symbol}:{tf}: {e}")
                finally:
                    if (symbol, tf) in self.priming_in_progress:
                        self.priming_in_progress.remove((symbol, tf))
            
            except Exception as e:
                logger.exception(f"Critical error in priming worker loop: {e}")
    # --- КІНЕЦЬ ЗМІН ---

    @defer.inlineCallbacks
    def _analyze_timeframe(self, symbol: str, tf: str):
        state_key, result_key = f"state:{symbol}:{tf}", f"analysis:result:{symbol}:{tf}"
        
        try:
            state_raw = yield threads.deferToThread(self.redis.get, state_key)
            
            # --- ПОЧАТОК ЗМІН: Логіка постановки в чергу ---
            if not state_raw:
                # Якщо стан не знайдено, ставимо в чергу на праймінг і виходимо
                if (symbol, tf) not in self.priming_in_progress:
                    logger.info(f"Adding priming task for {symbol}:{tf} to the queue.")
                    yield self.priming_queue.put((symbol, tf))
                return
            # --- КІНЕЦЬ ЗМІН ---
            
            state = json.loads(state_raw)
            if not self.candle_buffers[tf].get(symbol): return
            
            df = pd.DataFrame(list(self.candle_buffers[tf][symbol]))
            state = prime_indicators(df)
            yield threads.deferToThread(self.redis.set, state_key, json.dumps(state))
            
            if tf != '1day' and self.candle_buffers['1day'].get(symbol):
                daily_df = pd.DataFrame(list(self.candle_buffers['1day'][symbol]))
                current_price = self.candle_buffers[tf][symbol][-1]['close']
                
                final_result = calculate_final_signal(state, df, daily_df, current_price)
                final_result['pair'] = symbol
                final_result['timestamp'] = int(time.time())
                
                yield threads.deferToThread(self.redis.set, result_key, json.dumps(final_result), ex=3600*6)
                logger.info(f"SUCCESS: Analysis for {symbol}:{tf} saved. Score: {final_result.get('bull_percentage')}")

        except Exception as e:
            logger.exception(f"Failed to analyze {symbol}:{tf}: {e}")
    
    def _get_historical_data(self, symbol, timeframe, count) -> defer.Deferred:
        d = defer.Deferred()
        symbol_details = self.symbol_cache.get(symbol)
        if not symbol_details:
            d.errback(Exception(f"Symbol {symbol} not in cache"))
            return d
        
        now = int(time.time() * 1000)
        from_ts = now - (count * PERIOD_SECONDS[timeframe] * 1500)
        request = ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=self.client._client.account_id,
            symbolId=symbol_details.symbolId, period=PERIOD_MAP[timeframe],
            fromTimestamp=from_ts, toTimestamp=now
        )
        
        # --- ПОЧАТОК ЗМІН: Збільшено таймаут ---
        api_call = self.client.send(request, timeout=60)
        # --- КІНЕЦЬ ЗМІН ---
        def on_ok(msg):
            res = ProtoOAGetTrendbarsRes(); res.ParseFromString(msg.payload)
            divisor = 10**5
            bars = [{
                'ts': bar.utcTimestampInMinutes * 60,
                'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor,
                'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor,
                'Volume': bar.volume
            } for bar in res.trendbar]
            df = pd.DataFrame(bars)
            d.callback(df.sort_values(by='ts').