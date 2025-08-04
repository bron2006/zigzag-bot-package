# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, MARKET_DATA_CACHE, ANALYSIS_TIMEFRAMES
from ctrader_api import get_valid_access_token, get_trendbars

_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

# --- ДОДАНО ВІДСУТНЮ ФУНКЦІЮ ---
def get_asset_type(pair: str) -> str:
    """Визначає тип активу за його тікером."""
    if '/' in pair:
        return 'crypto' if 'USDT' in pair else 'forex'
    return 'stocks'

def get_market_data(pair, tf, asset, limit=300, force_refresh=False, user_id=None):
    key = f"{pair}_{tf}_{limit}"
    use_cache = asset == 'crypto'
    if use_cache and not force_refresh and key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
        
        elif asset == 'forex':
            if not user_id:
                logger.warning(f"Для отримання даних по {pair} потрібен user_id, але його не надано.")
                return pd.DataFrame()
            
            access_token = get_valid_access_token(user_id)
            if not access_token:
                logger.error(f"Не вдалося отримати/оновити токен cTrader для user_id {user_id}.")
                return pd.DataFrame()
            
            tf_map = {'15min': 'm15', '1h': 'h1', '4h': 'h4', '1day': 'd1'}
            ctrader_tf = tf_map.get(tf)
            if not ctrader_tf:
                logger.error(f"Непідтримуваний таймфрейм для cTrader: {tf}")
                return pd.DataFrame()

            # У cTrader API назви символів без слеша, напр. "EURUSD"
            df = get_trendbars(access_token, pair.replace("/", ""), ctrader_tf, limit)
            if not df.empty:
                df = df.rename(columns={'ts':'datetime'})

        elif asset == 'stocks':
            td_tf_map = { '15min': '15min', '1h': '1hour', '4h': '4hour', '1day': '1day'}
            td_tf = td_tf_map.get(tf)
            if not td_tf:
                logger.error(f"Непідтримуваний таймфрейм для TwelveData: {tf}")
                return pd.DataFrame()
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}).reset_index()
                df = df.sort_values(by='datetime').reset_index(drop=True)
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize('UTC')
        
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        
        # Переводимо назви колонок в нижній регістр для сумісності
        df.columns = [str(col).lower() for col in df.columns]

        if use_cache:
            MARKET_DATA_CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

# --- ДОДАНО ВІДСУТНЮ ФУНКЦІЮ ---
def analyze_pair(symbol: str, timeframe: str, limit: int = 150) -> dict:
    """Простий аналіз для кнопок в Telegram боті."""
    try:
        asset_type = get_asset_type(symbol)
        # Викликаємо get_market_data з None user_id, оскільки telegram_ui не має доступу до initData
        df = get_market_data(symbol, timeframe, asset_type, limit, user_id=None)
        
        if df is None or df.empty or len(df) < 20:
            return {'symbol': symbol, 'signal': 'NO DATA'}

        # Використовуємо назви колонок в нижньому регістрі
        df.ta.ema(close=df['close'], length=20, append=True, col_names=('EMA_20',))
        df.ta.rsi(close=df['close'], length=14, append=True, col_names=('RSI_14',))

        last_rsi = df['RSI_14'].iloc[-1]
        last_price = df['close'].iloc[-1]
        last_ema = df['EMA_20'].iloc[-1]

        signal = 'NEUTRAL'
        if last_price > last_ema and last_rsi > 55:
            signal = 'BUY'
        elif last_price < last_ema and last_rsi < 45:
            signal = 'SELL'

        return {
            'symbol': symbol,
            'signal': signal,
            'price': round(last_price, 5)
        }
    except Exception as e:
        logger.error(f"Помилка в analyze_pair для {symbol}: {e}", exc_info=True)
        return {'symbol': symbol, 'signal': 'ERROR'}


def _calculate_core_signal(df, daily_df):
    df.ta.rsi(close=df['close'], length=14, append=True, col_names=('RSI',))
    df.ta.kama(close=df['close'], length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']):
        raise ValueError("Помилка розрахунку індикаторів")
    current_price = float(last['close'])
    score = 50
    reasons = []
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості")
    score = int(np.clip(score, 0, 100))
    return { "score": score, "reasons": reasons, "price": current_price }

def get_api_detailed_signal_data(pair, user_id=None):
    asset = get_asset_type(pair)
    
    df = get_market_data(pair, '15min', asset, limit=100, user_id=user_id)
    if df.empty or len(df) < 25:
        return {"error": "Недостатньо даних для аналізу."}
    
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100, user_id=user_id)
        analysis = _calculate_core_signal(df, daily_df)
        
        verdict_text, verdict_level = "НЕЙТРАЛЬНО", "neutral"
        if analysis['score'] > 60: verdict_text, verdict_level = "КУПІВЛЯ", "moderate_buy"
        elif analysis['score'] < 40: verdict_text, verdict_level = "ПРОДАЖ", "moderate_sell"

        history_df = df.tail(50)
        date_col = 'datetime'
        history = { 
            "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), 
            "open": history_df['open'].tolist(), 
            "high": history_df['high'].tolist(), 
            "low": history_df['low'].tolist(), 
            "close": history_df['close'].tolist() 
        }
        return { "pair": pair, "price": analysis['price'], "verdict_text": verdict_text, "verdict_level": verdict_level, "reasons": analysis['reasons'], "support": None, "resistance": None, "history": history }
    except Exception as e:
        logger.error(f"Error in get_api_detailed_signal_data for {pair}: {e}")
        return {"error": str(e)}

def get_api_mta_data(pair, asset, user_id=None):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200, user_id=user_id)
        if df.empty or len(df) < 55: return None
        df.ta.ema(close=df['close'], length=21, append=True, col_names='EMA_fast')
        df.ta.ema(close=df['close'], length=55, append=True, col_names='EMA_slow')
        last_row = df.iloc[-1]
        if pd.isna(last_row['EMA_fast']) or pd.isna(last_row['EMA_slow']): return None
        signal = "BUY" if last_row['EMA_fast'] > last_row['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    mta_data = [r for r in results if r is not None]
    return mta_data

def rank_assets_for_api(pairs, asset_type, user_id=None):
    def fetch_score(pair):
        try:
            timeframe = '1h' if asset_type == 'crypto' else '15min'
            df = get_market_data(pair, timeframe, asset_type, limit=50, user_id=user_id)
            if df.empty or len(df) < 30: return {'ticker': pair, 'score': -1}
            rsi = df.ta.rsi(close=df['close'], length=14).iloc[-1]
            if pd.isna(rsi): return {'ticker': pair, 'score': -1}
            return {'ticker': pair, 'score': abs(rsi - 50)}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати активність {pair}: {e}")
            return {'ticker': pair, 'score': -1}
    executor = get_executor()
    results = list(executor.map(fetch_score, pairs))
    active_part = sorted([res for res in results if res['score'] != -1], key=lambda x: x['score'], reverse=True)
    inactive_part = [res for res in results if res['score'] == -1]
    return active_part + inactive_part