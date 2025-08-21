# config.py
import os

# cTrader / Spotware
CT_CLIENT_ID = os.environ.get("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.environ.get("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.environ.get("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = os.environ.get("CTRADER_REFRESH_TOKEN")
DEMO_ACCOUNT_ID = os.environ.get("DEMO_ACCOUNT_ID")

def get_demo_account_id():
    """Повертає DEMO_ACCOUNT_ID як int якщо можливо, інакше None."""
    try:
        return int(DEMO_ACCOUNT_ID)
    except (TypeError, ValueError):
        return None

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("MY_TELEGRAM_ID")

# API ключі інших сервісів
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")

# Fly.io app
FLY_APP_NAME = os.environ.get("FLY_APP_NAME")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

# Порт (для Klein/Flask)
PORT = int(os.environ.get("PORT", 8080))

# Приклад форекс-сесій
FOREX_SESSIONS = {
    "Asia": ["EUR/USD", "GBP/USD", "USD/JPY"],
    "Europe": ["EUR/USD", "GBP/USD", "EUR/GBP"],
    "America": ["USD/CHF", "USD/CAD", "EUR/USD"],
}
