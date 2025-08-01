# ctrader_api.py
import requests
import logging
import pandas as pd
import time

# --- ПОЧАТОК ЗМІН: Імпортуємо необхідні функції та константи ---
from db import get_ctrader_token, save_ctrader_token
from config import CT_CLIENT_ID, CT_CLIENT_SECRET, CT_REDIRECT_URI
# --- КІНЕЦЬ ЗМІН ---


# Базовий URL для демо-середовища cTrader
CTRADER_API_BASE_URL = "https://demo.ctraderapi.com"
# URL для оновлення токена (збігається з URL для отримання)
CTRADER_TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"


def get_trading_accounts(access_token: str):
    """
    Отримує список торгових рахунків, доступних для даного access_token.
    """
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/accounts"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # --- ПОЧАТОК ЗМІН: Додано timeout=15 ---
        response = requests.get(api_url, headers=headers, timeout=15)
        # --- КІНЕЦЬ ЗМІН ---
        response.raise_for_status()
        data = response.json()
        logging.info(f"Отримано дані про рахунки: {data}")
        return data.get("data", [])

    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні рахунків cTrader: {e}")
        return None

def get_trendbars(access_token: str, symbol_name: str, timeframe: str, limit: int):
    """
    Отримує історичні дані (свічки/бари) для символу.
    """
    symbol_id_map = {"EUR/USD": 1}
    symbol_id = symbol_id_map.get(symbol_name)
    if not symbol_id:
        logging.error(f"Невідомий символ для cTrader: {symbol_name}")
        return pd.DataFrame()

    timeframe_map = {"1m": "M1", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D1"}
    ctrader_tf = timeframe_map.get(timeframe)
    if not ctrader_tf:
        logging.error(f"Непідтримуваний таймфрейм для cTrader: {timeframe}")
        return pd.DataFrame()
        
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/symbols/{symbol_id}/trendbars/{ctrader_tf}?count={limit}"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # --- ПОЧАТОК ЗМІН: Додано timeout=15 ---
        response = requests.get(api_url, headers=headers, timeout=15)
        # --- КІНЕЦЬ ЗМІН ---
        response.raise_for_status()
        data = response.json().get("data", [])
        
        df = pd.DataFrame(data)
        if df.empty:
            return df
            
        df = df.rename(columns={
            'timestamp': 'ts', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        })
        price_cols = ['Open', 'High', 'Low', 'Close']
        df[price_cols] = df[price_cols] / 100000.0
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        
        return df[['ts', 'Open', 'High', 'Low', 'Close', 'Volume']]

    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні даних свічок від cTrader: {e}")
        return pd.DataFrame()

# --- ПОЧАТОК ЗМІН: Нові функції для оновлення токена ---
def _refresh_token(refresh_token: str):
    """
    Внутрішня функція для виконання POST-запиту на оновлення токена.
    """
    logging.info("Спроба оновити access_token...")
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': CT_CLIENT_ID,
        'client_secret': CT_CLIENT_SECRET
    }
    try:
        # --- ПОЧАТОК ЗМІН: Додано timeout=15 ---
        response = requests.post(CTRADER_TOKEN_URL, data=payload, timeout=15)
        # --- КІНЕЦЬ ЗМІН ---
        response.raise_for_status()
        new_token_data = response.json()
        logging.info("Токен успішно оновлено.")
        return new_token_data
    except requests.exceptions.RequestException as e:
        logging.error(f"Не вдалося оновити токен: {e}")
        return None

def get_valid_access_token(user_id: int):
    """
    "Розумна" функція: дістає токен, перевіряє, чи він ще дійсний,
    оновлює його за потреби і повертає актуальний access_token.
    """
    token_data = get_ctrader_token(user_id)
    if not token_data:
        logging.warning(f"Токен для користувача {user_id} не знайдено в БД.")
        return None

    # Перевіряємо, чи не закінчиться термін дії токена в найближчі 5 хвилин
    if time.time() > token_data['expires_at'] - 300:
        new_token_data = _refresh_token(token_data['refresh_token'])
        if new_token_data:
            # Зберігаємо нові токени в базу даних
            save_ctrader_token(
                user_id,
                new_token_data.get('accessToken'),
                new_token_data.get('refreshToken'),
                new_token_data.get('expiresIn')
            )
            return new_token_data.get('accessToken')
        else:
            # Якщо оновлення не вдалося
            return None
    
    # Якщо токен ще дійсний, повертаємо його
    return token_data['access_token']
# --- КІНЕЦЬ ЗМІН ---