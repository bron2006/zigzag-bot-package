# config.py
import os
import json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# --- ОСНОВНІ НАЛАШТУВАННЯ ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
def get_database_url() -> str: return os.getenv("DATABASE_URL")
IS_DEV_MODE = os.getenv("NORD", "off").lower() == "on"
DEV_USER_ID = int(os.getenv("MY_TELEGRAM_ID", 123456789))
def get_chat_id() -> int: return int(os.getenv("CHAT_ID")) if os.getenv("CHAT_ID") else None
def get_ct_client_id() -> str: return os.getenv("CT_CLIENT_ID")
def get_ct_client_secret() -> str: return os.getenv("CT_CLIENT_SECRET")
def get_ctrader_access_token() -> str: return os.getenv("CTRADER_ACCESS_TOKEN")
# --- ПОЧАТОК ЗМІН ---
def get_ctrader_refresh_token() -> str: return os.getenv("CTRADER_REFRESH_TOKEN")
# --- КІНЕЦЬ ЗМІН ---
def get_demo_account_id() -> int: return int(os.getenv("DEMO_ACCOUNT_ID")) if os.getenv("DEMO_ACCOUNT_ID") else None
def get_fly_app_name() -> str: return os.getenv("FLY_APP_NAME")

APP_MODE = os.getenv("APP_MODE", "full")  # 'full' or 'light'

# --- НАЛАШТУВАННЯ АНАЛІЗУ ---
ANALYSIS_CONFIG = { "min_bars_for_analysis": 50 }

# --- НАЛАШТУВАННЯ СКАНЕРА ---
IDEAL_ENTRY_THRESHOLD = 78
SCANNER_TIMEFRAME = "1m"
SCANNER_COOLDOWN_SECONDS = 300
MIN_ATR_PERCENTAGE = 0.05

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