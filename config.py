# config.py
import os
import logging
from cachetools import TTLCache
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application # <-- ЗМІНЕНО
from flask import Flask
import threading

load_dotenv()
TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
CACHE_LOCK = threading.Lock()

# --- ПОВНІСТЮ ЗМІНЕНО ІНІЦІАЛІЗАЦІЮ БОТА ---
application = Application.builder().token(TOKEN).build()
bot = application.bot
dp = application.dispatcher

app = Flask(__name__)

CRYPTO_PAIRS_FULL = []
CRYPTO_CHUNK_SIZE = 12

FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']
DB_NAME = "zigzag.db"