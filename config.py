# config.py
import os
import logging
from cachetools import TTLCache
from dotenv import load_dotenv
import threading

load_dotenv()

# Telegram token name: перевіряємо кілька можливих змінних (TELEGRAM_BOT_TOKEN, TOKEN)
def get_telegram_token():
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN")

TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")
DEMO_ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", "9541520"))

DB_NAME = "zigzag.db"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
SYMBOL_DATA_CACHE = {}
CACHE_LOCK = threading.Lock()

# Minimal placeholders so web + bot code can import them safely even if not configured
CRYPTO_PAIRS_FULL = []
STOCKS_US_SYMBOLS = []

FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']
