# config.py
import os
import logging
import threading
from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

# --- Telegram Tokens ---
TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")

# --- cTrader Credentials ---
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
DEMO_ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", "0"))

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Caching ---
MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
SYMBOL_DATA_CACHE = {}
CACHE_LOCK = threading.Lock()

# --- Constants ---
DB_NAME = "zigzag.db"
FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']

# --- ЗМІНЕНО: Видалено глобальні об'єкти bot, dp, app. Ініціалізація перенесена в main.py ---