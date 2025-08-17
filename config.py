import os
import logging
from cachetools import TTLCache
import threading

# Не імпортуємо Dispatcher тут (v20 використовує Application)
# Беремо токен з environment (Fly secrets)
TOKEN = os.environ.get("TOKEN")  # має бути у fly secrets
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

CT_CLIENT_ID = os.environ.get("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.environ.get("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.environ.get("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = os.environ.get("CTRADER_REFRESH_TOKEN")
MY_TELEGRAM_ID = os.environ.get("MY_TELEGRAM_ID")
DEMO_ACCOUNT_ID = int(os.environ.get("DEMO_ACCOUNT_ID", "9541520"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
SYMBOL_DATA_CACHE = {}
CACHE_LOCK = threading.Lock()

# Конфіги для UI / аналізу
CRYPTO_PAIRS_FULL = []
STOCKS_US_SYMBOLS = []

FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']
DB_NAME = os.environ.get("DB_NAME", "zigzag.db")

# Функція-доступ для токена (зручно)
def get_telegram_token():
    return TOKEN
