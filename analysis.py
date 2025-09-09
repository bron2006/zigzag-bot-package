# analysis.py
import logging
import pandas as pd
import numpy as np
import time
import talib # Використовуємо надійний talib замість pandas-ta

from typing import Optional, Dict, List
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        return d.errback(Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
        
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        return d.errback(Exception(f"Непідтримуваний таймфрейм: {period}"))

    now = int(time.time() * 1000)
    seconds_in_period = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1day': 86400}.get(period, 300)
    from_ts = now - (count * seconds_in_period * 1000)
    
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now
    )
    
    deferred = client.send(request, timeout=30)
    
    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes()
            response.ParseFromString(message.payload)
            logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
            if not response.trendbar:
                return d.callback(pd.DataFrame())

            divisor = 10**5
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                     'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor,
                     'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor,
                     'Volume': bar.volume} for bar in response.trendbar]
            df = pd.DataFrame(bars)
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e:
            d.errback(e)

    deferred.addCallbacks(process_response, d.errback)
    return d

def _find_candle_pattern(df: pd.DataFrame) -> Optional[Dict]:
    """Відтворюємо логіку пошуку патернів через talib."""
    try:
        # Перевірка наявності достатньої кількості даних
        if len(df) < 1:
            return None

        # Отримуємо дані для останньої свічки
        open_v, high_v, low_v, close_v = df['Open'], df['High'], df['Low'], df['Close']

        # Перевіряємо патерни для останньої свічки
        hammer = talib.CDLHAMMER(open_v, high_v, low_v, close_v).iloc[-1]
        engulfing = talib.CDLENGULFING(open_v, high_v, low_v, close_v).iloc[-1]
        doji = talib.CDLDOJI(open_v, high_v, low_v, close_v).iloc[-1]

        if engulfing != 0:
            pattern_type = 'bullish' if engulfing > 0 else 'bearish'
            arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
            return {'name': 'Engulfing', 'type': pattern_type, 'text': f'{arrow} Engulfing'}
        if hammer != 0:
            pattern_type = 'bullish'
            arrow = '⬆️'
            return {'name': 'Hammer', 'type': pattern_type, 'text': f'{arrow} Hammer'}
        if doji != 0:
            return {'name': 'Doji', 'type': 'neutral', 'text': '⚪️ Doji'}
            
        return None
    except Exception as e:
        logger.error(f"Помилка в _find_candle_pattern: {e}")
        return None

def _calculate_core_signal(df, daily_df, current_price):
    """Відтворюємо вашу стару логіку розрахунку, але з використанням talib."""
    try:
        # Розраховуємо індикатори через talib і додаємо їх як колонки
        df['RSI_14'] = talib.RSI(df['Close'], timeperiod=14)
        df['KAMA'] = talib.KAMA(df['Close'], timeperiod=14)
        upper, middle, lower = talib.BBANDS(df['Close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        df['BBU_20_2.0'] = upper
        df['BBL_20_2.0'] = lower
        macd, macdsignal, macdhist = talib.MACD(df['Close'], fastperiod=12, slowperiod=26, signalperiod=9)
        df['MACDh_12_26_9'] = macdhist
        df['ATRr_14'] = talib.ATR(df['High'], df['Low'], df['Close'], timeperiod=14)

        daily_df['KAMA_14'] = talib.KAMA(daily_df['Close'], timeperiod=14)
    except Exception as e:
        logger.error(f"Критична помилка при розрахунку індикаторів: {e}")
        return { "score": 50, "reasons": ["Помилка розрахунку індикаторів"] }

    last = df.iloc[-1]
    last_daily = daily_df.iloc[-1]
    
    score = 50
    reasons = []
    critical_warning = None
    
    # Розрахунок рівнів підтримки/опору
    long_term_support_raw = daily_df['Low'].rolling(window=20, center=True, min_periods=3).min()
    long_term_resistance_raw = daily_df['High'].rolling(window=20, center=True, min_periods=3).max()
    long_term_support = sorted(long_term_support_raw.dropna().unique().tolist())
    long_term_resistance = sorted(long_term_resistance_raw.dropna().unique().tolist(), reverse=True)
    
    candle_pattern = _find_candle_pattern(df)
    
    is_daily_uptrend = None
    if pd.notna(last_daily.get('KAMA_14')):
        is_daily_uptrend = last_daily['Close'] > last_daily['KAMA_14']
    
    if pd.notna(last.get('MACDh_12_26_9')):
        if last['MACDh_12_26_9'] > 0: score += 15; reasons.append("MACD росте")
        else: score -= 15; reasons.append("MACD падає")
    
    # Імітація Ichimoku Cloud через KAMA
    if pd.notna(last.get('KAMA')):
        if current_price > last['KAMA']:
            score += 15; reasons.append("Тренд: Ціна над KAMA")
        else:
            score -= 15; reasons.append("Тренд: Ціна під KAMA")

    if candle_pattern:
        if candle_pattern['type'] == 'bullish':
            score += 20; reasons.append(f"Бичачий патерн: {candle_pattern['name']}")
        elif candle_pattern['type'] == 'bearish':
            score -= 20; reasons.append(f"Ведмежий патерн: {candle_pattern['name']}")
        else:
             reasons.append(f"Нейтральний патерн: {candle_pattern['name']}")

    rsi = last.get('RSI_14')
    if pd.notna(rsi):
        if rsi < 30: score += 10; reasons.append("Ознаки перепроданості (RSI)")
        elif rsi > 70: score -= 10; reasons.append("Ознаки перекупленості (RSI)")

    last_atr = last.get('ATRr_14')
    if last_atr and pd.notna(last_atr):
        atr_threshold = last_atr * 0.5
        resistance_candidates = [r for r in long_term_resistance if r > current_price]
        if resistance_candidates and (min(resistance_candidates) - current_price) < atr_threshold:
            score -= 20; reasons.append("⚠️ Ціна біля сильного денного опору")
        support_candidates = [s for s in long_term_support if s < current_price]
        if support_candidates and (current_price - max(support_candidates)) < atr_threshold:
            score += 20; reasons.append("⚠️ Ціна біля сильної денної підтримки")

    if is_daily_uptrend is not None:
        if not is_daily_uptrend and score > 60:
            critical_warning = "❗️ Сигнал на покупку суперечить денному даунтренду"
            score = 55
        elif is_daily_uptrend and score < 40:
            critical_warning = "❗️ Сигнал на продаж суперечить денному аптренду"
            score = 45
            
    score = int(np.clip(score, 0, 100))
    
    support_candidates = [s for s in long_term_support if s < current_price]
    support = max(support_candidates) if support_candidates else None
    resistance_candidates = [r for r in long_term_resistance if r > current_price]
    resistance = min(resistance_candidates) if resistance_candidates else None

    return {
        "score": score, "reasons": reasons, "support": support, "resistance": resistance,
        "candle_pattern": candle_pattern, "critical_warning": critical_warning
    }

def _generate_verdict(score):
    if score > 80: return "⬆️ Strong BUY"
    if score > 65: return "↗️ Moderate BUY"
    if score < 20: return "⬇️ Strong SELL"
    if score < 35: return "↘️ Moderate SELL"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    final_deferred = Deferred()

    def on_data_ready(results):
        try:
            success1, df = results[0]
            success2, daily_df = results[1]

            if not (success1 and success2) or df.empty or len(df) < 50 or daily_df.empty:
                return final_deferred.callback({"error": f"Not enough historical data for {timeframe} analysis."})
                
            current_price = df.iloc[-1]['Close']
            
            analysis = _calculate_core_signal(df, daily_df, current_price)
            
            verdict = _generate_verdict(analysis['score'])

            add_signal_to_history({
                'user_id': user_id, 'pair': symbol, 
                'price': current_price, 'bull_percentage': analysis['score']
            })
            
            response_data = {
                "pair": symbol, "price": current_price, "verdict_text": verdict, 
                "reasons": analysis['reasons'], "support": analysis['support'], 
                "resistance": analysis['resistance'], "bull_percentage": analysis['score'],
                "bear_percentage": 100 - analysis['score'], "candle_pattern": analysis.get('candle_pattern'),
                "special_warning": analysis.get("critical_warning")
            }
            final_deferred.callback(response_data)
            
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    d1 = get_market_data(client, symbol_cache, symbol, timeframe, 300)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 300)
    
    d_list = DeferredList([d1, d2], consumeErrors=True)
    d_list.addCallback(on_data_ready)
    
    return final_deferred