# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- FIX: Define configuration as simple global variables ---

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# --- cTrader ---
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
DEMO_ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", 0))

# --- Fly.io ---
FLY_APP_NAME = os.getenv("FLY_APP_NAME")

# --- Database ---
DB_NAME = "bot_data.db"

# --- Asset Lists ---
FOREX_SESSIONS = {
    "Азіатська": ["USDJPY", "AUDUSD", "NZDUSD", "EURJPY", "CHFJPY"],
    "Європейська": ["EURUSD", "GBPUSD", "USDCHF", "EURGBP", "EURCHF", "GBPCHF"],
    "Американська": ["USDCAD", "USDMXN", "USDRUB", "USDZAR"]
}

# --- Validation ---
if not all([TELEGRAM_BOT_TOKEN, CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID]):
    raise ValueError("One or more required environment variables are not set.")