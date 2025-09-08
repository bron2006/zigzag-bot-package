# config.py
import os
import json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# --- ОСНОВНІ НАЛАШТУВАННЯ ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_database_url() -> str:
    """Отримує URL для підключення до бази даних Postgres."""
    return os.getenv("DATABASE_URL")

IS_DEV_MODE = os.getenv("NORD", "off").lower() == "on"

# --- ПОЧАТОК ЗМІН: Використовуємо MY_TELEGRAM_ID ---
# Тепер ID для розробника буде братися з вашого секрету
DEV_USER_ID = int(os.getenv("MY_TELEGRAM_ID", 123456789))
# --- КІНЕЦЬ ЗМІН ---

def get_chat_id() -> int: return int(os.getenv("CHAT_ID")) if os.getenv("CHAT_ID") else None
def get_ct_client_id() -> str: return os.getenv("CT_CLIENT_ID")
def get_ct_client_secret() -> str: return os.getenv("CT_CLIENT_SECRET")
def get_ctrader_access_token() -> str: return os.getenv("CTRADER_ACCESS_TOKEN")
def get_demo_account_id() -> int: return int(os.getenv("DEMO_ACCOUNT_ID")) if os.getenv("DEMO_ACCOUNT_ID") else None
def get_fly_app_name() -> str: return os.getenv("FLY_APP_NAME")

# --- НАЛАШТУВАННЯ АНАЛІЗУ ---
ANALYSIS_CONFIG = {
    "ema_daily_period": 200,
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_spike_multiplier": 1.5,
    "volume_low_multiplier": 0.5,
    "pivot_proximity_percent": 0.005,
    "min_bars_for_analysis": 200,
    "max_candle_staleness_seconds": 3600 * 3
}

# --- НАЛАШТУВАННЯ СКАНЕРА ---
IDEAL_ENTRY_THRESHOLD = 51
SCANNER_COOLDOWN_SECONDS = 300

# --- СПИСКИ АКТИВІВ ---
def load_assets_from_json():
    try:
        with open(Path(__file__).parent / "assets.json", "r", encoding="utf-8") as f:
            assets = json.load(f)
        return {
            "forex": assets.get("forex_sessions", {}),
            "crypto": assets.get("crypto_pairs", []),
            "stocks": assets.get("stock_tickers", []),
            "commodities": assets.get("commodities", [])
        }
    except Exception as e:
        print(f"CRITICAL: Could not load assets.json. Error: {e}")
        return {"forex": {}, "crypto": [], "stocks": [], "commodities": []}

_assets = load_assets_from_json()
FOREX_SESSIONS = _assets["forex"]
CRYPTO_PAIRS = _assets["crypto"]
STOCK_TICKERS = _assets["stocks"]
COMMODITIES = _assets["commodities"]

TRADING_HOURS = {
    "Європейська": "🇪🇺 (10:00 - 19:00)",
    "Американська": "🇺🇸 (15:00 - 00:00)",
    "Азіатська": "🇯🇵 (02:00 - 11:00)",
    "Тихоокеанська": "🇦🇺 (00:00 - 09:00)"
}