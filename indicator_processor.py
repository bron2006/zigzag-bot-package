# indicator_processor.py
import logging
import json
import time
import signal
import sys
from datetime import datetime, timezone

import pandas as pd
from twisted.internet import reactor, threads
from twisted.internet.task import LoopingCall

from redis_client import get_redis
from indicators import prime_indicators, update_indicators
# Примітка: сюди потрібно буде перенести логіку отримання даних та аналізу з analysis.py
# для виконання "праймінгу". Наразі це заглушка.

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("indicator_processor")

SUPPORTED_TIMEFRAMES = ["5m", "15m", "1h", "4h"]
PERIOD_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}

class IndicatorProcessor:
    def __init__(self):
        self.redis = get_redis()
        self.pubsub_thread = None
        self._stopping = False
        # Кеш для агрегації свічок {tf: {symbol: candle}}
        self.agg_candles = {tf: {} for tf in SUPPORTED_TIMEFRAMES}

    def start(self):
        logger.info("Starting Indicator Processor...")
        # Запускаємо слухача Pub/Sub в окремому потоці
        self.pubsub_thread = threads.deferToThread(self._listen_for_candles)
        # Запускаємо періодичну перевірку стану
        LoopingCall(self._heartbeat).start(10, now=True)
        reactor.run()

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
            logger.exception("Heartbeat failed")

    def _listen_for_candles(self):
        """Прослуховує канал 'candles:M1' і обробляє вхідні M1 свічки."""
        pubsub = self.redis.pubsub()
        pubsub.subscribe("candles:M1")
        logger.info("Subscribed to 'candles:M1' channel.")
        
        for message in pubsub.listen():
            if self._stopping:
                break
            if message['type'] != 'message':
                continue
            try:
                candle_data = json.loads(message['data'])
                self._process_m1_candle(candle_data)
            except Exception:
                logger.exception("Error processing M1 candle")

    def _process_m1_candle(self, m1_candle: dict):
        """Агрегує M1 свічки у вищі таймфрейми та запускає аналіз при їх закритті."""
        symbol = m1_candle['symbol']
        ts = int(m1_candle['ts'])
        close_price = m1_candle['close']

        for tf in SUPPORTED_TIMEFRAMES:
            period = PERIOD_SECONDS[tf]
            # Визначаємо початок поточної свічки для даного таймфрейму
            candle_start_ts = (ts // period) * period
            
            # Якщо M1 свічка є першою для нового бару вищого ТФ
            if candle_start_ts > self.agg_candles[tf].get(symbol, {}).get('ts', 0):
                # Попередня свічка (якщо вона існувала) закрита, запускаємо аналіз
                if symbol in self.agg_candles[tf]:
                    closed_candle = self.agg_candles[tf][symbol]
                    logger.info(f"Closed {tf} candle for {symbol} at {datetime.fromtimestamp(closed_candle['ts'], tz=timezone.utc)}")
                    self._analyze_timeframe(symbol, tf, closed_candle)

                # Створюємо нову свічку
                self.agg_candles[tf][symbol] = {
                    'ts': candle_start_ts,
                    'open': m1_candle['open'],
                    'high': m1_candle['high'],
                    'low': m1_candle['low'],
                    'close': close_price,
                    'volume': m1_candle['volume']
                }
            else: # Оновлюємо поточну свічку
                current = self.agg_candles[tf][symbol]
                current['high'] = max(current['high'], m1_candle['high'])
                current['low'] = min(current['low'], m1_candle['low'])
                current['close'] = close_price
                current['volume'] += m1_candle['volume']

    def _analyze_timeframe(self, symbol: str, tf: str, closed_candle: dict):
        """Основна логіка аналізу для закритої свічки."""
        state_key = f"state:{symbol}:{tf}"
        result_key = f"analysis:result:{symbol}:{tf}"
        
        try:
            state_raw = self.redis.get(state_key)
            if not state_raw:
                # ЗАГЛУШКА: Потрібен "праймінг" - завантаження історії та розрахунок початкового стану
                logger.warning(f"Priming needed for {symbol}:{tf}, but not implemented yet. Skipping analysis.")
                # TODO: Implement priming logic here
                # 1. Fetch 200 historical bars for symbol/tf
                # 2. df = parse_bars_to_dataframe(bars)
                # 3. state = prime_indicators(df)
                # 4. self.redis.set(state_key, json.dumps(state))
                return

            state = json.loads(state_raw)
            new_state = update_indicators(state, closed_candle['close'])
            
            # Зберігаємо оновлений стан
            self.redis.set(state_key, json.dumps(new_state))

            # ЗАГЛУШКА: Розрахунок фінального вердикту
            # TODO: Move _calculate_core_signal logic here
            score = int(new_state.get('rsi', 50)) # Простий приклад: score = RSI
            verdict = "NEUTRAL"
            if score > 70: verdict = "SELL"
            if score < 30: verdict = "BUY"

            final_result = {
                "pair": symbol,
                "price": closed_candle['close'],
                "verdict_text": verdict,
                "bull_percentage": score,
                "bear_percentage": 100 - score,
                "reasons": [f"RSI({tf}) is {score:.1f}"],
                # ... інші поля з аналізу
                "timestamp": int(time.time())
            }

            # Зберігаємо фінальний результат, доступний для API
            self.redis.set(result_key, json.dumps(final_result), ex=3600) # Зберігаємо на годину
            logger.info(f"SUCCESS: Analysis for {symbol}:{tf} saved. Score: {score}")

        except Exception:
            logger.exception(f"Failed to analyze {symbol}:{tf}")


def main():
    processor = IndicatorProcessor()
    signal.signal(signal.SIGINT, processor.stop)
    signal.signal(signal.SIGTERM, processor.stop)
    processor.start()

if __name__ == "__main__":
    main()