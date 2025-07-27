# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES

# Використовуємо ліниву ініціалізацію для стабільності
_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

def get_market_data(pair, tf, asset, limit=300):
    key = f"{pair}_{tf}_{limit}"
    if key in CACHE: return CACHE[key]
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
        elif asset in ('forex', 'stocks'):
            td_tf = tf.replace('m', 'min').replace('h', 'hour') if tf != '1d' else '1day'
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}).reset_index()
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

        signal_strength = found_patterns.iloc[0]
        # --- ПОКРАЩЕННЯ 1: Фільтруємо слабкі патерни ---
        if abs(signal_strength) < 100:
            return None

        pattern_name = found_patterns.index[0].replace("CDL_", "")
        pattern_type = 'bullish' if signal_strength > 0 else 'bearish'
        arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
        text = f'{arrow} {pattern_name}'
        return {'name': pattern_name, 'type': pattern_type, 'text': text}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}")
        return None

def analyze_volume(df):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних"
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    last = df.iloc[-1]
    if pd.isna(last['Volume_MA']): return "Недостатньо даних"

    if last['Volume'] > last['Volume_MA'] * 1.5:
        return "🟢 Підвищений об'єм"
    # --- ПОКРАЩЕННЯ 3: Виявляємо аномально низький об'єм ---
    elif last['Volume'] < last['Volume_MA'] * 0.5:
        return "🧊 Аномально низький об'єм"
    return "Об'єм нейтральний"

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.kama(length=14, append=True, col_names=('KAMA',))
    
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']):
        raise ValueError("Помилка розрахунку індикаторів")

    current_price = float(last['Close'])
    support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
    candle_pattern = analyze_candle_patterns(df)
    volume_info = analyze_volume(df)
    
    score = 50
    reasons = []

    # Аналіз KAMA
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    
    # Аналіз RSI
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
    
    # --- ПОКРАЩЕННЯ 2: Більш точна оцінка S/R ---
    if support_levels:
        dist_to_support = min(abs(current_price - sl) for sl in support_levels)
        if dist_to_support / current_price < 0.003:
            score += 15; reasons.append("Ціна ДУЖЕ близько до підтримки")
    
    if resistance_levels:
        dist_to_resistance = min(abs(current_price - rl) for rl in resistance_levels)
        if dist_to_resistance / current_price < 0.003:
            score -= 15; reasons.append("Ціна ДУЖЕ близько до опору")

    # --- ПОКРАЩЕННЯ 3: Зменшуємо впевненість при низькому об'ємі ---
    if "Аномально низький" in volume_info:
        score = np.clip(score, 25, 75)
        reasons.append("Низький об'єм!")

    score = int(np.clip(score, 0, 100))
    support = min(support_levels, key=lambda x: abs(x - current_price)) if support_levels else None
    resistance = min(resistance_levels, key=lambda x: abs(x - current_price)) if resistance_levels else None

    return {
        "score": score, "reasons": reasons, "support": support, "resistance": resistance,
        "candle_pattern": candle_pattern, "volume_info": volume_info, "price": current_price
    }

def get_signal_strength_verdict(pair, display_name, asset):
    df = get_market_data(pair, '1m', asset, limit=50)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для 1-хв аналізу *{display_name}*."
    try:
        daily_df = get_market_data(pair, '1d', asset, limit=30)
        analysis = _calculate_core_signal(df, daily_df)
        
        bull_percentage = analysis['score']
        bear_percentage = 100 - bull_percentage
        direction_arrow = "⬆️" if bull_percentage >= 50 else "⬇️"
        strength_line = f"🐂 Бики {bull_percentage}% ⬆️\n🐃 Ведмеді {bear_percentage}% ⬇️"
        reason_line = f"Підстава: {', '.join(analysis['reasons'])}." if analysis['reasons'] else "Змішані сигнали."
        disclaimer = "\n\n_⚠️ Це не фінансова порада._"
        sr_info = "Рівні не визначені"
        if analysis['support'] or analysis['resistance']:
            sr_parts = []
            if analysis['support']: sr_parts.append(f"Підтримка: `{analysis['support']:.4f}`")
            if analysis['resistance']: sr_parts.append(f"Опір: `{analysis['resistance']:.4f}`")
            sr_info = " | ".join(sr_parts)

        final_message = f"{direction_arrow}\n\n"
        final_message += (f"**🕯️ Індекс сили ринку (1хв):** *{display_name}*\n"
                         f"**Поточна ціна:** `{analysis['price']:.4f}`\n\n"
                         f"**Баланс сил:**\n{strength_line}\n\n")
        if analysis['candle_pattern']:
            final_message += f"**Свічковий патерн:**\n{analysis['candle_pattern']['text']}\n\n"
        final_message += f"**Рівні S/R (денні):**\n{sr_info}\n\n"
        final_message += f"**Аналіз об'єму:**\n{analysis['volume_info']}\n\n"
        final_message += f"_{reason_line}_{disclaimer}"
        return final_message
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*."

def get_api_detailed_signal_data(pair):
    asset = 'stocks'
    if '/' in pair:
        asset = 'crypto' if 'USDT' in pair else 'forex'
    
    df = get_market_data(pair, '1m', asset, limit=100)
    if df.empty or len(df) < 25:
        return {"error": "Недостатньо даних для аналізу."}
    try:
        daily_df = get_market_data(pair, '1d', asset, limit=100)
        analysis = _calculate_core_signal(df, daily_df)
        score = analysis['score']
        
        history_df = df.tail(50)
        date_col = 'ts' if 'ts' in history_df.columns else 'datetime'
        history = {
            "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            "open": history_df['Open'].tolist(), "high": history_df['High'].tolist(),
            "low": history_df['Low'].tolist(), "close": history_df['Close'].tolist()
        }
        return {
            "pair": pair, "price": analysis['price'], "bull_percentage": score,
            "bear_percentage": 100 - score, "reasons": analysis['reasons'], 
            "support": analysis['support'], "resistance": analysis['resistance'],
            "candle_pattern": analysis['candle_pattern'],
            "volume_analysis": analysis['volume_info'],
            "history": history
        }
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}")
        return {"error": str(e)}

# --- Решта функцій залишається без змін ---

def rank_crypto_chunk(pairs_chunk):
    # Ця функція використовує стару логіку ThreadPoolExecutor, яку потрібно оновити
    def fetch_score(pair):
        try:
            df = get_market_data(pair, '1h', 'crypto', limit=50)
            if df.empty: return None
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            return {'display_name': pair, 'ticker': pair, 'score': abs(rsi - 50)}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати пару {pair}: {e}")
            return None
    executor = get_executor()
    results = executor.map(fetch_score, pairs_chunk)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

def get_full_mta_verdict(pair, display_name, asset):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200)
        if df.empty or len(df) < 55: return (tf, None)
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        sig = "✅ BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "❌ SELL"
        return (tf, sig)
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    rows = [r for r in results if r[1] is not None]
    table = "\n".join([f"| {tf:<4} | {sig} |" for tf, sig in rows])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n| ТФ   | Сигнал |\n|:----:|:---:|\n{table}"

def rank_assets_for_api(pairs, asset_type):
    def fetch_score(pair):
        try:
            timeframe = '1h' if asset_type == 'crypto' else '15min'
            df = get_market_data(pair, timeframe, asset_type, limit=50)
            if df.empty: return None
            date_col = 'datetime' if 'datetime' in df.columns else 'ts'
            if date_col not in df.columns: return None
            last_update_time = df[date_col].iloc[-1]
            if datetime.now(timezone.utc) - last_update_time > timedelta(hours=4): return None
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            score = abs(rsi - 50)
            return {'ticker': pair, 'score': score}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати активність {pair}: {e}")
            return None
    executor = get_executor()
    results = executor.map(fetch_score, pairs)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

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
    executor = get_executor()
    results = ex.map(worker, ANALYSIS_TIMEFRAMES)
    mta_data = [r for r in results if r is not None]
    return mta_data