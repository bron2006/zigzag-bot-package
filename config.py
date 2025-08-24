# config.py
import os
import json # <-- НОВИЙ ІМПОРТ
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# --- Налаштування бази даних ---
DB_NAME = os.getenv("DB_NAME", "/data/signals.db")
DB_PATH = Path(os.getenv("DB_PATH", DB_NAME))

try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_chat_id() -> int:
    chat_id_str = os.getenv("TELEGRAM_CHAT_ID")
    return int(chat_id_str) if chat_id_str else None

# --- cTrader ---
def get_ct_client_id() -> str: return os.getenv("CT_CLIENT_ID")
def get_ct_client_secret() -> str: return os.getenv("CT_CLIENT_SECRET")
def get_ctrader_access_token() -> str: return os.getenv("CTRADER_ACCESS_TOKEN")
def get_demo_account_id() -> int:
    account_id_str = os.getenv("DEMO_ACCOUNT_ID")
    return int(account_id_str) if account_id_str else None

# --- Fly.io ---
def get_fly_app_name() -> str: return os.getenv("FLY_APP_NAME")

# --- ПОЧАТОК ЗМІН: Завантажуємо активи з assets.json ---
def load_assets_from_json():
    """Завантажує списки активів із файлу assets.json."""
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
# --- КІНЕЦЬ ЗМІН ---