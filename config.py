# config.py
import os
from dotenv import load_dotenv

# Завантажуємо змінні оточення з файлу .env
load_dotenv()

# --- Налаштування бази даних ---
# ОСЬ ЦЕЙ РЯДОК ПОТРІБНО ДОДАТИ
DB_NAME = os.getenv("DB_NAME", "signals.db") # Назва файлу бази даних SQLite

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_chat_id() -> int:
    """Повертає Telegram Chat ID, перетворюючи його на ціле число."""
    chat_id_str = os.getenv("TELEGRAM_CHAT_ID")
    return int(chat_id_str) if chat_id_str else None

# --- cTrader ---
def get_ct_client_id() -> str:
    """Повертає cTrader Client ID."""
    return os.getenv("CT_CLIENT_ID")

def get_ct_client_secret() -> str:
    """Повертає cTrader Client Secret."""
    return os.getenv("CT_CLIENT_SECRET")

def get_ctrader_access_token() -> str:
    """Повертає Access Token для доступу до рахунку."""
    return os.getenv("CTRADER_ACCESS_TOKEN")

def get_demo_account_id() -> int:
    """Повертає ID демо-рахунку cTrader, перетворюючи його на ціле число."""
    account_id_str = os.getenv("CT_DEMO_ACCOUNT_ID")
    return int(account_id_str) if account_id_str else None

# --- Fly.io ---
def get_fly_app_name() -> str:
    """Повертає назву додатку на Fly.io для побудови URL."""
    return os.getenv("FLY_APP_NAME")

# --- Словник з валютними парами для меню ---
FOREX_SESSIONS = {
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF"],
    "Американська": ["USD/CAD", "USD/JPY", "GBP/JPY", "EUR/JPY", "CAD/JPY"],
    "Азіатська": ["AUD/USD", "NZD/USD", "AUD/JPY", "NZD/JPY", "AUD/NZD"],
    "Тихоокеанська": ["AUD/CAD", "AUD/CHF", "CAD/CHF", "GBP/AUD", "EUR/AUD"]
}