# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- Глобальні змінні конфігурації ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
DEMO_ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", 0))
FLY_APP_NAME = os.getenv("FLY_APP_NAME")
DB_NAME = "bot_data.db"

# --- Списки активів ---
FOREX_SESSIONS = {
    "Азіатська": ["USDJPY", "AUDUSD", "NZDUSD", "EURJPY", "CHFJPY"],
    "Європейська": ["EURUSD", "GBPUSD", "USDCHF", "EURGBP", "EURCHF", "GBPCHF"],
    "Американська": ["USDCAD", "USDMXN", "USDRUB", "USDZAR"]
}

# --- Валідація ---
if not all([CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID]):
    raise ValueError("Одна або декілька обов'язкових змінних cTrader не встановлені в оточенні.")