# config.py
import os
import logging
from cachetools import TTLCache
# import ccxt # --- ВИМКНЕНО: Бібліотека для крипти більше не потрібна ---
from twelvedata import TDClient
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Updater
from flask import Flask

load_dotenv()
TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300)
RANKING_CACHE = TTLCache(maxsize=100, ttl=60)

# binance = ccxt.binance({'enableRateLimit': True}) # --- ВИМКНЕНО ---
td = TDClient(apikey=TWELVEDATA_API_KEY)

bot = Bot(token=TOKEN)
updater = Updater(bot=bot, use_context=True)
dp = updater.dispatcher
app = Flask(__name__)

# --- ЗМІНЕНО: Робимо список криптовалют порожнім ---
CRYPTO_PAIRS_FULL = []
# --------------------------------------------------
CRYPTO_CHUNK_SIZE = 12

STOCK_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "NVDA", "TSLA", "META", "JPM", "V", "JNJ"]

FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']
DB_NAME = "zigzag.db"