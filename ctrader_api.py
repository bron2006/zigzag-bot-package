# ctrader_api.py
import requests
import logging
import pandas as pd

# Базовий URL для демо-середовища cTrader
CTRADER_API_BASE_URL = "https://demo.ctraderapi.com"

def get_trading_accounts(access_token: str):
    """
    Отримує список торгових рахунків, доступних для даного access_token.
    """
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/accounts"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        logging.info(f"Отримано дані про рахунки: {data}")
        return data.get("data", [])

    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні рахунків cTrader: {e}")
        return None

# --- ПОЧАТОК ЗМІН: Нова функція для отримання ринкових даних ---
def get_trendbars(access_token: str, symbol_name: str, timeframe: str, limit: int):
    """
    Отримує історичні дані (свічки/бари) для символу.
    """
    # Спрощена мапа імен символів на їхні ID в демо-середовищі
    # У повноцінній версії тут мав би бути динамічний пошук ID
    symbol_id_map = {
        "EUR/USD": 1
    }
    symbol_id = symbol_id_map.get(symbol_name)
    if not symbol_id:
        logging.error(f"Невідомий символ для cTrader: {symbol_name}")
        return pd.DataFrame()

    # Мапа таймфреймів
    timeframe_map = {
        "1m": "M1", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D1"
    }
    ctrader_tf = timeframe_map.get(timeframe)
    if not ctrader_tf:
        logging.error(f"Непідтримуваний таймфрейм для cTrader: {timeframe}")
        return pd.DataFrame()
        
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/symbols/{symbol_id}/trendbars/{ctrader_tf}?count={limit}"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        data = response.json().get("data", [])
        
        # Конвертуємо дані у DataFrame, який очікує наш аналізатор
        df = pd.DataFrame(data)
        if df.empty:
            return df
            
        df = df.rename(columns={
            'timestamp': 'ts',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        })
        # API повертає ціни як цілі числа (напр., 1.07000 як 107000)
        price_cols = ['Open', 'High', 'Low', 'Close']
        df[price_cols] = df[price_cols] / 100000.0
        
        # API повертає timestamp в мілісекундах
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        
        return df[['ts', 'Open', 'High', 'Low', 'Close', 'Volume']]

    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні даних свічок від cTrader: {e}")
        return pd.DataFrame()
# --- КІНЕЦЬ ЗМІН ---