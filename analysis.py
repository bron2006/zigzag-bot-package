# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time

# Важливо: імпортуємо тільки ті змінні, що дійсно потрібні
from config import logger, binance, td, PAIR_ACTIVE_HOURS, ANALYSIS_TIMEFRAMES
from db import add_signal_to_history

_executor = ThreadPoolExecutor(max_workers=4)

# --- БАЗОВІ ФУНКЦІЇ ---

def get_market_data(pair, tf, asset, limit=300):
    """Отримує ринкові дані. Без кешування."""
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'})
        elif asset in ('forex', 'stocks'):
            td_tf_map = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': '1day'}
            td_tf = td_tf_map.get(tf)
            if not td_tf:
                return pd.DataFrame()
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}).reset_index()
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('UTC')
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def _format_price(price):
    if price >= 10: return f"{price:.2f}"
    if price >= 0.1: return f"{price:.4f}"
    return f"{price:.8f}".rstrip('0')

# --- ФУНКЦІЇ ПЕРЕВІРКИ СТАНУ РИНКУ ---

def is_pair_active_now(pair: str, asset_type: str) -> bool:
    """Перевіряє, чи активний ринок для даної пари."""
    now_utc = datetime.utcnow()
    if asset_type == 'crypto' or now_utc.weekday() >= 5: return asset_type == 'crypto'
    if asset_type == 'stocks': return time(13, 30) <= now_utc.time() <= time(20, 0)
    if asset_type == 'forex':
        start, end = PAIR_ACTIVE_HOURS.get(pair, (None, None))
        return start is None or start <= now_utc.time() <= end
    return True

def is_volatile_enough(df: pd.DataFrame, threshold: float = 0.003) -> bool:
    """Перевіряє, чи достатньо волатильний ринок на основі ATR."""
    if len(df) < 15: return True
    atr = df.ta.atr(length=14).iloc[-1]
    last_price = df['Close'].iloc[-1]
    return not (pd.isna(atr) or last_price == 0) and (atr / last_price) > threshold

# --- ЯДРО АНАЛІЗУ ---

def _calculate_core_signal(df, daily_df):
    """Розраховує основні індикатори та загальний бал."""
    # Ця функція є внутрішньою і потрібна для get_api_detailed_signal_data,
    # тому ми залишаємо її тут, хоч вона і не імпортується напряму.
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.kama(length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']): raise ValueError("Не вдалося розрахувати індикатори")
    
    current_price = float(last['Close'])
    reasons = []
    score = 50
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
    
    return {"score": score, "reasons": reasons, "price": current_price}

def _generate_verdict(analysis):
    """Генерує текстовий вердикт на основі балу."""
    score = analysis['score']
    if score > 55: return "⬆️ Сигнал: КУПУВАТИ", "strong_buy"
    if score < 45: return "⬇️ Сигнал: ПРОДАВАТИ", "strong_sell"
    return "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ", "neutral"

# --- ОСНОВНІ ФУНКЦІЇ, ЩО ІМПОРТУЮТЬСЯ ---

def get_api_detailed_signal_data(pair, timeframe='1m'):
    """Основна функція для отримання сигналу через API."""
    asset = 'crypto' if 'USDT' in pair else ('forex' if '/' in pair else 'stocks')

    if not is_pair_active_now(pair, asset):
        return {"error": f"Ринок зараз неактивний для {pair}."}

    df = get_market_data(pair, timeframe, asset)
    if df.empty or len(df) < 25:
        return {"error": f"Недостатньо історичних даних для аналізу {pair}."}

    if not is_volatile_enough(df):
        price = _format_price(df['Close'].iloc[-1])
        return {"error": f"Дуже низька волатильність для {pair} (ціна: {price})."}

    try:
        daily_df = get_market_data(pair, '1d', asset)
        analysis = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis)
        
        history_df = df.tail(50)
        date_col = 'ts' if 'ts' in history_df.columns else 'datetime'
        history = {
            "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            "open": history_df['Open'].tolist(), "high": history_df['High'].tolist(),
            "low": history_df['Low'].tolist(), "close": history_df['Close'].tolist()
        }
        
        return {
            "pair": pair, "price": analysis['price'], "timeframe": timeframe,
            "verdict_text": verdict_text, "verdict_level": verdict_level,
            "reasons": analysis['reasons'], "history": history
        }
    except Exception as e:
        logger.error(f"Помилка в get_api_detailed_signal_data для {pair}: {e}")
        return {"error": "Внутрішня помилка аналізу."}

def sort_pairs_by_activity(pairs: list[dict]) -> list[dict]:
    """Сортує пари, виносячи активні вгору."""
    return sorted(pairs, key=lambda p: is_pair_active_now(p['ticker'], 'forex' if '/' in p['ticker'] else 'stocks'), reverse=True)

def rank_assets_for_api(pairs, asset_type):
    """Ранжує криптовалютні пари за RSI."""
    def fetch_score(pair):
        df = get_market_data(pair, '1h', 'crypto', 50)
        if df.empty or len(df) < 15: return {'ticker': pair, 'score': -1}
        rsi = df.ta.rsi(length=14).iloc[-1]
        return {'ticker': pair, 'score': -1 if pd.isna(rsi) else abs(rsi - 50)}
    
    results = list(ThreadPoolExecutor().map(fetch_score, pairs))
    return sorted([res for res in results if res['score'] != -1], key=lambda x: x['score'], reverse=True)

def get_api_mta_data(pair, asset):
    """Розраховує Multi-Timeframe Analysis."""
    def worker(tf):
        df = get_market_data(pair, tf, asset, 200)
        if df.empty or len(df) < 55: return None
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        last = df.iloc[-1]
        if pd.isna(last['EMA_fast']) or pd.isna(last['EMA_slow']): return None
        return {"tf": tf, "signal": "BUY" if last['EMA_fast'] > last['EMA_slow'] else "SELL"}
    
    return [r for r in ThreadPoolExecutor().map(worker, ANALYSIS_TIMEFRAMES) if r is not None]

# Додаємо порожню функцію, щоб уникнути помилок імпорту в старих файлах, якщо вони залишились
def get_signal_strength_verdict(*args, **kwargs): return "Not Implemented", {}
def get_full_mta_verdict(*args, **kwargs): return "Not Implemented"