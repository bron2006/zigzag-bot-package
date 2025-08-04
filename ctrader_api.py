# ctrader_api.py
import requests
import logging
import pandas as pd
import time

from db import get_ctrader_token, save_ctrader_token
# --- ЗМІНЕНО: Видалено непотрібний імпорт CT_REDIRECT_URI ---
from config import CT_CLIENT_ID, CT_CLIENT_SECRET

CTRADER_API_BASE_URL = "https://demo.ctraderapi.com"
CTRADER_TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"

def get_trading_accounts(access_token: str):
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/accounts"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(api_url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json().get("data", [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні рахунків cTrader: {e}")
        return None

def get_trendbars(access_token: str, symbol_name: str, timeframe: str, limit: int):
    symbol_id_map = {"EURUSD": 1, "GBPUSD": 2, "USDJPY": 3, "USDCAD": 4, "AUDUSD": 5, "USDCHF": 6, "NZDUSD": 7, "EURGBP": 8, "EURJPY": 9, "CHFJPY": 48, "EURCHF": 49, "GBPCHF": 50, "USDMXN": 100, "USDBRL": 101, "USDZAR": 102}
    symbol_id = symbol_id_map.get(symbol_name)
    if not symbol_id:
        logging.error(f"Невідомий символ для cTrader: {symbol_name}")
        return pd.DataFrame()

    timeframe_map = {"15m": "m15", "1h": "h1", "4h": "h4", "1day": "d1"}
    ctrader_tf = timeframe_map.get(timeframe)
    if not ctrader_tf:
        logging.error(f"Непідтримуваний таймфрейм для cTrader: {timeframe}")
        return pd.DataFrame()
        
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/symbols/{symbol_id}/trendbars/{ctrader_tf}?count={limit}"
    
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(api_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json().get("data", [])
        
        df = pd.DataFrame(data)
        if df.empty: return df
            
        df = df.rename(columns={'timestamp': 'ts', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        # У cTrader ціни вже надходять у правильному форматі, ділення на 100000.0 не потрібне для REST API
        # price_cols = ['Open', 'High', 'Low', 'Close']
        # df[price_cols] = df[price_cols] / 100000.0
        
        return df[['ts', 'Open', 'High', 'Low', 'Close', 'Volume']]
    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні даних свічок від cTrader: {e}")
        return pd.DataFrame()

def _refresh_token(refresh_token: str):
    payload = {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': CT_CLIENT_ID, 'client_secret': CT_CLIENT_SECRET }
    try:
        response = requests.post(CTRADER_TOKEN_URL, data=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Не вдалося оновити токен: {e}"); return None

def get_valid_access_token(user_id: int):
    token_data = get_ctrader_token(user_id)
    if not token_data:
        logging.warning(f"Токен для користувача {user_id} не знайдено."); return None

    # Оновлюємо токен, якщо до закінчення терміну дії залишилося менше 5 хвилин
    if time.time() > token_data['expires_at'] - 300:
        logging.info(f"Токен cTrader для {user_id} закінчується, оновлюю...")
        new_token_data = _refresh_token(token_data['refresh_token'])
        if new_token_data and 'accessToken' in new_token_data:
            save_ctrader_token(user_id, new_token_data.get('accessToken'), new_token_data.get('refreshToken'), new_token_data.get('expiresIn'))
            logging.info(f"Токен для {user_id} успішно оновлено.")
            return new_token_data.get('accessToken')
        
        logging.error(f"Не вдалося оновити токен для {user_id}.")
        return None
    
    return token_data['access_token']