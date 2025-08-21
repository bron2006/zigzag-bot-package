import os
from dotenv import load_dotenv

load_dotenv()

# --- cTrader API ---
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
DEMO_ACCOUNT_ID = os.getenv("DEMO_ACCOUNT_ID")

# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") # Поки не використовується, але може знадобитись

# Словник сесій та пар для меню, як у вашому telegram_ui.py
FOREX_SESSIONS = {
    "Європейська": ["EUR/USD", "GBP/USD", "USD/CHF"],
    "Американська": ["USD/JPY", "USD/CAD", "AUD/USD"],
    "Азійська": ["NZD/USD", "AUD/JPY", "GBP/JPY"],
}

def get_ct_client_id(): return CT_CLIENT_ID
def get_ct_client_secret(): return CT_CLIENT_SECRET
def get_ctrader_access_token(): return CTRADER_ACCESS_TOKEN
def get_demo_account_id(): return int(DEMO_ACCOUNT_ID)