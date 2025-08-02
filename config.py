# config.py
import os
import logging
from cachetools import TTLCache
import ccxt
import finnhub
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Updater
from flask import Flask

# --- ICMarkets (cTrader OpenAPI) ---
CT_CLIENT_ID = "16464_vrriDtL7aZ8G5I6Sq8yA1Zm939awNfK9gakcWC2gM0huqx4Nwg"
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET") # Секрет тепер зчитується з середовища
CT_REDIRECT_URI = "https://zigzag-bot-package.fly.dev/callback"

# --- Завантаження змінних середовища ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

# --- Логування ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Кеш та клієнти API ---
MARKET_DATA_CACHE = TTLCache(maxsize=5000, ttl=300) # Для даних окремих активів
RANKING_CACHE = TTLCache(maxsize=100, ttl=60)      # Для результатів сортування списків

# --- ПОЧАТОК ЗМІН: Спрощена конфігурація ccxt для сумісності ---
binance = ccxt.binance({
    'enableRateLimit': True,
    'timeout': 15000  # 15 секунд
})
# --- КІНЕЦЬ ЗМІН ---

finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

# --- Глобальні об'єкти бота ---
bot = Bot(token=TOKEN)
updater = Updater(bot=bot, use_context=True, workers=4)
dp = updater.dispatcher
app = Flask(__name__)

# --- Константи ---
CRYPTO_PAIRS_FULL = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "SHIB/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "TRX/USDT",
    "MATIC/USDT", "LTC/USDT", "BCH/USDT", "XLM/USDT", "ATOM/USDT", "ETC/USDT",
    "FIL/USDT", "NEAR/USDT", "ALGO/USDT", "VET/USDT", "ICP/USDT", "EOS/USDT"
]
CRYPTO_CHUNK_SIZE = 12

STOCK_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "NVDA", "TSLA", "META", "JPM", "V", "JNJ"]

FOREX_PAIRS_MAP = {
    "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY", "USD/CAD": "USD/CAD",
    "AUD/USD": "AUD/USD", "USD/CHF": "USD/CHF", "NZD/USD": "NZD/USD", "EUR/GBP": "EUR/GBP",
    "EUR/JPY": "EUR/JPY", "CHF/JPY": "CHF/JPY", "EUR/CHF": "EUR/CHF", "GBP/CHF": "GBP/CHF",
    "USD/MXN": "USD/MXN", "USD/BRL": "USD/BRL", "USD/ZAR": "USD/ZAR"
}
FOREX_SESSIONS = {
    "Азіатська": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/JPY", "CHF/JPY"],
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/CHF", "GBP/CHF"],
    "Американська": ["USD/CAD", "USD/MXN", "USD/BRL", "USD/ZAR"]
}
ANALYSIS_TIMEFRAMES = ['15min', '1h', '4h', '1day']
DB_NAME = "zigzag.db"