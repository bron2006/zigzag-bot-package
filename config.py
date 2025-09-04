# config.py
import os
import json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

IS_DEV_MODE = os.getenv("NORD", "off").lower() == "on"
DEV_USER_ID = 123456789

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("CRITICAL: TELEGRAM_BOT_TOKEN is not set in the environment!")

DB_NAME = os.getenv("DB_NAME", "/data/signals.db")
DB_PATH = Path(os.getenv("DB_PATH", DB_NAME))

try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def get_chat_id() -> int:
    chat_id_str = os.getenv("CHAT_ID")
    return int(chat_id_str) if chat_id_str else None

def get_ct_client_id() -> str: return os.getenv("CT_CLIENT_ID")
def get_ct_client_secret() -> str: return os.getenv("CT_CLIENT_SECRET")
def get_ctrader_access_token() -> str: return os.getenv("CTRADER_ACCESS_TOKEN")
def get_demo_account_id() -> int:
    account_id_str = os.getenv("DEMO_ACCOUNT_ID")
    return int(account_id_str) if account_id_str else None

def get_fly_app_name() -> str: return os.getenv("FLY_APP_NAME")

def get_finnhub_api_key() -> str:
    return os.getenv("FINNHUB_API_KEY")

def load_assets_from_json():
    try:
        assets_path = Path(__file__).parent / "assets.json"
        with open(assets_path, "r", encoding="utf-8") as f:
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

# --- ПОЧАТОК ЗМІН: Налаштування для сканера ринку ---
IDEAL_ENTRY_THRESHOLD = 85 # Поріг для купівлі (для продажу буде 100 - 85 = 15)
SCANNER_COOLDOWN_SECONDS = 300 # 5 хвилин (5 * 60)
# --- КІНЕЦЬ ЗМІН ---