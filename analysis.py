# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import requests
from concurrent.futures import ThreadPoolExecutor

from db import add_signal_to_history
from config import logger, FINNHUB_API_KEY, MARKET_DATA_CACHE, RANKING_CACHE, ANALYSIS_TIMEFRAMES
from ctrader_api import get_valid_access_token
from api_clients import get_binance_client
from ctrader_websocket_client import fetch_trendbars_sync # <-- Наш новий імпорт

_executor = None
def get_executor():
    global _executor
    if _executor is None: _executor = ThreadPoolExecutor(max_workers=2)
    return _executor
    
def get_market_data(pair, tf, asset, limit=300, force_refresh=False):
    key = f"{pair}_{tf}_{limit}"
    use_cache = asset == 'crypto'
    if use_cache and not force_refresh and key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]

    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            binance = get_binance_client()
            if not binance: return pd.DataFrame()
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)

        elif asset == 'forex':
            user_id = 12345
            account_id = 62157581 # <-- ЗАМІНІТЬ НА ID ВАШОГО РЕАЛЬНОГО ДЕМО-РАХУНКУ
            
            symbol_id_map = {"EUR/USD": 1, "GBP/USD": 2, "USD/JPY": 3, "USD/CAD": 4, "AUD/USD": 5, "USD/CHF": 6, "NZD/USD": 7, "EUR/GBP": 8, "EUR/JPY": 9, "CHF/JPY": 48, "EUR/CHF": 49, "GBP/CHF": 50, "USD/MXN": 100, "USD/BRL": 101, "USD/ZAR": 102}
            symbol_id = symbol_id_map.get(pair)
            
            if not symbol_id:
                logger.error(f"Невідомий symbol_id для Forex-пари: {pair}")
                return pd.DataFrame()

            access_token = get_valid_access_token(user_id)
            if not access_token:
                logger.error(f"Не вдалося отримати/оновити токен cTrader для {pair}.")
                return pd.DataFrame()

            df = fetch_trendbars_sync(access_token, account_id, symbol_id, timeframe=tf)

        elif asset == 'stocks':
            finnhub_tf_map = {'15min': '15', '1h': '60', '4h': 'D', '1day': 'D'}
            resolution = finnhub_tf_map.get(tf, 'D')
            to_ts = int(time.time())
            delta_seconds = limit * (int(resolution) * 60 if resolution.isdigit() else 24 * 3600)
            from_ts = to_ts - delta_seconds
            api_url = f"https://finnhub.io/api/v1/stock/candle?symbol={pair}&resolution={resolution}&from={from_ts}&to={to_ts}&token={FINNHUB_API_KEY}"
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            data = response.json()
            if data.get('s') == 'ok' and data.get('t'):
                df = pd.DataFrame({'ts': pd.to_datetime(data['t'], unit='s', utc=True), 'Open': data['o'], 'High': data['h'], 'Low': data['l'], 'Close': data['c'], 'Volume': data['v']})
            else: return pd.DataFrame()

        if df.empty: return pd.DataFrame()
        if use_cache: MARKET_DATA_CACHE[key] = df
        return df

    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} (asset: {asset}, tf: {tf}): {e}", exc_info=True)
        return pd.DataFrame()

# ... (решта коду analysis.py залишається без змін, ви можете скопіювати її з попередніх відповідей) ...
def _format_price(price):
    if price >= 10: return f"{price:.2f}"
    if price >= 0.1: return f"{price:.4f}"
    return f"{price:.8f}".rstrip('0')
def identify_support_resistance_levels(df, window=20, threshold=0.01):
    try:
        if df.empty or not all(col in df.columns for col in ['Low', 'High']): return [], []
        lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
        highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
        support_values = df.loc[df['Low'] == lows, 'Low'].tolist()
        resistance_values = df.loc[df['High'] == highs, 'High'].tolist()
        def group_close_values(values, threshold_ratio=0.01):
            if not values: return []
            values = sorted(list(set(values)))
            groups, current_group = [], [values[0]]
            for val in values[1:]:
                if val <= current_group[-1] * (1 + threshold_ratio): current_group.append(val)
                else: groups.append(np.mean(current_group)); current_group = [val]
            groups.append(np.mean(current_group))
            return groups
        return sorted(group_close_values(support_values)), sorted(group_close_values(resistance_values), reverse=True)
    except Exception as e:
        logger.error(f"Помилка в identify_support_resistance_levels: {e}"); return [], []
def analyze_candle_patterns(df: pd.DataFrame):
    try:
        df_copy, candle_patterns = df.copy(), df.copy().ta.cdl_pattern(name="all")
        if candle_patterns is None or candle_patterns.empty: return None
        pattern_cols = [col for col in candle_patterns.columns if col.startswith('CDL_')]
        if not pattern_cols: return None
        last_candle = candle_patterns[pattern_cols].iloc[-1]
        found_patterns = last_candle[last_candle != 0]
        if found_patterns.empty: return None
        strongest_pattern, signal_strength = found_patterns.abs().idxmax(), found_patterns.max()
        if abs(signal_strength) == 0: return None
        pattern_name, pattern_type = strongest_pattern.replace("CDL_", ""), 'bullish' if signal_strength > 0 else 'bearish'
        arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
        return {'name': pattern_name, 'type': pattern_type, 'text': f'{arrow} {pattern_name}'}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}"); return None
def analyze_volume(df):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних"
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    last = df.iloc[-1]
    if pd.isna(last['Volume_MA']): return "Недостатньо даних"
    if last['Volume'] > last['Volume_MA'] * 1.5: return "🟢 Підвищений об'єм"
    if last['Volume'] < last['Volume_MA'] * 0.5: return "🧊 Аномально низький об'єм"
    return "Об'єм нейтральний"
def _calculate_core_signal(df, daily_df):
    df.ta.rsi(length=14, append=True, col_names=('RSI',)); df.ta.kama(length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']): raise ValueError("Помилка розрахунку індикаторів")
    current_price = float(last['Close'])
    support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
    candle_pattern, volume_info, score, reasons = analyze_candle_patterns(df), analyze_volume(df), 50, []
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
    if support_levels and (min(abs(current_price - s) for s in support_levels) / current_price) < 0.003: score += 15; reasons.append("Ціна ДУЖЕ близько до підтримки")
    if resistance_levels and (min(abs(current_price - r) for r in resistance_levels) / current_price) < 0.003: score -= 15; reasons.append("Ціна ДУЖЕ близько до опору")
    if "Аномально низький" in volume_info: score = np.clip(score, 25, 75); reasons.append("Низький об'єм!")
    score = int(np.clip(score, 0, 100))
    support = min(support_levels, key=lambda x: abs(x - current_price)) if support_levels else None
    resistance = min(resistance_levels, key=lambda x: abs(x - current_price)) if resistance_levels else None
    return {"score": score, "reasons": reasons, "support": support, "resistance": resistance, "candle_pattern": candle_pattern, "volume_info": volume_info, "price": current_price}
def _generate_verdict(analysis):
    score, reasons = analysis['score'], analysis['reasons']
    active_factors = sum(1 for r in ["RSI", "підтримки", "опору"] if r in "".join(reasons)) + (1 if analysis.get("candle_pattern") else 0) + (1 if analysis.get("volume_info") and "нейтральний" not in analysis['volume_info'] else 0)
    if "Низький об'єм!" in reasons: return "⚪️ НЕПЕРЕДБАЧУВАНИЙ РИНОК (Низький об'єм)", "unpredictable"
    if score > 55:
        if active_factors >= 3: return "⬆️ Сильний сигнал: КУПУВАТИ", "strong_buy"
        if active_factors == 2: return "↗️ Помірний сигнал: КУПУВАТИ", "moderate_buy"
        return "🧐 Слабкий сигнал: КУПУВАТИ (Ризиковано)", "weak_buy"
    if score < 45:
        if active_factors >= 3: return "⬇️ Сильний сигнал: ПРОДАВАТИ", "strong_sell"
        if active_factors == 2: return "↘️ Помірний сигнал: ПРОДАВАТИ", "moderate_sell"
        return "🧐 Слабкий сигнал: ПРОДАВАТИ (Ризиковано)", "weak_sell"
    return "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ", "neutral"
def get_signal_strength_verdict(pair, display_name, asset, user_id=None, force_refresh=False):
    main_tf = '15min' if asset in ['crypto', 'stocks'] else '1h'
    df = get_market_data(pair, main_tf, asset, limit=100, force_refresh=force_refresh)
    if df.empty or len(df) < 25: return f"⚠️ Недостатньо даних для аналізу *{display_name}* на ТФ {main_tf}.", None
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100, force_refresh=force_refresh)
        if daily_df.empty: return f"⚠️ Не вдалося завантажити денні дані для *{display_name}*.", None
        analysis = _calculate_core_signal(df, daily_df)
        if user_id: add_signal_to_history({'user_id': user_id, 'pair': pair, 'price': analysis['price'], 'bull_percentage': analysis['score']})
        verdict_text, _ = _generate_verdict(analysis)
        formatted_price = _format_price(analysis['price'])
        return f"**{verdict_text}**\n\n*{display_name}* | *Ціна:* `{formatted_price}`\n\n_Це не фінансова порада._", analysis
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}", exc_info=True)
        return f"⚠️ Помилка аналізу *{display_name}*.", None
def get_api_detailed_signal_data(pair):
    asset = 'stocks' if '/' not in pair else ('crypto' if 'USDT' in pair else 'forex')
    main_tf = '15min' if asset != 'forex' else '1h'
    df = get_market_data(pair, main_tf, asset, limit=100)
    if df.empty or len(df) < 25: return {"error": f"Недостатньо даних на ТФ {main_tf}."}
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100)
        if daily_df.empty: return {"error": "Не вдалося завантажити денні дані."}
        analysis = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis)
        history_df = df.tail(50)
        history = {"dates": history_df['ts'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), "open": history_df['Open'].tolist(), "high": history_df['High'].tolist(), "low": history_df['Low'].tolist(), "close": history_df['Close'].tolist()}
        return {"pair": pair, "price": analysis['price'], "verdict_text": verdict_text, "verdict_level": verdict_level, "reasons": analysis['reasons'], "support": analysis['support'], "resistance": analysis['resistance'], "candle_pattern": analysis['candle_pattern'], "volume_analysis": analysis['volume_info'], "history": history}
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}", exc_info=True); return {"error": str(e)}
def get_full_mta_verdict(pair, display_name, asset, force_refresh=False):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=100, force_refresh=force_refresh)
        if df.empty or len(df) < 25: return tf, "⚪️ Н/Д"
        try:
            df.ta.rsi(length=14, append=True, col_names=('RSI',))
            last_rsi = df.iloc[-1]['RSI']
            if pd.isna(last_rsi): return tf, "⚪️ Н/Д"
            if last_rsi > 65: return tf, "🔴 Продавати"
            if last_rsi < 35: return tf, "🟢 Купувати"
            return tf, "🟡 Нейтрально"
        except Exception: return tf, "⚪️ Помилка"
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    report = "\n".join([f"• *{tf}:* {sig}" for tf, sig in results if sig])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n{report}" if report else f"**📊 Детальний огляд тренду:** *{display_name}*\n\nНе вдалося згенерувати жодного сигналу."
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
        except Exception: return {"tf": tf, "signal": "Error"}
    executor = get_executor()
    return list(executor.map(worker, ANALYSIS_TIMEFRAMES))
def rank_assets_for_api(pairs, asset_type):
    cache_key = f"ranking_{asset_type}"
    if cache_key in RANKING_CACHE: return RANKING_CACHE[cache_key]
    def worker(pair):
        df = get_market_data(pair, '1h', asset_type, limit=50)
        if df.empty or len(df) < 25: return {'ticker': pair, 'score': -1}
        try:
            df.ta.rsi(length=14, append=True, col_names=('RSI',))
            last_rsi = df.iloc[-1]['RSI']
            if pd.isna(last_rsi): return {'ticker': pair, 'score': -1}
            return {'ticker': pair, 'score': abs(50 - last_rsi) * 2}
        except Exception: return {'ticker': pair, 'score': -1}
    executor = get_executor()
    results = sorted(list(executor.map(worker, pairs)), key=lambda x: x['score'], reverse=True)
    RANKING_CACHE[cache_key] = results
    return results