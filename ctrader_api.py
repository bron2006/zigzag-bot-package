# ctrader_api.py
import requests
import logging
import pandas as pd
import time

from db import get_ctrader_token, save_ctrader_token
from config import CT_CLIENT_ID, CT_CLIENT_SECRET

# --- ЗМІНЕНО: Встановлюємо правильну адресу для REST API ---
CTRADER_API_BASE_URL = "https://api.spotware.com"
CTRADER_TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"

def get_trading_accounts(access_token: str):
    # У цьому запиті потрібно вказати ctidTraderAccountId, тому ми його поки що не можемо використовувати
    # Для отримання списку рахунків потрібен інший ендпоїнт
    pass

def get_trendbars(access_token: str, symbol_name: str, timeframe: str, limit: int):
    # Для REST API нам потрібно знати ID нашого демо-рахунку
    # Оскільки він у вас один, ми можемо тимчасово його тут вказати
    DEMO_ACCOUNT_ID = "9541520" # З вашого скріншоту

    # У REST API логіка отримання даних інша, вона вимагає ID рахунку
    # Ми тимчасово спрощуємо логіку, щоб перевірити з'єднання
    # https://api.spotware.com/connect/tradingaccounts/{ctidTraderAccountId}/symbols?oauth_token={accessToken}
    
    # Спробуємо отримати дані по символах, це простіший запит
    api_url = f"{CTRADER_API_BASE_URL}/connect/tradingaccounts/{DEMO_ACCOUNT_ID}/symbols?oauth_token={access_token}"
    
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        logging.info(f"Звертаюся до URL: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", [])
        
        logging.info(f"✅ УСПІХ! Отримано відповідь від {CTRADER_API_BASE_URL}")
        logging.info(f"Отримано {len(data)} символів.")

        # Оскільки ми отримуємо список символів, а не свічок, повертаємо тимчасовий результат
        # Повноцінну логіку отримання свічок ми реалізуємо наступним кроком
        return pd.DataFrame() # Повертаємо пустий DataFrame, щоб не зламати інший код

    except requests.exceptions.RequestException as e:
        error_message = f"Помилка при отриманні даних від cTrader REST API: {e}"
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