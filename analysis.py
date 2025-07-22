# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES, CRYPTO_PAIRS_FULL, STOCK_TICKERS

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
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = executor.map(fetch_score, pairs_chunk)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

def identify_support_resistance_levels(df, window=10):
    if df.empty or len(df) < window * 2 + 1: return [], []
    local_min = df['Low'].rolling(window=window*2+1, center=True).min()
    local_max = df['High'].rolling(window=window*2+1, center=True).max()
    support_levels = df[df['Low'] == local_min]['Low'].dropna().unique().tolist()
    resistance_levels = df[df['High'] == local_max]['High'].dropna().unique().tolist()
    return support_levels, resistance_levels

def analyze_candle_patterns(df):
    if df.empty: return None
    patterns = df.ta.cdl_pattern(name="all")
    if patterns.empty: return None
    last_pattern_col = patterns.iloc[-1].replace(0, np.nan).dropna()
    if last_pattern_col.empty: return None
    pattern_name = last_pattern_col.index[0]
    signal = last_pattern_col.iloc[0]
    pattern_type = 'neutral'
    if signal > 0: pattern_type = 'bullish'
    elif signal < 0: pattern_type = 'bearish'
    name_map = pattern_name.replace('CDL_', '').replace('_', ' ').title()
    return {"name": name_map, "type": pattern_type, "text": f"{'🟢' if signal > 0 else '🔴'} {name_map}"}

def analyze_volume(df):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних", 0
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if pd.isna(last['Volume_MA']): return "Недостатньо даних", 0
    volume_info = "Об'єм нейтральний"
    score_change = 0
    if last['Volume'] > last['Volume_MA'] * 1.5:
        if last['Close'] > prev['Close']:
            volume_info = "🟢 Підвищений об'єм на зростанні"
            score_change = 5
        else:
            volume_info = "🔴 Підвищений об'єм на падінні"
            score_change = -5
    return volume_info, score_change

def get_signal_strength_verdict(pair, display_name, asset):
    df = get_market_data(pair, '1m', asset, limit=50)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для 1-хв аналізу *{display_name}*."
    try:
        df.ta.rsi(length=14, append=True, col_names=('RSI',))
        df.ta.kama(length=14, append=True, col_names=('KAMA',))
        daily_df = get_market_data(pair, '1d', asset, limit=100)
        support_levels, resistance_levels = [], []
        if not daily_df.empty:
            support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
        last = df.iloc[-1]
        if pd.isna(last['RSI']) or pd.isna(last['KAMA']):
             return f"⚠️ Помилка розрахунку індикаторів для *{display_name}*."
        current_price = last['Close']
        is_near_support = any(abs(current_price - sl) / current_price < 0.01 for sl in support_levels)
        is_near_resistance = any(abs(current_price - rl) / current_price < 0.01 for rl in resistance_levels)
        candle_pattern = analyze_candle_patterns(df)
        volume_info, volume_score_change = analyze_volume(df)
        score = 50
        reasons = []
        if last['Close'] > last['KAMA']: score += 10; reasons.append("ціна вище KAMA(14)")
        else: score -= 10; reasons.append("ціна нижче KAMA(14)")
        rsi = last['RSI']
        if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
        elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
        if is_near_support: score += 10; reasons.append("ціна біля підтримки")
        if is_near_resistance: score -= 10; reasons.append("ціна біля опору")
        score += volume_score_change
        score = np.clip(score, 0, 100)
        bull_percentage, bear_percentage = int(score), 100 - int(score)
        strength_line = f"🐂 Бики {bull_percentage}% ⬆️\n🐃 Ведмеді {bear_percentage}% ⬇️"
        reason_line = f"Підстава: {', '.join(reasons)}." if reasons else "Змішані сигнали."
        disclaimer = "\n\n_⚠️ Це не фінансова порада._"
        sr_text_parts = []
        if support_levels: sr_text_parts.append(f"Підтримка: `{min(support_levels, key=lambda x: abs(x - current_price)):.4f}`")
        if resistance_levels: sr_text_parts.append(f"Опір: `{min(resistance_levels, key=lambda x: abs(x - current_price)):.4f}`")
        sr_info = " | ".join(sr_text_parts) if sr_text_parts else "Рівні не визначені"
        final_message = (f"**🕯️ Індекс сили ринку (1хв):** *{display_name}*\n"
                         f"**Поточна ціна:** `{last['Close']:.4f}`\n\n"
                         f"**Баланс сил:**\n{strength_line}\n\n"
                         f"**Рівні S/R (денні):**\n{sr_info}\n\n")
        if candle_pattern: final_message += f"**Свічковий патерн:**\n{candle_pattern['text']}\n\n"
        if volume_info: final_message += f"**Аналіз об'єму:**\n{volume_info}\n\n"
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
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = ex.map(worker, ANALYSIS_TIMEFRAMES)
    rows = [r for r in results if r[1] is not None]
    table = "\n".join([f"| {tf:<4} | {sig} |" for tf, sig in rows])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n| ТФ   | Сигнал |\n|:----:|:---:|\n{table}"

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

        daily_df = get_market_data(pair, '1d', asset, limit=100)
        support, resistance = None, None
        if not daily_df.empty:
            support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
            if support_levels: support = float(min(support_levels, key=lambda x: abs(x - current_price)))
            if resistance_levels: resistance = float(min(resistance_levels, key=lambda x: abs(x - current_price)))

        if support and abs(current_price - support) / current_price < 0.01:
            score += 10; reasons.append("Ціна біля підтримки")
        if resistance and abs(current_price - resistance) / current_price < 0.01:
            score -= 10; reasons.append("Ціна біля опору")

        score = int(np.clip(score, 0, 100))
        
        history_df = df.tail(50)
        date_col = 'ts' if 'ts' in history_df.columns else 'datetime'
        history = {
            "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            "open": history_df['Open'].tolist(), "high": history_df['High'].tolist(),
            "low": history_df['Low'].tolist(), "close": history_df['Close'].tolist()
        }

        return {
            "pair": pair, "price": current_price, "bull_percentage": score,
            "bear_percentage": 100 - score, "reasons": reasons, "support": support,
            "resistance": resistance, "history": history
        }
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}")
        return {"error": str(e)}