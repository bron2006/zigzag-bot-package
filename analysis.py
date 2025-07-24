# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES, CRYPTO_PAIRS_FULL, STOCK_TICKERS, FOREX_PAIRS_MAP

def get_market_data(pair, tf, asset, limit=300):
    # ... (код залишається без змін)
    return pd.DataFrame() # Placeholder

def rank_assets_for_api(pairs, asset_type):
    # ... (код залишається без змін)
    return [] # Placeholder

def get_api_detailed_signal_data(pair):
    # ... (код залишається без змін)
    return {} # Placeholder
    
# --- ПОЧАТОК ЗМІНИ: Виправляємо опечатку в назві функції ---
def get_api_mta_data(pair, asset):
# --- КІНЕЦЬ ЗМІНИ ---
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
    
    mta_data = [r for r in results if r is not None]
    return mta_data

# ... (решта ваших старих функцій)
def rank_crypto_chunk(pairs_chunk):
    return []
def get_signal_strength_verdict(pair, display_name, asset):
    return ""
def get_full_mta_verdict(pair, display_name, asset):
    return ""