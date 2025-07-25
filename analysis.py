# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from datetime import datetime, timedelta, timezone
from threading import Semaphore
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES, CRYPTO_PAIRS_FULL, STOCK_TICKERS, FOREX_PAIRS_MAP

# --- Кеш для API-ранкінгу та throttle ---
RANK_CACHE = {}
THROTTLE_SEMAPHORE = Semaphore(1)

def get_market_data(pair, tf, asset, limit=300):
    key = f"{pair}_{tf}_{limit}"
    if key in CACHE:
        return CACHE[key]
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'}, inplace=True)
        elif asset in ('forex', 'stocks'):
            td_tf = tf.replace('m', 'min').replace('h', 'hour') if 'm' in tf or 'h' in tf else '1day'
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}, inplace=True)
                df.reset_index(inplace=True)
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('UTC')
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def group_close_values(values, threshold=0.01):
    if not len(values): return []
    values = sorted(values)
    groups, current_group = [], [values[0]]
    for value in values[1:]:
        if value - current_group[-1] <= threshold * value:
            current_group.append(value)
        else:
            groups.append(np.mean(current_group))
            current_group = [value]
    groups.append(np.mean(current_group))
    return groups

def identify_support_resistance_levels(df, window=20, threshold=0.01):
    try:
        lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
        highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
        support_levels = group_close_values(df.loc[df['Low'] == lows, 'Low'].tolist(), threshold)
        resistance_levels = group_close_values(df.loc[df['High'] == highs, 'High'].tolist(), threshold)
        return sorted(support_levels), sorted(resistance_levels, reverse=True)
    except Exception as e:
        logger.error(f"Помилка в identify_support_resistance_levels: {e}")
        return [], []

def analyze_candle_patterns(df: pd.DataFrame):
    try:
        patterns = df.ta.cdl_pattern(name="all")
        if patterns.empty: return None
        last_candle = patterns.iloc[-1]
        found_patterns = last_candle[last_candle != 0]
        if found_patterns.empty: return None
        pattern_name = found_patterns.index[0].replace("CDL_", "")
        signal_strength = found_patterns.iloc[0]
        pattern_type = 'bullish' if signal_strength > 0 else 'bearish'
        arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
        return {'name': pattern_name, 'type': pattern_type, 'text': f'{arrow} {pattern_name}'}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}")
        return None

def analyze_volume(df):
    if df.empty or 'Volume' not in df.columns or len(df) < 21:
        return "Недостатньо даних", 0
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    last = df.iloc[-1]
    if pd.isna(last['Volume_MA']):
        return "Недостатньо даних", 0
    if last['Volume'] > last['Volume_MA'] * 1.5:
        if last['Close'] > last['Open']:
            return "🟢 Підвищений об'єм на зростанні", 5
        else:
            return "🔴 Підвищений об'єм на падінні", -5
    return "Об'єм нейтральний", 0

def get_signal_strength_verdict(pair, display_name, asset):
    # Ця функція залишається для роботи бота в Telegram
    return f"Аналіз для {display_name}..."

def get_full_mta_verdict(pair, display_name, asset):
    # Ця функція залишається для роботи бота в Telegram
    return f"MTA для {display_name}..."

def rank_crypto_chunk(pairs_chunk):
    # Ця функція залишається для роботи бота в Telegram
    return rank_assets_for_api(pairs_chunk, 'crypto')

def get_api_detailed_signal_data(pair):
    asset = 'stocks'
    if '/' in pair:
        asset = 'crypto' if 'USDT' in pair else 'forex'
    df = get_market_data(pair, '1m', asset, limit=100)
    if df.empty or len(df) < 25:
        return {"error": "Недостатньо даних для аналізу."}
    try:
        df.ta.rsi(length=14, append=True, col_names=('RSI',))
        df.ta.kama(length=14, append=True, col_names=('KAMA',))
        last = df.iloc[-1]
        if pd.isna(last['RSI']) or pd.isna(last['KAMA']):
            return {"error": "Помилка розрахунку індикаторів."}
        current_price = float(last['Close'])
        score = 50
        reasons = []
        if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
        else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
        rsi = float(last['RSI'])
        if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
        elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
        support, resistance = None, None
        daily_df = get_market_data(pair, '1d', asset, limit=100)
        if not daily_df.empty:
            support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
            if support_levels: support = float(min(support_levels, key=lambda x: abs(x - current_price)))
            if resistance_levels: resistance = float(min(resistance_levels, key=lambda x: abs(x - current_price)))
        if support and abs(current_price - support) / current_price < 0.01:
            score += 10; reasons.append("Ціна біля підтримки")
        if resistance and abs(current_price - resistance) / current_price < 0.01:
            score -= 10; reasons.append("Ціна біля опору")
        candle_pattern = analyze_candle_patterns(df)
        volume_info, volume_score_change = analyze_volume(df)
        score += volume_score_change
        score = int(np.clip(score, 0, 100))
        history_df = df.tail(50)
        date_col = 'ts' if 'ts' in history_df.columns else 'datetime'
        history = {
            "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            "open": history_df['Open'].tolist(),
            "high": history_df['High'].tolist(),
            "low": history_df['Low'].tolist(),
            "close": history_df['Close'].tolist()
        }
        return {
            "pair": pair, "price": current_price, "bull_percentage": score,
            "bear_percentage": 100 - score, "reasons": reasons, "support": support,
            "resistance": resistance, "candle_pattern": candle_pattern,
            "volume_analysis": volume_info, "history": history
        }
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}")
        return {"error": str(e)}

def get_api_mta_data(pair, asset):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200)
        if df.empty or len(df) < 55: return None
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        last_row = df.iloc[-1]
        if pd.isna(last_row['EMA_fast']) or pd.isna(last_row['EMA_slow']): return None
        signal = "BUY" if last_row['EMA_fast'] > last_row['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = ex.map(worker, ANALYSIS_TIMEFRAMES)
    return [r for r in results if r]

def rank_assets_for_api(pairs, asset_type):
    cache_key = f"{asset_type}_{hash(tuple(pairs))}"
    now = time.time()
    if cache_key in RANK_CACHE:
        cached_time, cached_result = RANK_CACHE[cache_key]
        if now - cached_time < 180:
            return cached_result

    results = []
    if not THROTTLE_SEMAPHORE.acquire(timeout=5):
        logger.warning("rank_assets_for_api: Пропущено через throttle")
        return []

    try:
        for pair in pairs[:20]:
            try:
                timeframe = '1h' if asset_type == 'crypto' else '15min'
                df = get_market_data(pair, timeframe, asset_type, limit=30)
                if df.empty: continue
                if asset_type in ('stocks', 'forex'):
                    col = 'datetime' if 'datetime' in df.columns else 'ts'
                    if col not in df.columns: continue
                    if datetime.now(timezone.utc) - df[col].iloc[-1] > timedelta(hours=4):
                        continue
                rsi = df.ta.rsi(length=14).iloc[-1]
                if pd.isna(rsi): continue
                score = abs(rsi - 50)
                results.append({'ticker': pair, 'score': score})
            except Exception as e:
                logger.error(f"Не вдалося проаналізувати {pair}: {e}")
    finally:
        THROTTLE_SEMAPHORE.release()

    sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)
    RANK_CACHE[cache_key] = (now, sorted_results)
    return sorted_results