# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import requests
from concurrent.futures import ThreadPoolExecutor

# --- ПОЧАТОК ЗМІН: Оновлюємо імпорти ---
from db import add_signal_to_history
from config import logger, binance, FINNHUB_API_KEY, MARKET_DATA_CACHE, RANKING_CACHE, ANALYSIS_TIMEFRAMES
from ctrader_api import get_trendbars, get_valid_access_token
# --- КІНЕЦЬ ЗМІН ---

_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

# --- ПОЧАТОК ЗМІН: Повністю переписана функція get_market_data ---
def get_market_data(pair, tf, asset, limit=300, force_refresh=False):
    key = f"{pair}_{tf}_{limit}"
    # Для Forex кешування не використовується, щоб дані завжди були свіжими
    use_cache = asset == 'crypto'
    if use_cache and not force_refresh and key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]

    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)

        elif asset == 'forex':
            # Використовуємо user_id за замовчуванням для системних запитів
            user_id = 12345
            access_token = get_valid_access_token(user_id)
            if not access_token:
                logger.error(f"Не вдалося отримати/оновити токен cTrader для {pair}.")
                return pd.DataFrame()
            df = get_trendbars(access_token, pair, tf, limit)

        elif asset == 'stocks':
            finnhub_tf_map = {'15min': '15', '1h': '60', '4h': 'D', '1day': 'D'}
            resolution = finnhub_tf_map.get(tf, 'D') # 'D' як значення за замовчуванням
            
            # Розрахунок часу для Finnhub
            to_ts = int(time.time())
            # Приблизний розрахунок початкового часу
            if resolution == 'D':
                 from_ts = to_ts - (limit * 24 * 3600)
            else:
                 from_ts = to_ts - (limit * int(resolution) * 60)

            api_url = f"https://finnhub.io/api/v1/stock/candle?symbol={pair}&resolution={resolution}&from={from_ts}&to={to_ts}&token={FINNHUB_API_KEY}"
            
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            data = response.json()

            if data.get('s') == 'ok' and 't' in data and data['t']:
                df = pd.DataFrame({
                    'ts': pd.to_datetime(data['t'], unit='s', utc=True),
                    'Open': data['o'],
                    'High': data['h'],
                    'Low': data['l'],
                    'Close': data['c'],
                    'Volume': data['v']
                })
            else:
                logger.warning(f"Finnhub не повернув даних для {pair} з резолюцією {resolution}. Status: {data.get('s')}")
                return pd.DataFrame()

        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        
        if use_cache:
            MARKET_DATA_CACHE[key] = df
        return df

    except Exception as e:
        # Логуємо помилку з деталями
        logger.error(f"Помилка отримання даних для {pair} (asset: {asset}, tf: {tf}): {e}")
        return pd.DataFrame()
# --- КІНЕЦЬ ЗМІН ---


# ... (решта файлу analysis.py залишається без змін) ...
def _format_price(price):
    if price >= 10:
        return f"{price:.2f}"
    if price >= 0.1:
        return f"{price:.4f}"
    return f"{price:.8f}".rstrip('0')

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
        if df.empty or not all(col in df.columns for col in ['Low', 'High']):
            return [], []
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
        df_copy = df.copy()
        candle_patterns = df_copy.ta.cdl_pattern(name="all")
        df_copy = pd.concat([df_copy, candle_patterns], axis=1)
        
        pattern_cols = [col for col in df_copy.columns if col.startswith('CDL_')]
        if not pattern_cols:
            return None
        last_candle = df_copy[pattern_cols].iloc[-1]
        found_patterns = last_candle[last_candle != 0]
        if found_patterns.empty:
            return None
        strongest_pattern = found_patterns.abs().idxmax()
        signal_strength = found_patterns[strongest_pattern]
        
        if abs(signal_strength) == 0:
            return None
            
        pattern_name = strongest_pattern.replace("CDL_", "")
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

def get_signal_strength_verdict(pair, display_name, asset, user_id=None, force_refresh=False):
    # Для основного вердикту використовуємо більш короткий таймфрейм
    main_tf = '15min' if asset in ['crypto', 'stocks'] else '1h'
    
    df = get_market_data(pair, main_tf, asset, limit=100, force_refresh=force_refresh)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для аналізу *{display_name}* на таймфреймі {main_tf}.", None
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100, force_refresh=force_refresh)
        if daily_df.empty:
            return f"⚠️ Не вдалося завантажити денні дані для *{display_name}*, аналіз неможливий.", None

        analysis = _calculate_core_signal(df, daily_df)
        if user_id:
            add_signal_to_history({'user_id': user_id, 'pair': pair, 'price': analysis['price'], 'bull_percentage': analysis['score']})
        verdict_text, _ = _generate_verdict(analysis)
        formatted_price = _format_price(analysis['price'])
        final_message = (f"**{verdict_text}**\n\n"
                         f"*{display_name}* | *Ціна:* `{formatted_price}`\n\n"
                         f"_Це не фінансова порада. Для деталей натисніть кнопки нижче._")
        return final_message, analysis
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}", exc_info=True)
        return f"⚠️ Помилка аналізу *{display_name}*.", None

def get_api_detailed_signal_data(pair):
    asset = 'stocks'
    if '/' in pair:
        asset = 'crypto' if 'USDT' in pair else 'forex'
    
    main_tf = '15min' if asset in ['crypto', 'stocks'] else '1h'
    
    df = get_market_data(pair, main_tf, asset, limit=100)
    if df.empty or len(df) < 25:
        return {"error": f"Недостатньо даних для аналізу на таймфреймі {main_tf}."}
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100)
        if daily_df.empty:
            return {"error": "Не вдалося завантажити денні дані, аналіз неможливий."}
            
        analysis = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis)
        history_df = df.tail(50)
        date_col = 'ts'
        history = { "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), "open": history_df['Open'].tolist(), "high": history_df['High'].tolist(), "low": history_df['Low'].tolist(), "close": history_df['Close'].tolist() }
        return {
            "pair": pair, "price": analysis['price'],
            "verdict_text": verdict_text,
            "verdict_level": verdict_level,
            "reasons": analysis['reasons'], "support": analysis['support'], "resistance": analysis['resistance'],
            "candle_pattern": analysis['candle_pattern'], "volume_analysis": analysis['volume_info'], "history": history
        }
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}", exc_info=True)
        return {"error": str(e)}

def get_full_mta_verdict(pair, display_name, asset, force_refresh=False):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=100, force_refresh=force_refresh)
        if df.empty or len(df) < 25: return (tf, None)
        try:
            df.ta.rsi(length=14, append=True, col_names=('RSI',))
            last_rsi = df.iloc[-1]['RSI']
            if pd.isna(last_rsi): return (tf, "⚪️ Н/Д")
            if last_rsi > 65: sig = "🔴 Продавати"
            elif last_rsi < 35: sig = "🟢 Купувати"
            else: sig = "🟡 Нейтрально"
            return (tf, sig)
        except Exception:
            return (tf, "⚪️ Помилка")

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
        df = get_market_data(pair, tf, asset, limit=100)
        if df.empty or len(df) < 25: return {"tf": tf, "signal": "N/A"}
        try:
            df.ta.rsi(length=14, append=True, col_names=('RSI',))
            last_rsi = df.iloc[-1]['RSI']
            if pd.isna(last_rsi): return {"tf": tf, "signal": "N/A"}
            if last_rsi > 65: signal = "SELL"
            elif last_rsi < 35: signal = "BUY"
            else: signal = "NEUTRAL"
            return {"tf": tf, "signal": signal}
        except Exception:
            return {"tf": tf, "signal": "Error"}

    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    mta_data = [r for r in results if r is not None]
    return mta_data

def rank_assets_for_api(pairs, asset_type):
    cache_key = f"ranking_{asset_type}"
    if cache_key in RANKING_CACHE:
        return RANKING_CACHE[cache_key]

    def worker(pair):
        df = get_market_data(pair, '1h', asset_type, limit=50)
        if df.empty or len(df) < 25:
            return {'ticker': pair, 'score': -1}
        try:
            df.ta.rsi(length=14, append=True, col_names=('RSI',))
            last_rsi = df.iloc[-1]['RSI']
            if pd.isna(last_rsi):
                return {'ticker': pair, 'score': -1}
            # Оцінка від 0 до 100, де 100 - найсильніший сигнал до покупки/продажу
            score = abs(50 - last_rsi) * 2
            return {'ticker': pair, 'score': score}
        except Exception:
            return {'ticker': pair, 'score': -1}

    executor = get_executor()
    results = list(executor.map(worker, pairs))
    
    # Сортуємо за "цікавістю" (найбільш далекі від нейтрального RSI)
    final_ranking = sorted(results, key=lambda x: x['score'], reverse=True)
    
    RANKING_CACHE[cache_key] = final_ranking
    return final_ranking