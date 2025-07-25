# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES, CRYPTO_PAIRS_FULL, STOCK_TICKERS, FOREX_PAIRS_MAP

# --- ВИПРАВЛЕННЯ ПАДІННЯ СЕРВЕРА ---
# "Лінива ініціалізація" пулу потоків, безпечна для веб-сервера.
_executor = None

def get_executor():
    """Повертає єдиний екземпляр ThreadPoolExecutor."""
    global _executor
    if _executor is None:
        # Зменшено кількість воркерів до 2 для економії пам'яті
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

# Тут іде решта коду аналітики, який ми не змінювали...
# ...
# Ми додаємо сюди функції, які потрібні для API

def analyze_volume(df: pd.DataFrame, window=20):
    try:
        df['vol_ma'] = df['Volume'].rolling(window=window).mean()
        last_volume = df['Volume'].iloc[-1]
        avg_volume = df['vol_ma'].iloc[-1]
        if last_volume > avg_volume * 2:
            return f"🔥 Аномально високий об'єм (в {last_volume/avg_volume:.1f}x разів вище середнього)"
        return "Об'єм у межах норми"
    except:
        return None

def get_api_detailed_signal_data(pair):
    """Повертає структуровані дані для /api/signal."""
    asset_type = 'stocks'
    if '/' in pair: asset_type = 'crypto' if 'USDT' in pair else 'forex'

    df = get_market_data(pair, '1m', asset_type, limit=100)
    if df.empty or len(df) < 2: return {"error": f"Недостатньо даних для аналізу {pair}"}

    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=21, append=True)
    
    daily_df = get_market_data(pair, '1d', asset_type, limit=50)
    support_levels, resistance_levels = [], []
    if not daily_df.empty:
        support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
    
    current_price = df.iloc[-1]['Close']
    is_near_support = any(abs(current_price - sl) / current_price < 0.005 for sl in support_levels)
    is_near_resistance = any(abs(current_price - rl) / current_price < 0.005 for rl in resistance_levels)
        
    candle_pattern = analyze_candle_patterns(df)
    volume_analysis = analyze_volume(df)

    last = df.iloc[-1]
    score = 50
    reasons = []
    
    if last['Close'] > last['EMA_21']: score += 10; reasons.append("Ціна вище EMA(21)")
    else: score -= 10; reasons.append("Ціна нижче EMA(21)")
    
    rsi = last['RSI_14']
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості (<30)")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості (>70)")
    
    if is_near_support: score += 10; reasons.append("Ціна знаходиться біля рівня підтримки")
    elif is_near_resistance: score -= 10; reasons.append("Ціна знаходиться біля рівня опору")
    
    score = np.clip(score, 0, 100)
    date_col = 'ts' if 'ts' in df.columns else 'datetime'
    
    return {
        "pair": pair,
        "price": current_price,
        "bull_percentage": int(score),
        "bear_percentage": 100 - int(score),
        "support": min(support_levels, key=lambda x: abs(x - current_price)) if support_levels else None,
        "resistance": min(resistance_levels, key=lambda x: abs(x - current_price)) if resistance_levels else None,
        "reasons": reasons,
        "candle_pattern": candle_pattern,
        "volume_analysis": volume_analysis,
        "history": {
            "dates": df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            "open": df['Open'].tolist(),
            "high": df['High'].tolist(),
            "low": df['Low'].tolist(),
            "close": df['Close'].tolist(),
        } if not df.empty and pd.api.types.is_datetime64_any_dtype(df[date_col]) else None
    }

def get_api_mta_data(pair, asset_type):
    """Повертає дані MTA у форматі JSON для /api/get_mta."""
    def worker(tf):
        df = get_market_data(pair, tf, asset_type, limit=200)
        if df.empty or len(df) < 55: return None
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        signal = "BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}
    
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    return [r for r in results if r is not None]

def rank_assets_for_api(pairs, asset_type):
    """Універсальна функція для ранжування активів для API."""
    def fetch_score(pair):
        try:
            df = get_market_data(pair, '1h', asset_type, limit=50)
            if df.empty: return None
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            return {'ticker': pair, 'score': abs(rsi - 50)}
        except Exception:
            return None
            
    executor = get_executor()
    results = executor.map(fetch_score, pairs)
    ranked_assets = [r for r in results if r is not None]
    return sorted(ranked_assets, key=lambda x: x['score'], reverse=True)