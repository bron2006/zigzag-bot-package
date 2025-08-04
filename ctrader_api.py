# ctrader_api.py
import requests
import logging
import pandas as pd
import time

from db import get_ctrader_token, save_ctrader_token
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
    symbol_id_map = {
        "EUR/USD": 1, "GBP/USD": 2, "USD/JPY": 3, "USD/CAD": 4, "AUD/USD": 5, 
        "USD/CHF": 6, "NZD/USD": 7, "EUR/GBP": 8, "EUR/JPY": 9, "CHF/JPY": 48, 
        "EUR/CHF": 49, "GBP/CHF": 50, "USD/MXN": 100, "USD/BRL": 101, "USD/ZAR": 102
    }
    symbol_id = symbol_id_map.get(symbol_name)
    if not symbol_id:
        logging.error(f"Невідомий символ для cTrader: {symbol_name}")
        return pd.DataFrame()

    timeframe_map = {"15min": "m15", "1h": "h1", "4h": "h4", "1day": "d1"}
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
        
        return df[['ts', 'Open', 'High', 'Low', 'Close', 'Volume']]
    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні даних свічок від cTrader: {e}")
        return pd.DataFrame()

def _refresh_token(refresh_token: str):
    # --- ДОДАНО СПЕЦІАЛЬНИЙ МАРКЕР ДЛЯ ПЕРЕВІРКИ ---
    logging.info("ДЕБАГ: Запущено оновлену функцію _refresh_token з детальним логуванням...")
    # -----------------------------------------------
    
    payload = {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': CT_CLIENT_ID, 'client_secret': CT_CLIENT_SECRET }
    try:
        response = requests.post(CTRADER_TOKEN_URL, data=payload, timeout=15)
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
        
        logging.error(f"Не вдалося оновити токен для {user_id}.")
        return None
    
    return token_data['access_token']