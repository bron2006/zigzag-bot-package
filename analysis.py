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
                df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('UTC') # Переконуємось, що дата в UTC
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

# --- ПОЧАТОК ЗМІН: Нова універсальна функція для рейтингу ---
def rank_assets(pairs, asset_type):
    """
    Універсальна функція для аналізу активності на ринку (криптовалюти, акції, форекс).
    """
    def fetch_score(pair):
        try:
            # Використовуємо коротший таймфрейм для акцій/форексу, щоб точніше бачити активність
            timeframe = '1h' if asset_type == 'crypto' else '15min'
            df = get_market_data(pair, timeframe, asset_type, limit=50)
            if df.empty: return None

            # Перевірка, чи ринок активний (для акцій та форексу)
            if asset_type in ('stocks', 'forex'):
                date_col = 'datetime' if 'datetime' in df.columns else 'ts'
                last_update_time = df[date_col].iloc[-1]
                # Якщо останні дані старші за 4 години, вважаємо ринок закритим
                if datetime.now(timezone.utc) - last_update_time > timedelta(hours=4):
                    return None
            
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            
            score = abs(rsi - 50) # Чим далі від 50, тим вища активність
            return {'ticker': pair, 'score': score}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати активність {pair}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(fetch_score, pairs)
    
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)
# --- КІНЕЦЬ ЗМІН ---

# Стара функція rank_crypto_chunk більше не потрібна, її замінила rank_assets
# (решта функцій залишається без змін)

def identify_support_resistance_levels(df, window=10):
    # ... (код залишається без змін)
    return [], []

def analyze_candle_patterns(df):
    # ... (код залишається без змін)
    return None

def analyze_volume(df):
    # ... (код залишається без змін)
    return "Об'єм нейтральний", 0
    
def get_signal_strength_verdict(pair, display_name, asset):
    # ... (код залишається без змін)
    return "Повідомлення від бота"

def get_full_mta_verdict(pair, display_name, asset):
    # ... (код залишається без змін)
    return "MTA повідомлення від бота"

def get_api_detailed_signal_data(pair):
    # ... (код залишається без змін)
    return {}