# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from db import add_signal_to_history
from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES

_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

def get_market_data(pair, tf, asset, limit=300, force_refresh=False):
    key = f"{pair}_{tf}_{limit}"
    if not force_refresh and key in CACHE:
        return CACHE[key]
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
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
    if support_levels:
        dist_to_support = min(abs(current_price - sl) for sl in support_levels)
        if dist_to_support / current_price < 0.003:
            score += 15; reasons.append("Ціна ДУЖЕ близько до підтримки")
    if resistance_levels:
        dist_to_resistance = min(abs(current_price - rl) for rl in resistance_levels)
        if dist_to_resistance / current_price < 0.003:
            score -= 15; reasons.append("Ціна ДУЖЕ близько до опору")
    
    if "Аномально низький" in volume_info:
        score = np.clip(score, 25, 75)
        reasons.append("Низький об'єм!")
    
    score = int(np.clip(score, 0, 100))
    support = min(support_levels, key=lambda x: abs(x - current_price)) if support_levels else None
    resistance = min(resistance_levels, key=lambda x: abs(x - current_price)) if resistance_levels else None
    return { "score": score, "reasons": reasons, "support": support, "resistance": resistance, "candle_pattern": candle_pattern, "volume_info": volume_info, "price": current_price }

# --- ПОЧАТОК ЗМІН: Нова єдина функція для генерації вердикту ---
def _generate_verdict(analysis):
    score = analysis['score']
    reasons = analysis['reasons']
    
    active_factors = 0
    if "RSI" in "".join(reasons): active_factors += 1
    if "підтримки" in "".join(reasons): active_factors += 1
    if "опору" in "".join(reasons): active_factors += 1
    if analysis.get("candle_pattern"): active_factors += 1
    active_factors += 1
    if analysis.get("volume_info") and "нейтральний" not in analysis['volume_info'].lower():
        active_factors += 1
            
    verdict_text = "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ"
    verdict_level = "neutral" 

    is_low_volume = "Низький об'єм!" in reasons

    if is_low_volume:
        verdict_text = "⚪️ НЕПЕРЕДБАЧУВАНИЙ РИНОК (Низький об'єм)"
        verdict_level = "unpredictable"
    else:
        if score > 55:
            if active_factors >= 4:
                verdict_text = "⬆️ Сильний сигнал: КУПУВАТИ"
                verdict_level = "strong_buy"
            elif active_factors == 3:
                verdict_text = "↗️ Помірний сигнал: КУПУВАТИ"
                verdict_level = "moderate_buy"
            else:
                verdict_text = "🧐 Слабкий сигнал: КУПУВАТИ (Ризиковано)"
                verdict_level = "weak_buy"
        elif score < 45:
            if active_factors >= 4:
                verdict_text = "⬇️ Сильний сигнал: ПРОДАВАТИ"
                verdict_level = "strong_sell"
            elif active_factors == 3:
                verdict_text = "↘️ Помірний сигнал: ПРОДАВАТИ"
                verdict_level = "moderate_sell"
            else:
                verdict_text = "🧐 Слабкий сигнал: ПРОДАВАТИ (Ризиковано)"
                verdict_level = "weak_sell"
    
    return verdict_text, verdict_level
# --- КІНЕЦЬ ЗМІН ---

# --- ПОЧАТОК ЗМІН: get_signal_strength_verdict тепер використовує новий вердикт ---
def get_signal_strength_verdict(pair, display_name, asset, user_id=None, force_refresh=False):
    df = get_market_data(pair, '1m', asset, limit=100, force_refresh=force_refresh)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для аналізу *{display_name}*.", None
    try:
        daily_df = get_market_data(pair, '1d', asset, limit=100, force_refresh=force_refresh)
        analysis = _calculate_core_signal(df, daily_df)
        
        if user_id:
            add_signal_to_history({'user_id': user_id, 'pair': pair, 'price': analysis['price'], 'bull_percentage': analysis['score']})

        verdict_text, _ = _generate_verdict(analysis)
        
        final_message = (f"**{verdict_text}**\n\n"
                         f"*{display_name}* | *Ціна:* `{analysis['price']:.4f}`\n\n"
                         f"_Це не фінансова порада. Для деталей натисніть кнопки нижче._")
        
        return final_message, analysis

    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*.", None
# --- КІНЕЦЬ ЗМІН ---

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
        
        verdict_text, verdict_level = _generate_verdict(analysis)

        history_df = df.tail(50)
        date_col = 'ts' if 'ts' in history_df.columns else 'datetime'
        history = { "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), "open": history_df['Open'].tolist(), "high": history_df['High'].tolist(), "low": history_df['Low'].tolist(), "close": history_df['Close'].tolist() }

        return {
            "pair": pair, "price": analysis['price'],
            "verdict_text": verdict_text,
            "verdict_level": verdict_level,
            "reasons": analysis['reasons'], "support": analysis['support'], "resistance": analysis['resistance'],
            "candle_pattern": analysis['candle_pattern'], "volume_analysis": analysis['volume_info'], "history": history
        }

    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}")
        return {"error": str(e)}

def get_full_mta_verdict(pair, display_name, asset, force_refresh=False):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200, force_refresh=force_refresh)
        if df.empty or len(df) < 55: return (tf, None)
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        sig = "✅ BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "❌ SELL"
        return (tf, sig)
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    rows_data = [r for r in results if r[1] is not None]
    if not rows_data:
        return f"**📊 Детальний огляд тренду:** *{display_name}*\n\nНе вдалося згенерувати жодного сигналу."
    report_lines = []
    for tf, sig in rows_data:
        report_lines.append(f"• *{tf}:* {sig}")
    report = "\n".join(report_lines)
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n{report}"


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
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    mta_data = [r for r in results if r is not None]
    return mta_data

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
    executor = get_executor()
    results = executor.map(fetch_score, pairs_chunk)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

# --- ПОЧАТОК ЗМІН: Виправлено фільтр для закритих ринків ---
def rank_assets_for_api(pairs, asset_type):
    def fetch_score(pair):
        try:
            timeframe = '1h' if asset_type == 'crypto' else '15min'
            df = get_market_data(pair, timeframe, asset_type, limit=50)
            if df.empty: return None
            if asset_type in ('stocks', 'forex'):
                date_col = 'datetime' if 'datetime' in df.columns else 'ts'
                if date_col not in df.columns: return None
                last_update_time = df[date_col].iloc[-1]
                # Змінюємо 4 години на 26, щоб врахувати закриття ринків
                if pd.Timestamp.now(tz='UTC') - last_update_time > timedelta(hours=26):
                    return None
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
# --- КІНЕЦЬ ЗМІН ---