# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time

from db import add_signal_to_history
from config import logger, binance, td, PAIR_ACTIVE_HOURS, ANALYSIS_TIMEFRAMES

_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4)
    return _executor

def get_market_data(pair, tf, asset, limit=300, force_refresh=False):
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
        elif asset in ('forex', 'stocks'):
            td_tf_map = { '1m': '1min', '5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': '1day' }
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
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def _format_price(price):
    if price >= 10: return f"{price:.2f}"
    if price >= 0.1: return f"{price:.4f}"
    return f"{price:.8f}".rstrip('0')

def is_volatile_enough(df: pd.DataFrame, threshold: float = 0.003) -> bool:
    if len(df) < 15: return True
    atr = df.ta.atr(length=14).iloc[-1]
    last_price = df['Close'].iloc[-1]
    if pd.isna(atr) or last_price == 0: return False
    return (atr / last_price) > threshold

def is_pair_active_now(pair: str, asset_type: str) -> bool:
    now_utc = datetime.utcnow()
    if asset_type == 'crypto': return True
    if now_utc.weekday() >= 5: return False
    if asset_type == 'stocks': return time(13, 30) <= now_utc.time() <= time(20, 0)
    if asset_type == 'forex':
        start, end = PAIR_ACTIVE_HOURS.get(pair, (None, None))
        if start is None: return True
        return start <= now_utc.time() <= end
    return True

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.kama(length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']):
        raise ValueError("Помилка розрахунку індикаторів")
    current_price = float(last['Close'])
    reasons = []
    score = 50
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
    # ... (інші функції без змін)
    return { "score": score, "reasons": reasons, "price": current_price } # Скорочено для ясності

def get_signal_strength_verdict(pair, display_name, asset, timeframe='1m', user_id=None, force_refresh=False):
    if not is_pair_active_now(pair, asset):
        message = (f"**🌙 Ринок зараз неактивний для пари {display_name}**")
        return message, None
    df = get_market_data(pair, timeframe, asset, limit=100)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для аналізу *{display_name}*.", None
    if not is_volatile_enough(df):
        price = _format_price(df['Close'].iloc[-1])
        message = (f"**⚪️ Низька волатильність для *{display_name}***\n\nЦіна: `{price}`")
        return message, None
    try:
        daily_df = get_market_data(pair, '1d', asset, limit=100)
        analysis = _calculate_core_signal(df, daily_df)
        # ... (решта логіки)
        return "some message", analysis
    except Exception as e:
        return f"⚠️ Помилка аналізу *{display_name}*.", None

def get_api_detailed_signal_data(pair, timeframe='1m'):
    asset = 'crypto' if 'USDT' in pair else ('forex' if '/' in pair else 'stocks')
    if not is_pair_active_now(pair, asset):
        return {"error": f"Ринок зараз неактивний для {pair}."}
    df = get_market_data(pair, timeframe, asset)
    if df.empty or len(df) < 25:
        return {"error": f"Недостатньо даних для аналізу {pair}."}
    if not is_volatile_enough(df):
        return {"error": f"Низька волатильність для {pair}."}
    try:
        daily_df = get_market_data(pair, '1d', asset)
        analysis = _calculate_core_signal(df, daily_df)
        # ... (решта логіки)
        return { "data": "some_data" }
    except Exception as e:
        return {"error": str(e)}

def sort_pairs_by_activity(pairs: list[dict]) -> list[dict]:
    # ... (без змін)
    return sorted(pairs)

# ... (інші функції, такі як rank_assets_for_api, get_full_mta_verdict і т.д., залишаються без змін,
# оскільки вони не використовують кеш, що викликав проблеми)