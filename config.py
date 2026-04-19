import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("config")
BASE_DIR = Path(__file__).resolve().parent


def _env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(name: str, default: int | None = None) -> int | None:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("%s=%r is not an integer. Using %r.", name, value, default)
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("%s=%r is not a float. Using %r.", name, value, default)
        return default


TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = _env_str("GEMINI_API_KEY")
IS_DEV_MODE = _env_bool("NORD", False)
DEV_USER_ID = _env_int("MY_TELEGRAM_ID", 123456789)

APP_MODE = (_env_str("APP_MODE", "full") or "full").lower()
if APP_MODE not in {"full", "light"}:
    logger.warning("Unsupported APP_MODE=%r. Falling back to 'full'.", APP_MODE)
    APP_MODE = "full"

ANALYSIS_CONFIG = {"min_bars_for_analysis": 50}

IDEAL_ENTRY_THRESHOLD = _env_int("IDEAL_ENTRY_THRESHOLD", 78)
SCANNER_TIMEFRAME = _env_str("SCANNER_TIMEFRAME", "1m") or "1m"
SCANNER_COOLDOWN_SECONDS = _env_int("SCANNER_COOLDOWN_SECONDS", 300)
MIN_ATR_PERCENTAGE = _env_float("MIN_ATR_PERCENTAGE", 0.05)


def get_database_url() -> str | None:
    return _env_str("DATABASE_URL")


def get_chat_id() -> int | None:
    return _env_int("CHAT_ID")


def get_ct_client_id() -> str | None:
    return _env_str("CT_CLIENT_ID")


def get_ct_client_secret() -> str | None:
    return _env_str("CT_CLIENT_SECRET")


def get_ctrader_access_token() -> str | None:
    return _env_str("CTRADER_ACCESS_TOKEN")


def get_ctrader_refresh_token() -> str | None:
    return _env_str("CTRADER_REFRESH_TOKEN")


def get_demo_account_id() -> int | None:
    return _env_int("DEMO_ACCOUNT_ID")


def get_fly_app_name() -> str | None:
    return _env_str("FLY_APP_NAME")


def load_assets_from_json() -> dict:
    try:
        with open(BASE_DIR / "assets.json", "r", encoding="utf-8") as f:
            assets = json.load(f)
        return {
            "forex": assets.get("forex_sessions", {}),
            "crypto": assets.get("crypto_pairs", []),
            "stocks": assets.get("stock_tickers", []),
            "commodities": assets.get("commodities", []),
            "symbol_aliases": assets.get("symbol_aliases", {}),
        }
    except Exception:
        logger.exception("Could not load assets.json")
        return {
            "forex": {},
            "crypto": [],
            "stocks": [],
            "commodities": [],
            "symbol_aliases": {},
        }


_assets = load_assets_from_json()
FOREX_SESSIONS = _assets["forex"]
CRYPTO_PAIRS = _assets["crypto"]
STOCK_TICKERS = _assets["stocks"]
COMMODITIES = _assets["commodities"]


def normalize_symbol_key(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


SYMBOL_ALIASES = {
    normalize_symbol_key(source): normalize_symbol_key(target)
    for source, target in _assets["symbol_aliases"].items()
    if normalize_symbol_key(source) and normalize_symbol_key(target)
}


def broker_symbol_key(value: str) -> str:
    requested = normalize_symbol_key(value)
    return SYMBOL_ALIASES.get(requested, requested)

TRADING_HOURS = {
    "Європейська": "🇪🇺 (10:00 - 19:00)",
    "Американська": "🇺🇸 (15:00 - 00:00)",
    "Азіатська": "🇯🇵 (02:00 - 11:00)",
    "Тихоокеанська": "🇦🇺 (00:00 - 09:00)",
}

SESSION_WINDOWS_UTC = {
    "Тихоокеанська": (21, 6),
    "Азіатська": (0, 9),
    "Європейська": (7, 16),
    "Американська": (13, 22),
}

SESSION_FLAGS = {
    "Тихоокеанська": "🇦🇺",
    "Азіатська": "🇯🇵",
    "Європейська": "🇪🇺",
    "Американська": "🇺🇸",
}
