# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES, CRYPTO_PAIRS_FULL, STOCK_TICKERS

# ... (всі існуючі функції до get_api_signal_data залишаються без змін) ...

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
    # ... (код цієї функції не змінюється)
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
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = executor.map(fetch_score, pairs_chunk)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

def get_signal_strength_verdict(pair, display_name, asset):
    # ... (код цієї функції не змінюється)
    df = get_market_data(pair, '1m', asset, limit=50)
    if df.empty or len(df) < 2:
        return f"⚠️ Недостатньо даних для 1-хв аналізу *{display_name}*."
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.kama(length=14, append=True, col_names='KAMA')
        daily_df = get_market_data(pair, '1d', asset, limit=30)
        support_levels, resistance_levels = [], []
        if not daily_df.empty:
            support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
        current_price = df.iloc[-1]['Close']
        is_near_support = any(abs(current_price - sl) / current_price < 0.005 for sl in support_levels)
        is_near_resistance = any(abs(current_price - rl) / current_price < 0.005 for rl in resistance_levels)
        candle_pattern = analyze_candle_patterns(df)
        volume_info, volume_score_change = analyze_volume(df)
        last = df.iloc[-1]
        score = 50
        reasons = []
        if last['Close'] > last['KAMA']: 
            score += 10; reasons.append("ціна вище KAMA(14)")
        else: 
            score -= 10; reasons.append("ціна нижче KAMA(14)")
        rsi = last['RSI_14']
        if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
        elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
        if is_near_support: score += 10; reasons.append("ціна біля підтримки")
        elif is_near_resistance: score -= 10; reasons.append("ціна біля опору")
        score += volume_score_change
        warning = None
        if candle_pattern and candle_pattern['type'] == 'neutral':
            score = (score + 50) / 2
            warning = f"⚠️ **Увага:** Знайдено патерн невизначеності ({candle_pattern['name']}). Ризик підвищений."
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
        final_message = f"{confluence_header}"
        if warning:
            final_message += f"{warning}\n\n"
        final_message += (f"**🕯️ Індекс сили ринку (1хв):** *{display_name}*\n"
                         f"**Поточна ціна:** `{last['Close']:.4f}`\n\n"
                         f"**Баланс сил:**\n{strength_line}\n\n"
                         f"**Рівні S/R (денні):**\n{sr_info}\n\n")
        if candle_pattern:
            final_message += f"**Свічковий патерн:**\n{candle_pattern['text']}\n\n"
        if volume_info:
            final_message += f"**Аналіз об'єму:**\n{volume_info}\n\n"
        final_message += f"_{reason_line}_{disclaimer}"
        return final_message
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*."

def get_full_mta_verdict(pair, display_name, asset):
    # ... (код цієї функції не змінюється)
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200)
        if df.empty or len(df) < 55: return (tf, None)
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        sig = "✅ BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "❌ SELL"
        return (tf, sig)
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = ex.map(worker, ANALYSIS_TIMEFRAMES)
    rows = [r for r in results if r[1] is not None]
    table = "\n".join([f"| {tf:<4} | {sig} |" for tf, sig in rows])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n| ТФ   | Сигнал |\n|:----:|:---:|\n{table}"

# --- ПОЧАТОК ЗМІН ---
def get_api_signal_data(pair):
    """Готує дані для відповіді API-запиту від Web App."""
    asset = 'stocks'
    if '/' in pair:
        asset = 'crypto' if 'USDT' in pair else 'forex'
    
    df = get_market_data(pair, '1m', asset, limit=100)
    if df.empty or len(df) < 25: # Збільшили мінімальну довжину для розрахунку індикаторів
        return {"error": "no data"}

    # Явно вказуємо імена колонок для індикаторів
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.ema(length=21, append=True, col_names=('EMA',))
    
    last = df.iloc[-1]

    # Перевіряємо, чи індикатори розрахувалися коректно
    if pd.isna(last['RSI']) or pd.isna(last['EMA']):
        return {"error": "indicator calculation failed"}

    price = last['Close']
    rsi = last['RSI']
    ema_signal = last['Close'] > last['EMA']
    
    signal = "NEUTRAL" # За замовчуванням нейтральний
    if rsi < 35 and ema_signal:
        signal = "BUY"
    elif rsi > 65 and not ema_signal:
        signal = "SELL"
    
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
        "pair": pair, "price": price, "rsi": rsi,
        "ema": ema_signal, "signal": signal, "history": history
    }
# --- КІНЕЦЬ ЗМІН ---

# (Решта функцій, як-от analyze_volume, identify_support_resistance_levels, залишаються без змін)
# Переконайтесь, що решта файлу, якщо там є ще щось, залишається на місці.
# Наприклад, функції analyze_candle_patterns, analyze_volume, identify_support_resistance_levels
# (якщо вони у вас є в цьому файлі) мають залишитися.