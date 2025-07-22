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
    # ... (Ця функція залишається без змін) ...
    return "This is a placeholder for the bot's detailed text message."

def get_full_mta_verdict(pair, display_name, asset):
    # ... (Ця функція залишається без змін) ...
    return "This is a placeholder for the bot's MTA message."

# --- ПОЧАТОК ЗМІН ---
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
        
        # Додаємо аналіз об'єму та свічок
        candle_pattern = analyze_candle_patterns(df)
        volume_info, volume_score_change = analyze_volume(df)
        score += volume_score_change

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
            "resistance": resistance,
            "candle_pattern": candle_pattern, # Додано патерн
            "volume_analysis": volume_info,   # Додано аналіз об'єму
            "history": history
        }
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}")
        return {"error": str(e)}
# --- КІНЕЦЬ ЗМІН ---