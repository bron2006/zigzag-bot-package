# ctrader_api.py
import requests
import logging
import time

from db import get_ctrader_token, save_ctrader_token
from config import CT_CLIENT_ID, CT_CLIENT_SECRET

# Ця URL залишається правильною для оновлення токенів
CTRADER_TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"

# --- ВИДАЛЕНО НЕПОТРІБНУ ФУНКЦІЮ get_trendbars ---

def _refresh_token(refresh_token: str):
    payload = {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': CT_CLIENT_ID, 'client_secret': CT_CLIENT_SECRET }
    try:
        response = requests.post(CTRADER_TOKEN_URL, data=payload, timeout=10)
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

    # Оновлюємо токен, якщо до його закінчення залишилося менше 5 хвилин
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