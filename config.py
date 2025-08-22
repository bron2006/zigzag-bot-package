# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- Налаштування бази даних ---
# ПОВЕРТАЄМОСЬ ДО ПРОСТОЇ НАЗВИ ФАЙЛУ
DB_NAME = os.getenv("DB_NAME", "/data/signals.db")
DB_PATH = Path(os.getenv("DB_PATH", DB_NAME))

try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    # Якщо файловий шар read-only — не падати на імпорті
    pass

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_chat_id() -> int:
    chat_id_str = os.getenv("TELEGRAM_CHAT_ID")
    return int(chat_id_str) if chat_id_str else None

# HTTP server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# --- cTrader ---
def get_ct_client_id() -> str: return os.getenv("CT_CLIENT_ID")
def get_ct_client_secret() -> str: return os.getenv("CT_CLIENT_SECRET")
def get_ctrader_access_token() -> str: return os.getenv("CTRADER_ACCESS_TOKEN")
def get_demo_account_id() -> int:
    account_id_str = os.getenv("DEMO_ACCOUNT_ID")
    return int(account_id_str) if account_id_str else None
# Utility: повний шлях до файлу бази
def get_db_path():
    return str(DB_PATH)

# --- Fly.io ---
def get_fly_app_name() -> str: return os.getenv("FLY_APP_NAME")

# --- Словник з валютними парами для меню ---
FOREX_SESSIONS = {
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF"],
    "Американська": ["USD/CAD", "USD/JPY", "GBP/JPY", "EUR/JPY", "CAD/JPY"],
    "Азіатська": ["AUD/USD", "NZD/USD", "AUD/JPY", "NZD/JPY", "AUD/NZD"],
    "Тихоокеанська": ["AUD/CAD", "AUD/CHF", "CAD/CHF", "GBP/AUD", "EUR/AUD"]
}