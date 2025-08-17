# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import time
from twisted.internet import threads

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history
from config import logger, MARKET_DATA_CACHE, SYMBOL_DATA_CACHE, CACHE_LOCK, ANALYSIS_TIMEFRAMES

def get_market_data(ctrader_service, pair, tf, limit=300):
    key = f"{pair}_{tf}_{limit}"
    if key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]

    symbol_details = SYMBOL_DATA_CACHE.get(pair)
    if not symbol_details:
        # --- ВИПРАВЛЕННЯ: Додано більш інформативне повідомлення про помилку ---
        available = list(SYMBOL_DATA_CACHE.keys())[:5]
        raise Exception(f"Пара '{pair}' не знайдена в кеші. Доступні: {available}...")

    tf_map = {"15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}
    if tf not in tf_map:
        raise Exception(f"Непідтримуваний таймфрейм: {tf}")

    now = int(time.time() * 1000)
    seconds_per_bar = {'15min': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (limit * seconds_per_bar[tf] * 1000)

    d = ctrader_service.get_trendbars(
        symbol_id=symbol_details['symbolId'],
        period=tf_map[tf],
        from_timestamp=from_ts,
        to_timestamp=now
    )

    def process_response(response):
        trendbars_response = response
        if not trendbars_response.trendbar:
            return pd.DataFrame()
        
        divisor = 10**symbol_details['digits']
        bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                 'open': (bar.low + bar.deltaOpen) / divisor,
                 'high': (bar.low + bar.deltaHigh) / divisor,
                 'low': bar.low / divisor,
                 'close': (bar.low + bar.deltaClose) / divisor,
                 'volume': bar.volume} for bar in trendbars_response.trendbar]
        
        df = pd.DataFrame(bars)
        if df.empty: return df
        df = df.sort_values(by='ts').reset_index(drop=True).tail(limit)
        MARKET_DATA_CACHE[key] = df
        return df

    return d.addCallback(process_response)

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(close=df['close'], length=14, append=True, col_names=('RSI',))
    df.ta.kama(close=df['close'], length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    current_price = float(last['close'])
    
    lows = daily_df['low'].tail(30)
    highs = daily_df['high'].tail(30)
    support = lows[lows < current_price].max()
    resistance = highs[highs > current_price].min()
    support = float(support) if pd.notna(support) else None
    resistance = float(resistance) if pd.notna(resistance) else None

    score, reasons = 50, []
    if current_price > last['KAMA']: score += 15; reasons.append("Ціна вище лінії KAMA(14)")
    else: score -= 15; reasons.append("Ціна нижче лінії KAMA(14)")
    if last['RSI'] < 30: score += 20; reasons.append("RSI в зоні перепроданості (<30)")
    elif last['RSI'] > 70: score -= 20; reasons.append("RSI в зоні перекупленості (>70)")
    
    score = int(np.clip(score, 0, 100))
    return { "score": score, "reasons": reasons, "support": support, "resistance": resistance, "price": current_price }

def _generate_verdict(analysis):
    score = analysis['score']
    if score > 65: return "⬆️ Сильний сигнал: КУПУВАТИ", "strong_buy"
    if score > 55: return "↗️ Помірний сигнал: КУПУВАТИ", "moderate_buy"
    if score < 35: return "⬇️ Сильний сигнал: ПРОДАВАТИ", "strong_sell"
    if score < 45: return "↘️ Помірний сигнал: ПРОДАВАТИ", "moderate_sell"
    return "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ", "neutral"

def get_api_detailed_signal_data(ctrader_service, pair, user_id=None):
    # --- ВИПРАВЛЕННЯ: Додано валідацію назви пари ---
    if not isinstance(pair, str) or len(pair) < 3:
        return {"error": f"Некоректна назва пари: '{pair}'. Очікується рядок."}

    def on_data_ready(results):
        df, daily_df = results
        if df.empty or len(df) < 25 or daily_df.empty:
            return {"error": "Недостатньо історичних даних для аналізу."}

        analysis_result = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis_result)

        if user_id:
            add_signal_to_history({
                'user_id': user_id, 
                'pair': pair, 
                'price': analysis_result['price'], 
                'bull_percentage': analysis_result['score']
            })
        
        history_df = df.tail(50)
        history = { 
            "dates": history_df['ts'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), 
            "open": history_df['open'].tolist(), "high": history_df['high'].tolist(), 
            "low": history_df['low'].tolist(), "close": history_df['close'].tolist() 
        }
        
        return { 
            "pair": pair, "price": analysis_result['price'], "verdict_text": verdict_text, 
            "verdict_level": verdict_level, "reasons": analysis_result['reasons'], 
            "support": analysis_result['support'], "resistance": analysis_result['resistance'], 
            "history": history 
        }

    d1 = get_market_data(ctrader_service, pair, '15min', 100)
    d2 = get_market_data(ctrader_service, pair, '1day', 100)
    d_list = reactor.defer.DeferredList([d1, d2], consumeErrors=True)
    d_list.addCallback(lambda results: on_data_ready([res[1] for res in results]))
    return d_list

def get_api_mta_data(ctrader_service, pair):
    def get_single_tf_signal(tf):
        d = get_market_data(ctrader_service, pair, tf, 200)
        def on_df_ready(df):
            if df.empty or len(df) < 55: return None
            df.ta.ema(close=df['close'], length=21, append=True, col_names=('EMA_fast',))
            df.ta.ema(close=df['close'], length=55, append=True, col_names=('EMA_slow',))
            signal = "BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "SELL"
            return {"tf": tf, "signal": signal}
        return d.addCallback(on_df_ready)

    deferreds = [get_single_tf_signal(tf) for tf in ANALYSIS_TIMEFRAMES]
    d_list = reactor.defer.DeferredList(deferreds, consumeErrors=True)

    def on_all_ready(results):
        valid_results = [res[1] for res in results if res[0] and res[1] is not None]
        valid_results.sort(key=lambda x: ANALYSIS_TIMEFRAMES.index(x['tf']))
        return valid_results
        
    return d_list.addCallback(on_all_ready)