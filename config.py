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
DEV_MODE_UNSAFE_AUTH_BYPASS = _env_bool("DEV_MODE_UNSAFE_AUTH_BYPASS", False)
if DEV_MODE_UNSAFE_AUTH_BYPASS:
    logger.critical(
        "DEV_MODE_UNSAFE_AUTH_BYPASS=true — Telegram initData НЕ перевіряється і будь-хто "
        "може видавати себе за DEV_USER_ID. Це НІКОЛИ не повинно бути увімкнено на Fly.io "
        "чи будь-якому продакшн-середовищі."
    )
DEV_USER_ID = _env_int("MY_TELEGRAM_ID", 123456789)
CRYPTO_PAY_TOKEN = _env_str("CRYPTO_PAY_TOKEN")
CRYPTO_PAY_API_URL = (_env_str("CRYPTO_PAY_API_URL", "https://pay.crypt.bot/api") or "https://pay.crypt.bot/api").rstrip("/")
SUBSCRIPTION_PRICE_AMOUNT = _env_str("SUBSCRIPTION_PRICE_AMOUNT", "10") or "10"
SUBSCRIPTION_PRICE_ASSET = (_env_str("SUBSCRIPTION_PRICE_ASSET", "USDT") or "USDT").upper()
SUBSCRIPTION_DAYS = _env_int("SUBSCRIPTION_DAYS", 30) or 30
TRIAL_HOURS = _env_int("TRIAL_HOURS", 24) or 24

APP_MODE = (_env_str("APP_MODE", "full") or "full").lower()
if APP_MODE not in {"full", "light"}:
    logger.warning("Unsupported APP_MODE=%r. Falling back to 'full'.", APP_MODE)
    APP_MODE = "full"

ANALYSIS_CONFIG = {"min_bars_for_analysis": 50}

IDEAL_ENTRY_THRESHOLD = _env_int("IDEAL_ENTRY_THRESHOLD", 78)
SCANNER_TIMEFRAME = _env_str("SCANNER_TIMEFRAME", "1m") or "1m"
SCANNER_COOLDOWN_SECONDS = _env_int("SCANNER_COOLDOWN_SECONDS", 300)
SCANNER_BATCH_SIZE = _env_int("SCANNER_BATCH_SIZE", 8) or 8
SCANNER_MANUAL_PRIORITY_WINDOW_SECONDS = _env_int("SCANNER_MANUAL_PRIORITY_WINDOW_SECONDS", 20) or 20
SCANNER_RATE_LIMIT_PAUSE_SECONDS = _env_int("SCANNER_RATE_LIMIT_PAUSE_SECONDS", 180) or 180
ANALYSIS_CACHE_TTL_SECONDS = _env_int("ANALYSIS_CACHE_TTL_SECONDS", 20) or 20
MARKET_DATA_CACHE_TTL_SECONDS = _env_int("MARKET_DATA_CACHE_TTL_SECONDS", 20) or 20
MARKET_DATA_REQUEST_INTERVAL_MS = _env_int("MARKET_DATA_REQUEST_INTERVAL_MS", 400) or 400
MARKET_DATA_MAX_CONCURRENT_REQUESTS = _env_int("MARKET_DATA_MAX_CONCURRENT_REQUESTS", 1) or 1
MIN_ATR_PERCENTAGE = _env_float("MIN_ATR_PERCENTAGE", 0.05)

# Signal outcome tracking (Part 1): TP/SL distance as ATR multiples, how long
# a pending signal is tracked before being closed as "timeout", and how
# often the resolver loop checks pending signals against live prices.
SIGNAL_TP_ATR_MULTIPLIER = _env_float("SIGNAL_TP_ATR_MULTIPLIER", 1.5)
SIGNAL_SL_ATR_MULTIPLIER = _env_float("SIGNAL_SL_ATR_MULTIPLIER", 1.0)
SIGNAL_OUTCOME_TIMEOUT_HOURS = _env_float("SIGNAL_OUTCOME_TIMEOUT_HOURS", 4.0)
SIGNAL_OUTCOME_CHECK_INTERVAL_MINUTES = _env_float("SIGNAL_OUTCOME_CHECK_INTERVAL_MINUTES", 5.0)

# Part 2: adaptive threshold recommendations. This ONLY produces a
# notify_admin suggestion once a day — it never changes IDEAL_ENTRY_THRESHOLD
# itself. A human decides whether to update it.
THRESHOLD_RECOMMENDATION_LOOKBACK_DAYS = _env_int("THRESHOLD_RECOMMENDATION_LOOKBACK_DAYS", 30) or 30
THRESHOLD_RECOMMENDATION_MIN_SAMPLES = _env_int("THRESHOLD_RECOMMENDATION_MIN_SAMPLES", 20) or 20
THRESHOLD_RECOMMENDATION_MIN_IMPROVEMENT_PP = _env_float("THRESHOLD_RECOMMENDATION_MIN_IMPROVEMENT_PP", 5.0)
THRESHOLD_RECOMMENDATION_INTERVAL_HOURS = _env_float("THRESHOLD_RECOMMENDATION_INTERVAL_HOURS", 24.0)

# Part 3: autotrader. Disabled by default. AUTOTRADE_ACCOUNT_MODE has NO
# Telegram/Web App toggle anywhere in this codebase on purpose — switching to
# 'live' requires manually editing the env var on Fly.io and redeploying.
AUTOTRADE_ENABLED = _env_bool("AUTOTRADE_ENABLED", False)
AUTOTRADE_ACCOUNT_MODE = (_env_str("AUTOTRADE_ACCOUNT_MODE", "demo") or "demo").strip().lower()
if AUTOTRADE_ACCOUNT_MODE not in {"demo", "live"}:
    logger.warning("Unsupported AUTOTRADE_ACCOUNT_MODE=%r. Falling back to 'demo'.", AUTOTRADE_ACCOUNT_MODE)
    AUTOTRADE_ACCOUNT_MODE = "demo"

if AUTOTRADE_ENABLED and AUTOTRADE_ACCOUNT_MODE == "live":
    logger.critical(
        "AUTOTRADE_ENABLED=true with AUTOTRADE_ACCOUNT_MODE=live — the autotrader "
        "will place REAL orders with REAL money on the configured cTrader account."
    )
elif AUTOTRADE_ENABLED:
    logger.warning("AUTOTRADE_ENABLED=true (mode=demo) — autotrader will place demo-account orders.")

# Risk limits — all parameters, never hardcoded in autotrader.py.
MAX_RISK_PERCENT_PER_TRADE = _env_float("MAX_RISK_PERCENT_PER_TRADE", 1.0)
MAX_OPEN_POSITIONS = _env_int("MAX_OPEN_POSITIONS", 3) or 3
MAX_DAILY_LOSS_PERCENT = _env_float("MAX_DAILY_LOSS_PERCENT", 5.0)
AUTOTRADE_BALANCE_CACHE_SECONDS = _env_float("AUTOTRADE_BALANCE_CACHE_SECONDS", 30.0)


def get_database_url() -> str | None:
    return _env_str("DATABASE_URL")


def get_chat_id() -> int | None:
    return _env_int("CHAT_ID")


def get_admin_access_token() -> str | None:
    """Secret bookmarkable-link token letting the admin (DEV_USER_ID) use the
    Web App outside Telegram (e.g. a plain desktop browser), without
    disabling Telegram initData validation for everyone else. Unset by
    default — the feature is off unless this secret is explicitly set."""
    return _env_str("ADMIN_ACCESS_TOKEN")


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


def get_ctrader_proto_hosts() -> list[str]:
    raw = _env_str("CTRADER_PROTO_HOSTS")
    if raw:
        hosts = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    else:
        single = _env_str("CTRADER_PROTO_HOST")
        hosts = [single] if single else ["demo1.p.ctrader.com", "demo.ctraderapi.com"]

    deduped = []
    seen = set()
    for host in hosts:
        normalized = host.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped or ["demo1.p.ctrader.com", "demo.ctraderapi.com"]


def get_ctrader_proto_port() -> int:
    return _env_int("CTRADER_PROTO_PORT", 5035) or 5035


def get_fly_app_name() -> str | None:
    return _env_str("FLY_APP_NAME")


def get_public_base_url() -> str:
    explicit = _env_str("PUBLIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")

    fly_app = get_fly_app_name() or "zigzag-bot-package"
    return f"https://{fly_app}.fly.dev"


def get_ctrader_redirect_uri() -> str:
    explicit = _env_str("CTRADER_REDIRECT_URI")
    if explicit:
        return explicit.strip()
    return f"{get_public_base_url()}/api/ctrader/oauth/callback"


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
