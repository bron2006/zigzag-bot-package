# ctrader_api.py
import requests
import logging
import pandas as pd
import time

from db import get_ctrader_token, save_ctrader_token
from config import CT_CLIENT_ID, CT_CLIENT_SECRET

# --- ВИКОРИСТОВУЄМО ПРАВИЛЬНУ АДРЕСУ ДЛЯ REST API ---
CTRADER_API_BASE_URL = "https://api.spotware.com"
CTRADER_TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"

def get_trendbars(access_token: str, symbol_name: str, timeframe: str, limit: int):
    # Ця мапа ID залишається актуальною
    symbol_id_map = {
        "EUR/USD": 1, "GBP/USD": 2, "USD/JPY": 3, "USD/CAD": 4, "AUD/USD": 5, 
        "USD/CHF": 6, "NZD/USD": 7, "EUR/GBP": 8, "EUR/JPY": 9, "CHF/JPY": 48, 
        "EUR/CHF": 49, "GBP/CHF": 50, "USD/MXN": 100, "USD/BRL": 101, "USD/ZAR": 102
    }
    symbol_id = symbol_id_map.get(symbol_name)
    if not symbol_id:
        logging.error(f"Невідомий символ для cTrader: {symbol_name}")
        return pd.DataFrame()

    timeframe_map = {"1m": "m1", "15min": "m15", "1h": "h1", "4h": "h4", "1day": "d1"}
    ctrader_tf = timeframe_map.get(timeframe)
    if not ctrader_tf:
        logging.error(f"Непідтримуваний таймфрейм для cTrader: {timeframe}")
        return pd.DataFrame()
    
    # --- ВИПРАВЛЕНО: Формуємо правильний URL для отримання свічок ---
    # REST API cTrader використовує інший формат шляху, ніж той, що був у WebSocket API
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/symbols/{symbol_id}/trendbars/{ctrader_tf}"
    
    # Параметри запиту передаємо окремо
    params = {
        'count': limit
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        logging.info(f"Звертаюся до URL: {api_url} з параметрами: {params}")
        response = requests.get(api_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", [])
        
        df = pd.DataFrame(data)
        if df.empty: 
            logging.warning(f"Отримано порожній результат для {symbol_name}")
            return df
            
        df = df.rename(columns={'timestamp': 'ts', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        
        logging.info(f"✅ УСПІХ! Отримано {len(df)} свічок для {symbol_name} з cTrader.")
        return df[['ts', 'Open', 'High', 'Low', 'Close', 'Volume']]

    except requests.exceptions.RequestException as e:
        error_message = f"Помилка при отриманні даних свічок від cTrader: {e}"
        if e.response is not None:
            error_message += f" | Status Code: {e.response.status_code} | Response: {e.response.text}"
        logging.error(error_message)
        return pd.DataFrame()


def _refresh_token(refresh_token: str):
    payload = {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': CT_CLIENT_ID, 'client_secret': CT_CLIENT_SECRET }
    try:
        response = requests.post(CTRADER_TOKEN_URL, data=payload, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        error_message = f"Не вдалося оновити токен: {e}"
        if e.response is not None:
            error_message += f" | Status Code: {e.response.status_code} | Response: {e.response.text}"
        logging.error(error_message)
        return None

def get_valid_access_token(user_id: int):
    token_data = get_ctrader_token(user_id)
    if not token_data:
        logging.warning(f"Токен для користувача {user_id} не знайдено."); return None

    if time.time() > token_data['expires_at'] - 300:
        logging.info(f"Токен cTrader для {user_id} закінчується, оновлюю...")
        new_token_data = _refresh_token(token_data['refresh_token'])
        if new_token_data and 'accessToken' in new_token_data:
            save_ctrader_token(user_id, new_token_data.get('accessToken'), new_token_data.get('refreshToken'), new_token_data.get('expiresIn'))
            logging.info(f"Токен для {user_id} успішно оновлено.")
            return new_token_data.get('accessToken')
        
        logging.error(f"‼️ Не вдалося отримати/оновити access_token для користувача {user_id} — буде повернено None.")
        return None
    
    return token_data['access_token']