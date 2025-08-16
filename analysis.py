# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import time

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history
from config import (
    logger, MARKET_DATA_CACHE, SYMBOL_DATA_CACHE, CACHE_LOCK,
    ANALYSIS_TIMEFRAMES, DEMO_ACCOUNT_ID
)
# --- ЗМІНА ІМПОРТУ ---
from ctrader_prod_service import ctrader_service


def get_market_data(pair, tf, limit=300, force_refresh=False):
    key = f"{pair}_{tf}_{limit}"
    
    with CACHE_LOCK:
        if not force_refresh and key in MARKET_DATA_CACHE:
            return MARKET_DATA_CACHE[key]

    with CACHE_LOCK:
        symbol_details = SYMBOL_DATA_CACHE.get(pair)
    
    if not symbol_details:
        logger.error(f"Деталі для символу {pair} не знайдено в кеші.")
        return pd.DataFrame()

    tf_map = {"1m": TrendbarPeriod.M1, "15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}
    if tf not in tf_map: return pd.DataFrame()

    try:
        now = int(time.time() * 1000)
        seconds_per_bar = {'1m': 60, '15min': 900, '1h': 3600, '4h': 14400, '1day': 86400}
        from_ts = now - (limit * seconds_per_bar[tf] * 1000)
        
        trendbars_response = ctrader_service.get_trendbars(
            symbol_id=symbol_details['symbolId'],
            period=tf_map[tf],
            from_timestamp=from_ts,
            to_timestamp=now
        )
        
        if not trendbars_response.trendbar:
            logger.warning(f"Для {pair} ({tf}) не отримано жодного бару.")
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
        
        with CACHE_LOCK:
            MARKET_DATA_CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання ринкових даних для {pair} ({tf}): {e}", exc_info=True)
        return pd.DataFrame()


def get_api_detailed_signal_data(pair, user_id=None):
    try:
        df = get_market_data(pair, '15min', 100)
        if df.empty or len(df) < 25: return {"error": "Недостатньо історичних даних для аналізу."}
        
        daily_df = get_market_data(pair, '1day', 100)
        analysis = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis)
        
        if user_id:
            add_signal_to_history({
                'user_id': user_id, 
                'pair': pair, 
                'price': analysis['price'], 
                'bull_percentage': analysis['score']
            })
        
        history_df = df.tail(50)
        history = { 
            "dates": history_df['ts'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), 
            "open": history_df['open'].tolist(), "high": history_df['high'].tolist(), 
            "low": history_df['low'].tolist(), "close": history_df['close'].tolist() 
        }
        
        return { 
            "pair": pair, "price": analysis['price'], "verdict_text": verdict_text, 
            "verdict_level": verdict_level, "reasons": analysis['reasons'], 
            "support": analysis['support'], "resistance": analysis['resistance'], 
            "history": history 
        }
    except Exception as e:
        logger.error(f"Помилка в get_api_detailed_signal_data для {pair}: {e}", exc_info=True)
        return {"error": str(e)}

def get_api_mta_data(pair):
    def worker(tf):
        df = get_market_data(pair, tf, 200)
        if df.empty or len(df) < 55: return None
        df.ta.ema(close=df['close'], length=21, append=True, col_names=('EMA_fast',))
        df.ta.ema(close=df['close'], length=55, append=True, col_names=('EMA_slow',))
        signal = "BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}
    
    results = []
    with ThreadPoolExecutor(max_workers=len(ANALYSIS_TIMEFRAMES)) as executor:
        futures = {executor.submit(worker, tf): tf for tf in ANALYSIS_TIMEFRAMES}
        for future in futures:
            result = future.result()
            if result:
                results.append(result)
    
    results.sort(key=lambda x: ANALYSIS_TIMEFRAMES.index(x['tf']))
    return results

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(close=df['close'], length=14, append=True, col_names=('RSI',))
    df.ta.kama(close=df['close'], length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']): raise ValueError("Помилка розрахунку індикаторів")
    
    current_price = float(last['close'])
    support, resistance = _find_sr_levels(daily_df, current_price)
    
    score, reasons = 50, []
    if current_price > last['KAMA']: score += 15; reasons.append("Ціна вище лінії KAMA(14)")
    else: score -= 15; reasons.append("Ціна нижче лінії KAMA(14)")
    if last['RSI'] < 30: score += 20; reasons.append("RSI в зоні перепроданості (<30)")
    elif last['RSI'] > 70: score -= 20; reasons.append("RSI в зоні перекупленості (>70)")
    
    score = int(np.clip(score, 0, 100))
    return { "score": score, "reasons": reasons, "support": support, "resistance": resistance, "price": current_price }

def _find_sr_levels(df, current_price):
    if df.empty or len(df) < 10: return None, None
    lows = df['low'].tail(30)
    highs = df['high'].tail(30)
    support = lows[lows < current_price].max()
    resistance = highs[highs > current_price].min()
    return float(support) if pd.notna(support) else None, float(resistance) if pd.notna(resistance) else None

def _generate_verdict(analysis):
    score = analysis['score']
    if score > 65:
        return "⬆️ Сильний сигнал: КУПУВАТИ", "strong_buy"
    if score > 55:
        return "↗️ Помірний сигнал: КУПУВАТИ", "moderate_buy"
    if score < 35:
        return "⬇️ Сильний сигнал: ПРОДАВАТИ", "strong_sell"
    if score < 45:
        return "↘️ Помірний сигнал: ПРОДАВАТИ", "moderate_sell"
    return "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ", "neutral"