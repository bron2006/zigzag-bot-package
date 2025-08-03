# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import requests
import ccxt
from concurrent.futures import ThreadPoolExecutor

from db import add_signal_to_history
from config import logger, FINNHUB_API_KEY, MARKET_DATA_CACHE, RANKING_CACHE, ANALYSIS_TIMEFRAMES
from ctrader_api import get_valid_access_token
from ctrader_websocket_client import fetch_trendbars_sync

_executor = None
def get_executor():
    global _executor
    if _executor is None: _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

def get_market_data(pair, tf, asset, limit=300, force_refresh=False):
    key = f"{pair}_{tf}_{limit}"
    use_cache = asset == 'crypto'
    if use_cache and not force_refresh and key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]

    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            binance = ccxt.binance({'enableRateLimit': True, 'timeout': 15000})
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)

        elif asset == 'forex':
            user_id = 12345
            account_id = 62157581 # <-- ЗАМІНІТЬ НА ID ВАШОГО РЕАЛЬНОГО ДЕМО-РАХУНКУ
            
            symbol_id_map = {"EUR/USD": 1, "GBP/USD": 2, "USD/JPY": 3, "USD/CAD": 4, "AUD/USD": 5, "USD/CHF": 6, "NZD/USD": 7, "EUR/GBP": 8, "EUR/JPY": 9, "CHF/JPY": 48, "EUR/CHF": 49, "GBP/CHF": 50, "USD/MXN": 100, "USD/BRL": 101, "USD/ZAR": 102}
            symbol_id = symbol_id_map.get(pair)
            
            if not symbol_id:
                logger.error(f"Невідомий symbol_id для Forex-пари: {pair}")
                return pd.DataFrame()

            access_token = get_valid_access_token(user_id)
            if not access_token:
                logger.error(f"Не вдалося отримати/оновити токен cTrader для {pair}.")
                return pd.DataFrame()

            # Використовуємо '15m' замість '15min' для сумісності з cTrader
            tf_map = {'15min': '15m', '1h': '1h', '4h': '4h', '1day': '1day'}
            ctrader_tf = tf_map.get(tf, tf)
            # Примітка: для денних графіків (1day) fetch_trendbars_sync може повернути мало даних.
            # Для детального аналізу краще використовувати REST API або більший ліміт.
            df = fetch_trendbars_sync(access_token, account_id, symbol_id, timeframe=ctrader_tf)

        elif asset == 'stocks':
            finnhub_tf_map = {'15min': '15', '1h': '60', '4h': 'D', '1day': 'D'}
            resolution = finnhub_tf_map.get(tf, 'D')
            to_ts = int(time.time())
            delta_seconds = limit * (int(resolution) * 60 if resolution.isdigit() else 24 * 3600)
            from_ts = to_ts - delta_seconds
            api_url = f"https://finnhub.io/api/v1/stock/candle?symbol={pair}&resolution={resolution}&from={from_ts}&to={to_ts}&token={FINNHUB_API_KEY}"
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            data = response.json()
            if data.get('s') == 'ok' and data.get('t'):
                df = pd.DataFrame({'ts': pd.to_datetime(data['t'], unit='s', utc=True), 'Open': data['o'], 'High': data['h'], 'Low': data['l'], 'Close': data['c'], 'Volume': data['v']})
            else: return pd.DataFrame()

        if df.empty: return pd.DataFrame()
        
        df.columns = [col.lower() for col in df.columns]
        
        if use_cache: MARKET_DATA_CACHE[key] = df
        return df

    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} (asset: {asset}, tf: {tf}): {e}", exc_info=True)
        return pd.DataFrame()

def get_asset_type(pair: str) -> str:
    """Визначає тип активу за його тікером."""
    if '/' in pair:
        return 'crypto' if 'USDT' in pair else 'forex'
    return 'stocks'

def analyze_pair(symbol: str, timeframe: str, limit: int = 150) -> dict:
    """Завантажити історію, розрахувати індикатори та сформувати сигнал"""
    try:
        asset_type = get_asset_type(symbol)
        df = get_market_data(symbol, timeframe, asset_type, limit)
        
        if df is None or df.empty:
            logger.warning(f"[ANALYZE] Дані для {symbol} ({timeframe}) відсутні")
            return {'symbol': symbol, 'signal': 'NO DATA'}

        df.ta.ema(length=20, append=True)
        df.ta.rsi(length=14, append=True)

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
            'price': round(last_price, 5),
            'rsi': round(last_rsi, 2),
            'ema': round(last_ema, 5),
            'time': df['ts'].iloc[-1].strftime('%Y-%m-%d %H:%M')
        }

    except Exception as e:
        logger.error(f"[ANALYZE] Помилка для {symbol}: {e}", exc_info=True)
        return {'symbol': symbol, 'signal': 'ERROR'}

# --- НОВА ФУНКЦІЯ ДЛЯ ДЕТАЛЬНОГО АНАЛІЗУ ---
def get_detailed_signal(pair: str, limit: int = 200) -> dict:
    """
    Виконує детальний аналіз для пари, повертаючи дані для WebApp.
    """
    asset_type = get_asset_type(pair)
    # Використовуємо денний графік для основного, більш стабільного сигналу
    df = get_market_data(pair, '1day', asset_type, limit=limit)

    if df is None or df.empty or len(df) < 50: # Потрібно достатньо даних для EMA(50)
        return {'error': f'Недостатньо історичних даних для аналізу {pair}'}

    # 1. Розрахунок індикаторів
    df.ta.ema(length=20, append=True, col_names=('EMA_20',))
    df.ta.ema(length=50, append=True, col_names=('EMA_50',))
    df.ta.rsi(length=14, append=True, col_names=('RSI_14',))
    df.ta.bbands(length=20, append=True, col_names=('BBL_20_2.0', 'BBM_20_2.0', 'BBU_20_2.0', 'BBB_20_2.0', 'BBP_20_2.0'))
    df.ta.macd(fast=12, slow=26, append=True, col_names=('MACD_12_26_9', 'MACDh_12_26_9', 'MACDs_12_26_9'))

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    last_price = last_row['close']
    
    reasons = []
    buy_score = 0
    sell_score = 0

    # 2. Формування списку причин на основі індикаторів
    # Тренд за EMA
    if last_price > last_row['EMA_20'] and last_row['EMA_20'] > last_row['EMA_50']:
        reasons.append("🟢 Сильний висхідний тренд (Ціна > EMA20 > EMA50)")
        buy_score += 2
    elif last_price > last_row['EMA_20']:
        reasons.append("🟢 Ціна вище EMA(20), що вказує на короткостроковий висхідний імпульс.")
        buy_score += 1
    elif last_price < last_row['EMA_20'] and last_row['EMA_20'] < last_row['EMA_50']:
        reasons.append("🔴 Сильний низхідний тренд (Ціна < EMA20 < EMA50)")
        sell_score += 2
    elif last_price < last_row['EMA_20']:
        reasons.append("🔴 Ціна нижче EMA(20), що вказує на короткостроковий низхідний імпульс.")
        sell_score += 1
        
    # RSI
    if last_row['RSI_14'] > 70:
        reasons.append("🟡 RSI > 70: Ринок перекуплений, можлива корекція вниз.")
        sell_score += 1
    elif last_row['RSI_14'] < 30:
        reasons.append("🟡 RSI < 30: Ринок перепроданий, можливий відскок вгору.")
        buy_score += 1
    
    # Смуги Боллінджера
    if last_price > last_row['BBU_20_2.0']:
        reasons.append("🟡 Ціна пробила верхню смугу Боллінджера, що може вказувати на майбутню корекцію.")
        sell_score += 1
    if last_price < last_row['BBL_20_2.0']:
        reasons.append("🟡 Ціна пробила нижню смугу Боллінджера, що може вказувати на майбутній відскок.")
        buy_score += 1

    # MACD (перетин)
    if last_row['MACD_12_26_9'] > last_row['MACDs_12_26_9'] and prev_row['MACD_12_26_9'] <= prev_row['MACDs_12_26_9']:
        reasons.append("🟢 MACD перетнув сигнальну лінію знизу вгору (бичачий сигнал).")
        buy_score += 2
    elif last_row['MACD_12_26_9'] < last_row['MACDs_12_26_9'] and prev_row['MACD_12_26_9'] >= prev_row['MACDs_12_26_9']:
        reasons.append("🔴 MACD перетнув сигнальну лінію зверху вниз (ведмежий сигнал).")
        sell_score += 2
        
    # 3. Формулювання вердикту
    total_score = buy_score - sell_score
    verdict_text = "НЕЙТРАЛЬНО"
    verdict_level = "neutral"

    if total_score >= 4:
        verdict_text = "СИЛЬНА КУПІВЛЯ"
        verdict_level = "strong_buy"
    elif total_score >= 2:
        verdict_text = "КУПІВЛЯ"
        verdict_level = "moderate_buy"
    elif total_score <= -4:
        verdict_text = "СИЛЬНИЙ ПРОДАЖ"
        verdict_level = "strong_sell"
    elif total_score <= -2:
        verdict_text = "ПРОДАЖ"
        verdict_level = "moderate_sell"
        
    # 4. Форматування даних для графіка
    chart_df = df.tail(100)
    history_data = {
        'dates': chart_df['ts'].dt.strftime('%Y-%m-%d').tolist(),
        'open': chart_df['open'].tolist(),
        'high': chart_df['high'].tolist(),
        'low': chart_df['low'].tolist(),
        'close': chart_df['close'].tolist(),
    }

    return {
        'pair': pair,
        'price': last_price,
        'verdict_text': verdict_text,
        'verdict_level': verdict_level,
        'reasons': reasons if reasons else ["Сигнали суперечливі, ринок невизначений."],
        'support': last_row['BBL_20_2.0'],
        'resistance': last_row['BBU_20_2.0'],
        'history': history_data
    }