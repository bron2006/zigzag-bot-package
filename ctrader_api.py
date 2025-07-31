# ctrader_api.py
import requests
import logging

# Базовий URL для демо-середовища cTrader
CTRADER_API_BASE_URL = "https://demo.ctraderapi.com"

def get_trading_accounts(access_token: str):
    """
    Отримує список торгових рахунків, доступних для даного access_token.
    """
    api_url = f"{CTRADER_API_BASE_URL}/api/v2/accounts"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()  # Перевірка на HTTP-помилки
        
        data = response.json()
        logging.info(f"Отримано дані про рахунки: {data}")
        return data.get("data", []) # Повертаємо список рахунків

    except requests.exceptions.RequestException as e:
        logging.error(f"Помилка при отриманні рахунків cTrader: {e}")
        return None