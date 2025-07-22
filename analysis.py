# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES, CRYPTO_PAIRS_FULL, STOCK_TICKERS, FOREX_PAIRS_MAP

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
                df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('UTC')
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def rank_assets(pairs, asset_type):
    def fetch_score(pair):
        try:
            timeframe = '1h' if asset_type == 'crypto' else '15min'
            df = get_market_data(pair, timeframe, asset_type, limit=50)
            if df.empty: return None
            if asset_type in ('stocks', 'forex'):
                date_col = 'datetime' if 'datetime' in df.columns else 'ts'
                last_update_time = df[date_col].iloc[-1]
                if datetime.now(timezone.utc) - last_update_time > timedelta(hours=4): return None
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            score = abs(rsi - 50)
            return {'ticker': pair, 'score': score}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати активність {pair}: {e}")
            return None
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(fetch_score, pairs)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)

def rank_crypto_chunk(pairs_chunk):
    # This function is kept for backwards compatibility with telegram_ui.py
    return rank_assets(pairs_chunk, 'crypto')

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
    return {"name": name_map, "type": pattern_type, "text": f"{'⬆️' if signal > 0 else '⬇️'} {name_map}"}

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
    # ... (код залишається без змін)
    return "This is a placeholder for the bot's detailed text message."

def get_full_mta_verdict(pair, display_name, asset):
    # ... (код залишається без змін)
    return "This is a placeholder for the bot's MTA message."

def get_api_detailed_signal_data(pair):
    # ... (код залишається без змін)
    return {}

# --- ПОЧАТОК НОВОГО КОДУ ---
def get_api_mta_data(pair, asset):
    """
    Розраховує сигнали на різних таймфреймах і повертає їх у форматі JSON.
    """
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200)
        if df.empty or len(df) < 55: return None
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        
        last_row = df.iloc[-1]
        if pd.isna(last_row['EMA_fast']) or pd.isna(last_row['EMA_slow']):
            return None
            
        signal = "BUY" if last_row['EMA_fast'] > last_row['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = ex.map(worker, ANALYSIS_TIMEFRAMES)
    
    # Фільтруємо None результати, якщо дані для якогось ТФ не вдалося отримати
    mta_data = [r for r in results if r is not None]
    return mta_data
# --- КІНЕЦЬ НОВОГО КОДУ ---