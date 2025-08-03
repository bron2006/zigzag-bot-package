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

            df = fetch_trendbars_sync(access_token, account_id, symbol_id, timeframe=tf)

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
        
        # Перейменовуємо стовпці до нижнього регістру для сумісності
        df.columns = [col.lower() for col in df.columns]
        
        if use_cache: MARKET_DATA_CACHE[key] = df
        return df

    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} (asset: {asset}, tf: {tf}): {e}", exc_info=True)
        return pd.DataFrame()

# --- ПОЧАТОК ЗМІН: Відновлено відсутні функції ---

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
            logger.warning(f"[ANALYZE] Дані для {symbol} відсутні")
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

def get_signal_strength_verdict(results: list) -> str:
    """Підраховує BUY/SELL сигнали та повертає загальну оцінку"""
    buy_count = sum(1 for r in results if r['signal'] == 'BUY')
    sell_count = sum(1 for r in results if r['signal'] == 'SELL')
    total = len([r for r in results if r['signal'] in ('BUY', 'SELL')])

    if total == 0:
        return "📊 Немає даних для аналізу"

    strength = ''
    if buy_count > sell_count:
        strength = f"🟢 BUY: {buy_count}/{total}"
    elif sell_count > buy_count:
        strength = f"🔴 SELL: {sell_count}/{total}"
    else:
        strength = f"⚪️ NEUTRAL: {buy_count}/{total}"

    return f"Загальна оцінка ринку: {strength}"

def get_full_mta_verdict(pairs: list, timeframe: str) -> str:
    results = []
    for symbol in pairs:
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in MARKET_DATA_CACHE:
            results.append(MARKET_DATA_CACHE[cache_key])
        else:
            result = analyze_pair(symbol, timeframe)
            MARKET_DATA_CACHE[cache_key] = result
            results.append(result)

    verdict = get_signal_strength_verdict(results)
    formatted = "\n".join([
        f"{r['symbol']} — {r['signal']} ({r.get('price', '-')})"
        for r in results
    ])
    return f"{verdict}\n\n{formatted}"

# --- КІНЕЦЬ ЗМІН ---