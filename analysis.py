# analysis.py
import pandas as pd
import pandas_ta as ta
from datetime import datetime, time
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, PAIR_ACTIVE_HOURS, ANALYSIS_TIMEFRAMES

def get_market_data(pair, tf, asset, limit=300):
    """Отримує ринкові дані без кешування."""
    try:
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            return df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'})
        
        if asset in ('forex', 'stocks'):
            td_tf_map = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': '1day'}
            ts = td.time_series(symbol=pair, interval=td_tf_map.get(tf), outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                return df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}).reset_index()
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair}: {e}")
        return pd.DataFrame()

def _calculate_core_signal(df):
    """Розраховує базовий сигнал на основі RSI."""
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']): raise ValueError("Не вдалося розрахувати RSI")
    
    score = 50
    rsi = float(last['RSI'])
    if rsi < 35: score += 15
    elif rsi > 65: score -= 15

    return {"score": int(score), "price": float(last['Close'])}

def get_api_detailed_signal_data(pair, timeframe='1m'):
    """Головна функція для отримання сигналу."""
    asset = 'crypto' if 'USDT' in pair else ('forex' if '/' in pair else 'stocks')
    df = get_market_data(pair, timeframe, asset)

    if df.empty or len(df) < 20:
        return {"error": "Недостатньо даних для аналізу."}

    try:
        analysis = _calculate_core_signal(df)
        score = analysis['score']
        verdict_text = "Нейтрально"
        if score > 55: verdict_text = "Сигнал на покупку"
        elif score < 45: verdict_text = "Сигнал на продаж"

        return {
            "pair": pair, "price": analysis['price'], "timeframe": timeframe,
            "verdict_text": verdict_text, "verdict_level": "neutral"
        }
    except Exception as e:
        logger.error(f"Помилка генерації сигналу для {pair}: {e}")
        return {"error": "Помилка аналізу."}

# --- Функції, які ВИКЛИКАЮТЬСЯ з bot.py ---

def rank_assets_for_api(pairs, asset_type):
    """Ранжує активи (зараз просто повертає список як є)."""
    logger.info(f"Викликано rank_assets_for_api для {asset_type}")
    return [{'ticker': p, 'score': 0, 'active': True} for p in pairs]

def sort_pairs_by_activity(pairs: list[dict]) -> list[dict]:
    """Сортує активи (зараз просто повертає список як є)."""
    logger.info("Викликано sort_pairs_by_activity")
    return pairs

def get_api_mta_data(pair, asset):
    """Повертає порожні дані для MTA, щоб уникнути помилок."""
    logger.info(f"Викликано get_api_mta_data для {pair}")
    return []