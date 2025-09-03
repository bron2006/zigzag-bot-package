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

# --- ПОЧАТОК ЗМІН: Додано імпорти для роботи з API та аналізом ---
from spotware_connect import SpotwareConnect
from config import get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from redis_client import get_redis
from indicators import prime_indicators, update_indicators, calculate_final_signal
# --- КІНЕЦЬ ЗМІН ---

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
        # --- ПОЧАТОК ЗМІН: Додано клієнт, кеші та буфери ---
        self.client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        self.symbol_cache = {}
        self.agg_candles = {tf: {} for tf in SUPPORTED_TIMEFRAMES}
        # Буфери для зберігання останніх N свічок {tf: {symbol: deque}}
        self.candle_buffers = {tf: {} for tf in SUPPORTED_TIMEFRAMES}
        self.priming_in_progress = set() # { (symbol, tf) }
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

    def stop(self, *args):
        # ... (код зупинки залишається без змін) ...
        logger.info("Stopping Indicator Processor...")
        self._stopping = True
        if reactor.running:
            reactor.stop()
        sys.exit(0)

    def _heartbeat(self):
        # ... (код heartbeat залишається без змін) ...
        try:
            self.redis.set("processor:heartbeat", int(time.time()), ex=60)
        except Exception:
            logger.exception("Heartbeat failed")

    def _listen_for_candles(self):
        # ... (код прослуховування залишається майже без змін) ...
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
        ts, close_price = int(m1_candle['ts']), m1_candle['close']

        for tf in SUPPORTED_TIMEFRAMES:
            period = PERIOD_SECONDS[tf]
            candle_start_ts = (ts // period) * period
            
            if candle_start_ts > self.agg_candles[tf].get(symbol, {}).get('ts', 0):
                if symbol in self.agg_candles[tf]:
                    closed_candle = self.agg_candles[tf][symbol]
                    logger.info(f"Closed {tf} candle for {symbol}")
                    # Додаємо свічку в буфер
                    if symbol not in self.candle_buffers[tf]:
                        self.candle_buffers[tf][symbol] = deque(maxlen=200)
                    self.candle_buffers[tf][symbol].append(closed_candle)
                    
                    # Запускаємо аналіз в головному потоці Twisted
                    reactor.callFromThread(self._analyze_timeframe, symbol, tf)

                self.agg_candles[tf][symbol] = {k: v for k, v in m1_candle.items() if k != 'symbol'}
                self.agg_candles[tf][symbol]['ts'] = candle_start_ts
            else:
                current = self.agg_candles[tf][symbol]
                current['high'] = max(current['high'], m1_candle['high'])
                current['low'] = min(current['low'], m1_candle['low'])
                current['close'] = close_price
                current['volume'] += m1_candle['volume']

    # --- ПОЧАТОК ЗМІН: Оновлена логіка аналізу з праймінгом ---
    @defer.inlineCallbacks
    def _analyze_timeframe(self, symbol: str, tf: str):
        state_key, result_key = f"state:{symbol}:{tf}", f"analysis:result:{symbol}:{tf}"
        if (symbol, tf) in self.priming_in_progress: return
        
        try:
            state_raw = yield threads.deferToThread(self.redis.get, state_key)
            if not state_raw:
                logger.info(f"Priming needed for {symbol}:{tf}. Fetching history...")
                self.priming_in_progress.add((symbol, tf))
                try:
                    df = yield self._get_historical_data(symbol, tf, 200)
                    if df is None or df.empty or len(df) < 200:
                        logger.error(f"Not enough data to prime {symbol}:{tf} ({len(df) if df is not None else 0} candles)")
                        return
                    
                    # Зберігаємо історію свічок для майбутнього аналізу
                    self.candle_buffers[tf][symbol] = deque(df.to_dict('records'), maxlen=200)
                    state = prime_indicators(df)
                    if not state:
                        logger.error(f"Failed to generate initial state for {symbol}:{tf}")
                        return
                    yield threads.deferToThread(self.redis.set, state_key, json.dumps(state))
                    logger.info(f"Priming successful for {symbol}:{tf}")
                finally:
                    self.priming_in_progress.remove((symbol, tf))
            
            # --- Основний цикл аналізу ---
            closed_candle = self.candle_buffers[tf][symbol][-1]
            # state = update_indicators(state, closed_candle) # Спрощене оновлення поки що вимкнено
            
            # Для точного розрахунку перераховуємо на поточних даних
            df = pd.DataFrame(list(self.candle_buffers[tf][symbol]))
            state = prime_indicators(df) # Перераховуємо стан для точності
            yield threads.deferToThread(self.redis.set, state_key, json.dumps(state))
            
            # Для аналізу потрібні денні дані
            if tf != '1day' and self.candle_buffers['1day'].get(symbol):
                daily_df = pd.DataFrame(list(self.candle_buffers['1day'][symbol]))
                
                final_result = calculate_final_signal(state, df, daily_df, closed_candle['close'])
                final_result['pair'] = symbol
                final_result['timestamp'] = int(time.time())
                
                yield threads.deferToThread(self.redis.set, result_key, json.dumps(final_result), ex=3600*6)
                logger.info(f"SUCCESS: Analysis for {symbol}:{tf} saved. Score: {final_result.get('bull_percentage')}")

        except Exception as e:
            logger.exception(f"Failed to analyze {symbol}:{tf}: {e}")
    
    def _get_historical_data(self, symbol, timeframe, count) -> defer.Deferred:
        """Завантажує історичні дані з cTrader."""
        d = defer.Deferred()
        symbol_details = self.symbol_cache.get(symbol)
        if not symbol_details:
            d.errback(Exception(f"Symbol {symbol} not in cache"))
            return d
        
        now = int(time.time() * 1000)
        from_ts = now - (count * PERIOD_SECONDS[timeframe] * 1500) # З запасом
        request = ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=self.client._client.account_id,
            symbolId=symbol_details.symbolId, period=PERIOD_MAP[timeframe],
            fromTimestamp=from_ts, toTimestamp=now
        )
        
        api_call = self.client.send(request, timeout=20)
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
            if not df.empty:
                df['ts'] = pd.to_datetime(df['ts'], unit='s', utc=True)
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        def on_err(f):
            d.errback(f)
        api_call.addCallbacks(on_ok, on_err)
        return d
    # --- КІНЕЦЬ ЗМІН ---

def main():
    processor = IndicatorProcessor()
    signal.signal(signal.SIGINT, processor.stop)
    signal.signal(signal.SIGTERM, processor.stop)
    processor.start()

if __name__ == "__main__":
    main()