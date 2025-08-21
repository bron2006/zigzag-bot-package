import os
from dotenv import load_dotenv

# Завантажуємо змінні з .env файлу для локальної розробки.
# На fly.io ці змінні будуть завантажені з секретів автоматично.
load_dotenv()

# --- cTrader API ---
# Взято з секретів fly.io
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
DEMO_ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID")) # Важливо перетворити на int

# --- API Endpoints ---
# Для демо-рахунків використовуємо sandbox
host = "sandbox-api.ctrader.com"
port = 5035

# --- Telegram Bot ---
# Взято з секретів fly.io
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Перевірка наявності основних змінних
if not all([CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID, TELEGRAM_BOT_TOKEN]):
    raise ValueError("Одна або декілька критичних змінних середовища не встановлені!")