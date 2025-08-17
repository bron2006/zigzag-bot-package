# config.py
import os
import logging
from cachetools import TTLCache
from dotenv import load_dotenv
import threading

load_dotenv()

# Telegram token environment name: TELEGRAM_BOT_TOKEN
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# cTrader envs
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")
DEMO_ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", 9541520))

# App settings
DB_NAME = os.getenv("DB_NAME", "zigzag.db")
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Caches & global structures
MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
SYMBOL_DATA_CACHE = {}
CACHE_LOCK = threading.Lock()

# Defaults for UI lists (fill later)
CRYPTO_PAIRS_FULL = []
STOCKS_US_SYMBOLS = []

# Forex sessions (as before)
FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
