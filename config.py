# config.py
import os
import logging
from datetime import time
import ccxt
from twelvedata import TDClient
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Updater
from flask import Flask

# --- Завантаження змінних середовища ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")

# --- Логування ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Клієнти API ---
binance = ccxt.binance({'enableRateLimit': True})
td = TDClient(apikey=TWELVEDATA_API_KEY)

# --- Глобальні об'єкти бота ---
bot = Bot(token=TOKEN)
updater = Updater(bot=bot, use_context=True)
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

PAIR_ACTIVE_HOURS = {
    "USD/JPY": (time(0, 0), time(9, 0)),
    "AUD/USD": (time(0, 0), time(9, 0)),
    "NZD/USD": (time(0, 0), time(9, 0)),
    "EUR/JPY": (time(0, 0), time(9, 0)),
    "CHF/JPY": (time(0, 0), time(9, 0)),
    "EUR/USD": (time(7, 0), time(16, 0)),
    "GBP/USD": (time(7, 0), time(16, 0)),
    "USD/CHF": (time(7, 0), time(16, 0)),
    "EUR/GBP": (time(7, 0), time(16, 0)),
    "EUR/CHF": (time(7, 0), time(16, 0)),
    "GBP/CHF": (time(7, 0), time(16, 0)),
    "USD/CAD": (time(13, 0), time(22, 0)),
    "USD/MXN": (time(13, 0), time(22, 0)),
    "USD/BRL": (time(13, 0), time(22, 0)),
    "USD/ZAR": (time(13, 0), time(22, 0)),
}

ANALYSIS_TIMEFRAMES = ['15m', '1h', '4h', '1d']
DB_NAME = "zigzag.db"