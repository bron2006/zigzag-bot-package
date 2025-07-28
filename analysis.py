# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from db import add_signal_to_history
from config import logger, binance, td, MARKET_DATA_CACHE, RANKING_CACHE, ANALYSIS_TIMEFRAMES

_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

def get_market_data(pair, tf, asset, limit=300, force_refresh=False):
    key = f"{pair}_{tf}_{limit}"
    if not force_refresh and key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
        elif asset in ('forex', 'stocks'):
            td_tf_map = { '1m': '1min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': '1day', '15min': '15min' }
            td_tf = td_tf_map.get(tf)
            if not td_tf:
                logger.error(f"Непідтримуваний таймфрейм для TwelveData: {tf}")
                return pd.DataFrame()
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}).reset_index()
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('UTC')
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        MARKET_DATA_CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def _calculate_core_signal(df, daily_df):
    # ... (код без змін) ...
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

def _format_price(price):
    if price >= 10:
        return f"{price:.2f}"
    if price >= 0.1:
        return f"{price:.4f}"
    return f"{price:.8f}".rstrip('0')

def _generate_verdict(analysis):
    # ... (код без змін) ...
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
    # ... (код без змін) ...
    df = get_market_data(pair, '1m', asset, limit=100, force_refresh=force_refresh)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для аналізу *{display_name}*.", None
    try:
        daily_df = get_market_data(pair, '1d', asset, limit=100, force_refresh=force_refresh)
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
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*.", None

# --- ПОЧАТОК ЗМІН: Додано параметр force_refresh ---
def get_api_detailed_signal_data(pair, force_refresh=False):
    asset = 'stocks'
    if '/' in pair:
        asset = 'crypto' if 'USDT' in pair else 'forex'
    
    df = get_market_data(pair, '1m', asset, limit=100, force_refresh=force_refresh)
    if df.empty or len(df) < 25:
        return {"error": "Недостатньо даних для аналізу."}

    try:
        daily_df = get_market_data(pair, '1d', asset, limit=100, force_refresh=force_refresh)
        # --- КІНЕЦЬ ЗМІН ---
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

def rank_assets_for_api(pairs, asset_type):
    # ... (код без змін) ...
    cache_key = f"ranking_{asset_type}"
    if cache_key in RANKING_CACHE:
        return RANKING_CACHE[cache_key]
    def fetch_score(pair):
        try:
            timeframe = '1h' if asset_type == 'crypto' else '15m'
            df = get_market_data(pair, timeframe, asset_type, limit=50)
            if df.empty or len(df) < 30:
                return {'ticker': pair, 'score': -1}
            if asset_type in ('stocks', 'forex'):
                date_col = 'datetime' if 'datetime' in df.columns else 'ts'
                if date_col not in df.columns: return {'ticker': pair, 'score': -1}
                last_update_time = df[date_col].iloc[-1]
                if pd.Timestamp.utcnow() - last_update_time > timedelta(hours=2):
                    return {'ticker': pair, 'score': -1}
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi):
                return {'ticker': pair, 'score': -1}
            score = abs(rsi - 50)
            return {'ticker': pair, 'score': score}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати активність {pair}: {e}")
            return {'ticker': pair, 'score': -1}
    executor = get_executor()
    results = list(executor.map(fetch_score, pairs))
    active_part = sorted([res for res in results if res['score'] != -1], key=lambda x: x['score'], reverse=True)
    inactive_part = [res for res in results if res['score'] == -1]
    final_ranking = active_part + inactive_part
    RANKING_CACHE[cache_key] = final_ranking
    return final_ranking
# ... (решта файлу без змін) ...