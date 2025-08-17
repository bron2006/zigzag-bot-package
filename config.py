# config.py
import os
import logging
from cachetools import TTLCache
from dotenv import load_dotenv
import threading

load_dotenv()

# Telegram token environment (compatibility)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOKEN = os.getenv("TOKEN")  # підтримка старої змінної
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# cTrader / зовнішні налаштування
CLIENT_ID = os.getenv("CT_CLIENT_ID")
CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")
ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", 9541520))
APP_PORT = int(os.getenv("PORT", 8080))

# Логи
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("zigzag")

# Кеші
MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
SYMBOL_DATA_CACHE = {}
CACHE_LOCK = threading.Lock()

# UI lists placeholders
CRYPTO_PAIRS_FULL = []
STOCKS_US_SYMBOLS = []

FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']

DB_NAME = "zigzag.db"
