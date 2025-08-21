# config.py
import os


def _getenv(name: str, default=None, required: bool = False):
    """Get env var; if required and missing → raise."""
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return value


# ---------- Base ----------
PORT = int(_getenv("PORT", "8080"))
FLY_APP_NAME = _getenv("FLY_APP_NAME")

# ---------- Telegram ----------
TELEGRAM_BOT_TOKEN = _getenv("TELEGRAM_BOT_TOKEN", required=True)
CHAT_ID = _getenv("CHAT_ID")
MY_TELEGRAM_ID = _getenv("MY_TELEGRAM_ID")
WEBHOOK_SECRET = _getenv("WEBHOOK_SECRET", "dev")

# ---------- cTrader ----------
CT_CLIENT_ID = _getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = _getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = _getenv("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = _getenv("CTRADER_REFRESH_TOKEN")
DEMO_ACCOUNT_ID_ENV = _getenv("DEMO_ACCOUNT_ID")  # raw value from env

def get_demo_account_id() -> int:
    """
    Backward-compatible getter expected by analysis.py.
    Parses DEMO_ACCOUNT_ID to int and errors if missing/invalid.
    """
    if not DEMO_ACCOUNT_ID_ENV:
        raise RuntimeError("Missing required env var: DEMO_ACCOUNT_ID")
    try:
        return int(str(DEMO_ACCOUNT_ID_ENV).strip())
    except ValueError as e:
        raise RuntimeError("DEMO_ACCOUNT_ID must be an integer") from e


# ---------- Market Data ----------
FINNHUB_API_KEY = _getenv("FINNHUB_API_KEY")
TWELVEDATA_API_KEY = _getenv("TWELVEDATA_API_KEY")

# ---------- Legacy ----------
TOKEN = _getenv("TOKEN")

# ---------- DB ----------
DB_NAME = _getenv("DB_NAME", "/data/zigzag.sqlite3")

def get_db_name() -> str:
    """Optional getter for modules that prefer a function."""
    return DB_NAME
