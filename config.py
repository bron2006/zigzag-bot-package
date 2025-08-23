# config.py
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

DB_NAME = os.getenv("DB_NAME", "/data/signals.db")
DB_PATH = Path(os.getenv("DB_PATH", DB_NAME))

try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_chat_id() -> int:
    chat_id_str = os.getenv("TELEGRAM_CHAT_ID")
    return int(chat_id_str) if chat_id_str else None

def get_ct_client_id() -> str: return os.getenv("CT_CLIENT_ID")
def get_ct_client_secret() -> str: return os.getenv("CT_CLIENT_SECRET")
def get_ctrader_access_token() -> str: return os.getenv("CTRADER_ACCESS_TOKEN")
def get_demo_account_id() -> int:
    account_id_str = os.getenv("DEMO_ACCOUNT_ID")
    return int(account_id_str) if account_id_str else None

def get_fly_app_name() -> str: return os.getenv("FLY_APP_NAME")

FOREX_SESSIONS = {
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF"],
    "Американська": ["USD/CAD", "USD/JPY", "GBP/JPY", "EUR/JPY", "CAD/JPY"],
    "Азіатська": ["AUD/USD", "NZD/USD", "AUD/JPY", "NZD/JPY", "AUD/NZD"],
    "Тихоокеанська": ["AUD/CAD", "AUD/CHF", "CAD/CHF", "GBP/AUD", "EUR/AUD"]
}

# Повертаємо список, який будемо уточнювати
CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", 
    "LTC/USD", "BNB/USD", "ADA/USD", "AVAX/USD", "DOT/USD"
]

STOCK_TICKERS = [
    "AAPL", "GOOGL", "MSFT", "AMZN", "NVDA", "TSLA", "META", "JPM", "V", "JNJ"
]

COMMODITIES = [
    "XAU/USD"
]