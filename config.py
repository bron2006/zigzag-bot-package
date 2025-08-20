# config.py
import os
import logging

# --- Статичні налаштування для cTrader API (Demo Account) ---
# Згідно з офіційною документацією Spotware.
HOST = "demo.ctraderapi.com"
PORT = 5035
SSL = True

# --- Читання секретів з оточення Fly.io ---
# Цей код отримує значення, які ви встановили через 'fly secrets set'.

# Client ID та Client Secret вашого додатку
APP_CLIENT_ID = os.getenv("CT_CLIENT_ID")
APP_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")

# Токен доступу для авторизації торгового рахунку
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

# ID вашого демо-рахунку. Конвертуємо в ціле число.
try:
    ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID"))
except (ValueError, TypeError):
    logging.error("DEMO_ACCOUNT_ID не знайдено або має невірний формат. Перевірте секрети.")
    ACCOUNT_ID = None

# --- Перевірка наявності всіх змінних ---
# Переконуємось, що всі необхідні секрети були завантажені.
if not all([APP_CLIENT_ID, APP_CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID]):
    missing = [
        name for name, var in {
            "CT_CLIENT_ID": APP_CLIENT_ID,
            "CT_CLIENT_SECRET": APP_CLIENT_SECRET,
            "CTRADER_ACCESS_TOKEN": ACCESS_TOKEN,
            "DEMO_ACCOUNT_ID": ACCOUNT_ID
        }.items() if not var
    ]
    raise ImportError(f"Не вдалося завантажити наступні секрети з оточення: {', '.join(missing)}. "
                      f"Будь ласка, перевірте налаштування в Fly.io.")