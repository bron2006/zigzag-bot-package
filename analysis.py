# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES

# --- ПОЧАТОК ЗМІН ---
# Створюємо єдиний, глобальний пул потоків для всього модуля.
# Це дозволяє уникнути створення нових потоків при кожному запиті,
# що є причиною помилок "Out of Memory" на сервері.
# Ми обираємо 4 воркери як компроміс між швидкістю та використанням ресурсів.
EXECUTOR = ThreadPoolExecutor(max_workers=4)
# --- КІНЕЦЬ ЗМІН ---


# ------------------- FUNCTIONS -------------------
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
        pattern_name = found_patterns.index[0]
        signal_strength = found_patterns.iloc[0]
        simple_name = pattern_name.replace("CDL_", "")
        
        pattern_type = 'neutral'
        if signal_strength > 0: pattern_type = 'bullish'
        elif signal_strength < 0: pattern_type = 'bearish'

        text = f'⏳ Нейтральний патерн: "{simple_name}" (невизначеність)'
        if pattern_type == 'bullish':
            text = f'✅ Бичачий патерн: "{simple_name}" (ріст ⬆️)'
        elif pattern_type == 'bearish':
            text = f'❌ Ведмежий патерн: "{simple_name}" (падіння ⬇️)'
            
        return {'name': simple_name, 'type': pattern_type, 'text': text}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}")
        return None

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
            td_tf = tf
            if td_tf.endswith('m'): td_tf = td_tf.replace('m', 'min')
            elif td_tf.endswith('h'): td_tf = td_tf.replace('h', 'hour')
            elif td_tf == '1d': td_tf = '1day'
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}).reset_index()
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def rank_crypto_chunk(pairs_chunk):
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
            
    # --- ПОЧАТОК ЗМІН ---
    # Використовуємо глобальний EXECUTOR замість створення нового.
    # Забираємо конструкцію "with".
    results = EXECUTOR.map(fetch_score, pairs_chunk)
    # --- КІНЕЦЬ ЗМІН ---
    
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

def get_signal_strength_verdict(pair, display_name, asset):
    df = get_market_data(pair, '1m', asset, limit=50)
    if df.empty or len(df) < 2:
        return f"⚠️ Недостатньо даних для 1-хв аналізу *{display_name}*."
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=21, append=True)
        
        daily_df = get_market_data(pair, '1d', asset, limit=30)
        support_levels, resistance_levels = [], []
        if not daily_df.empty:
            support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
        
        current_price = df.iloc[-1]['Close']
        is_near_support = any(abs(current_price - sl) / current_price < 0.005 for sl in support_levels)
        is_near_resistance = any(abs(current_price - rl) / current_price < 0.005 for rl in resistance_levels)
            
        candle_pattern = analyze_candle_patterns(df)

        last = df.iloc[-1]
        score = 50
        reasons = []
        
        if last['Close'] > last['EMA_21']: score += 10; reasons.append("ціна вище EMA(21)")
        else: score -= 10; reasons.append("ціна нижче EMA(21)")
        
        rsi = last['RSI_14']
        if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
        elif rsi > 70: score -= 15; reasons.append("RSI в золі перекупленості")
        
        if is_near_support: score += 10; reasons.append("ціна біля підтримки")
        elif is_near_resistance: score -= 10; reasons.append("ціна біля опору")
        
        if candle_pattern and candle_pattern['type'] == 'neutral':
            score = (score + 50) / 2
        
        score = np.clip(score, 0, 100)
        bull_percentage, bear_percentage = int(score), 100 - int(score)
        
        strength_line = f"🐂 Бики {bull_percentage}% ⬆️\n🐃 Ведмеді {bear_percentage}% ⬇️"
        reason_line = f"Підстава: {', '.join(reasons)}." if reasons else "Змішані сигнали."
        disclaimer = "\n\n_⚠️ Це не фінансова порада._"
        
        sr_info = ""
        if not support_levels and not resistance_levels:
            sr_info = "⚠️ Не вдалося отримати рівні S/R"
        else:
            nearest_support = min(support_levels, key=lambda x: abs(x - current_price)) if support_levels else 'N/A'
            nearest_resistance = min(resistance_levels, key=lambda x: abs(x - current_price)) if resistance_levels else 'N/A'
            sr_info = f"Підтримка: `{nearest_support:.4f}` | Опір: `{nearest_resistance:.4f}`"

        confluence_header = ""
        if bull_percentage >= 80 and candle_pattern and candle_pattern['type'] == 'bullish':
            confluence_header = "🚀 **СИЛЬНИЙ СИГНАЛ ВГОРУ!**\n*Виявлено збіг кількох бичачих індикаторів.*\n\n"
        elif bear_percentage >= 80 and candle_pattern and candle_pattern['type'] == 'bearish':
            confluence_header = "📉 **СИЛЬНИЙ СИГНАЛ ВНИЗ!**\n*Виявлено збіг кількох ведмежих індикаторів.*\n\n"
        
        final_message = (f"{confluence_header}"
                         f"**🕯️ Індекс сили ринку (1хв):** *{display_name}*\n"
                         f"**Поточна ціна:** `{last['Close']:.4f}`\n\n"
                         f"**Баланс сил:**\n{strength_line}\n\n"
                         f"**Рівні S/R (денні):**\n{sr_info}\n\n")

        if candle_pattern:
            final_message += f"**Свічковий патерн:**\n{candle_pattern['text']}\n\n"
        
        final_message += f"_{reason_line}_{disclaimer}"
        
        return final_message
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*."

def get_full_mta_verdict(pair, display_name, asset):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200)
        if df.empty or len(df) < 55: return (tf, None)
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        sig = "✅ BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "❌ SELL"
        return (tf, sig)

    # --- ПОЧАТОК ЗМІН ---
    # Використовуємо глобальний EXECUTOR замість створення нового.
    # Забираємо конструкцію "with".
    results = EXECUTOR.map(worker, ANALYSIS_TIMEFRAMES)
    # --- КІНЕЦЬ ЗМІН ---

    rows = [r for r in results if r[1] is not None]
    table = "\n".join([f"| {tf:<4} | {sig} |" for tf, sig in rows])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n| ТФ   | Сигнал |\n|:----:|:---:|\n{table}"