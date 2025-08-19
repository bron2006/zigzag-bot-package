# config.py
import os
from dotenv import load_dotenv

load_dotenv()

def _get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if value is None:
        raise ValueError(f"Помилка: обов'язкова змінна оточення '{var_name}' не встановлена.")
    return value

# --- Telegram ---
def get_telegram_token() -> str:
    return _get_required_env("TELEGRAM_BOT_TOKEN")

def get_webhook_secret() -> str:
    return _get_required_env("WEBHOOK_SECRET")

# --- cTrader ---
def get_ct_client_id() -> str:
    return _get_required_env("CT_CLIENT_ID")

def get_ct_client_secret() -> str:
    return _get_required_env("CT_CLIENT_SECRET")

def get_ctrader_access_token() -> str:
    return _get_required_env("CTRADER_ACCESS_TOKEN")

def get_demo_account_id() -> int:
    return int(_get_required_env("DEMO_ACCOUNT_ID"))

# --- Fly.io ---
def get_fly_app_name() -> str | None:
    return os.getenv("FLY_APP_NAME")

# --- Database ---
DB_NAME = "bot_data.db"

# --- Списки активів (тільки Forex) ---
# ВИДАЛЕНО CRYPTO_PAIRS_FULL та STOCKS_US_SYMBOLS
CRYPTO_PAIRS_FULL = [] 
STOCKS_US_SYMBOLS = []

# ОНОВЛЕНО: Назви пар відповідають даним з логів (без "/")
FOREX_SESSIONS = {
    "Азіатська": ["USDJPY", "AUDUSD", "NZDUSD", "EURJPY", "CHFJPY"],
    "Європейська": ["EURUSD", "GBPUSD", "USDCHF", "EURGBP", "EURCHF", "GBPCHF"],
    "Американська": ["USDCAD", "USDMXN", "USDRUB", "USDZAR"] # Замінено BRL на RUB, оскільки BRL немає у списку
}