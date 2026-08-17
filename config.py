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

# ML model BUY/SELL/NEUTRAL split (analysis.py _run_technical_analysis).
# These thresholds are still named for the score direction they compare
# against - HOTFIX (2026-08-10): the verdict assigned to each side is
# swapped (score > ML_BUY_SCORE_THRESHOLD -> SELL, score <
# ML_SELL_SCORE_THRESHOLD -> BUY, otherwise NEUTRAL) pending a fix to the
# underlying model - see the TEMPORARY HOTFIX comment in analysis.py. This
# sits below IDEAL_ENTRY_THRESHOLD, which is the separate, higher bar
# scanner.py uses to decide whether to actually fire a signal - keep both
# in sync if the verdict mapping changes again (see scanner.py's own
# HOTFIX FOLLOW-UP comment - missing that sync once already caused ~13h
# with zero signals in production).
ML_BUY_SCORE_THRESHOLD = _env_int("ML_BUY_SCORE_THRESHOLD", 75) or 75
ML_SELL_SCORE_THRESHOLD = _env_int("ML_SELL_SCORE_THRESHOLD", 25) or 25
SCANNER_TIMEFRAME = _env_str("SCANNER_TIMEFRAME", "1m") or "1m"
SCANNER_COOLDOWN_SECONDS = _env_int("SCANNER_COOLDOWN_SECONDS", 300)
SCANNER_BATCH_SIZE = _env_int("SCANNER_BATCH_SIZE", 8) or 8
SCANNER_MANUAL_PRIORITY_WINDOW_SECONDS = _env_int("SCANNER_MANUAL_PRIORITY_WINDOW_SECONDS", 20) or 20
SCANNER_RATE_LIMIT_PAUSE_SECONDS = _env_int("SCANNER_RATE_LIMIT_PAUSE_SECONDS", 180) or 180
# Dedicated, faster crypto scan cadence (2026-08-17, per external
# consultation): the main "scanner" loop (60s tick) rotates ALL enabled
# categories - forex (active sessions only), crypto, commodities, watchlist -
# through ONE shared SCANNER_BATCH_SIZE-sized batch per tick. Crypto trades
# 24/7 with no session gating, so mixed into that one rotation it can go
# ~10+ minutes between rescans of the same pair (e.g. ~85 total assets /
# batch 8 = ~11 ticks x 60s). This gives crypto its OWN loop (see app.py's
# _start_loop("scanner_crypto", ...)) and its own rotating cursor, so each
# crypto pair gets rescanned roughly every ceil(len(CRYPTO_PAIRS) /
# SCANNER_CRYPTO_BATCH_SIZE) * SCANNER_CRYPTO_INTERVAL_SECONDS - with the
# defaults below (38 pairs, batch 8, 20s) that's ~100s instead of ~11min.
#
# Rate-limit safety: this does NOT raise the actual request rate to
# cTrader - analysis.py's MARKET_DATA_MAX_CONCURRENT_REQUESTS/
# MARKET_DATA_REQUEST_INTERVAL_MS (a single shared semaphore + pacing gate
# ALL scanning, including this loop, funnels through) already caps that at
# ~1 request/400ms regardless of how many logical loops call it. A faster
# crypto cadence just means crypto pairs get a larger share of that same
# fixed, already-safe budget, interleaved with forex/watchlist - it cannot
# by itself trigger RATE_LIMIT_BLOCKED/REQUEST_FREQUENCY_EXCEEDED.
SCANNER_CRYPTO_INTERVAL_SECONDS = _env_float("SCANNER_CRYPTO_INTERVAL_SECONDS", 20.0)
SCANNER_CRYPTO_BATCH_SIZE = _env_int("SCANNER_CRYPTO_BATCH_SIZE", 8) or 8
ANALYSIS_CACHE_TTL_SECONDS = _env_int("ANALYSIS_CACHE_TTL_SECONDS", 20) or 20
MARKET_DATA_CACHE_TTL_SECONDS = _env_int("MARKET_DATA_CACHE_TTL_SECONDS", 20) or 20
MARKET_DATA_REQUEST_INTERVAL_MS = _env_int("MARKET_DATA_REQUEST_INTERVAL_MS", 400) or 400
MARKET_DATA_MAX_CONCURRENT_REQUESTS = _env_int("MARKET_DATA_MAX_CONCURRENT_REQUESTS", 1) or 1
MIN_ATR_PERCENTAGE = _env_float("MIN_ATR_PERCENTAGE", 0.05)
# "Monday signal drought" fix (2026-08-17, per external consultation) -
# see CLAUDE.md and get_market_data's own comment (analysis.py) for the
# full incident: get_market_data's lookback window is fixed calendar
# time, so right after a weekend forex closure it mostly covers closed-
# market time and comes back short of the bars _run_technical_analysis
# needs (confirmed live: 177 of 300 requested 5m bars), which then
# silently suppresses signals bot-wide for hours. Widens the window by
# this factor on Saturday/Sunday/Monday (UTC) only - every other weekday
# keeps the normal, un-widened window.
MARKET_DATA_WEEKEND_LOOKBACK_MULTIPLIER = _env_float("MARKET_DATA_WEEKEND_LOOKBACK_MULTIPLIER", 3.5)

# Entry-drift block (audit fix, 2026-08-15): how much price is allowed to
# have moved between the signal's own price and the live price before a
# trade is blocked as "already moved against you". Used to be ONE flat
# 0.005% for every instrument analysis.py scans - forex, crypto,
# commodities, stocks - despite their typical per-second volatility
# differing by orders of magnitude (0.005% of a BTCUSD price near $60k is
# ~$3, a move that can happen within the seconds _analysis_flow takes to
# fetch data and run the model; the same 0.005% is a much rarer, more
# meaningful move for a calm forex major). A single threshold silently
# suppressed far more valid crypto/commodity signals than forex ones,
# indistinguishable from "the strategy doesn't work for those instruments".
# See classify_instrument_class/entry_drift_percent_for_pair below (defined
# after CRYPTO_PAIRS/COMMODITIES/STOCK_TICKERS, which they depend on).
#
# These per-class values are a first approximation, NOT empirically tuned -
# scaled roughly by typical relative volatility (crypto and commodities
# move a lot more per unit time than forex majors), pending real
# observation of how often each class's threshold actually fires once live.
MAX_ENTRY_DRIFT_PERCENT_FOREX = _env_float("MAX_ENTRY_DRIFT_PERCENT_FOREX", 0.005)
MAX_ENTRY_DRIFT_PERCENT_CRYPTO = _env_float("MAX_ENTRY_DRIFT_PERCENT_CRYPTO", 0.05)
MAX_ENTRY_DRIFT_PERCENT_COMMODITIES = _env_float("MAX_ENTRY_DRIFT_PERCENT_COMMODITIES", 0.02)
MAX_ENTRY_DRIFT_PERCENT_STOCKS = _env_float("MAX_ENTRY_DRIFT_PERCENT_STOCKS", 0.015)

# HOTFIX (2026-08-17, critical, active-incident): confirmed live in
# production - EURUSD BUY signals on the 5m timeframe were repeatedly
# recorded/broadcast with entry_price stuck at exactly 1.10000 (score
# always 80) while the pair's real live price was ~1.158, a ~4.3%
# divergence between the trendbar-derived signal price and the live tick
# price that should be near-identical at generation time. The exact root
# cause (which of the two price sources is wrong, and why) was NOT
# conclusively pinned down after investigation - this is a defense-in-depth
# PLAUSIBILITY check, not a root-cause fix: signal_tracking.py rejects
# (and alerts on) any signal whose entry_price and live-tick mid diverge
# by more than this percent, since two sources both claiming to represent
# "right now" should never differ this much for any instrument class.
# 2% is deliberately generous - well above normal same-instant bid-ask/
# timing noise for any pair this bot scans, comfortably below the ~4.3%
# divergence that exposed the incident.
SIGNAL_PRICE_SANITY_MAX_DIVERGENCE_PERCENT = _env_float("SIGNAL_PRICE_SANITY_MAX_DIVERGENCE_PERCENT", 2.0)

# Signal outcome tracking (Part 1, legacy TP/SL fields — kept only so old
# rows/paths don't break; no longer used to size new tracking).
SIGNAL_TP_ATR_MULTIPLIER = _env_float("SIGNAL_TP_ATR_MULTIPLIER", 1.5)
SIGNAL_SL_ATR_MULTIPLIER = _env_float("SIGNAL_SL_ATR_MULTIPLIER", 1.0)
SIGNAL_OUTCOME_TIMEOUT_HOURS = _env_float("SIGNAL_OUTCOME_TIMEOUT_HOURS", 4.0)

# backtest.py (standalone, one-shot, local-only script — see its own
# docstring) - reuses SIGNAL_TP_ATR_MULTIPLIER/SIGNAL_SL_ATR_MULTIPLIER
# above for TP/SL sizing, these are just its own defaults.
BACKTEST_DEFAULT_POSITION_SIZE = _env_float("BACKTEST_DEFAULT_POSITION_SIZE", 1000.0)
# AUDIT FIX (2026-08-16, high): spread used to be derived from a "pip",
# via 10.0/resolve_price_divisor(symbol_details) - that assumes the
# traditional pip convention (0.0001 for majors, 0.01 for JPY pairs)
# follows directly from the broker's quoting precision (digits). Live-
# confirmed this broker quotes JPY pairs at 5 digits too (same as
# majors), so that formula understated JPY spread by ~100x while
# simultaneously overstating it for pairs whose M1 ATR is small relative
# to a flat pip cost. Expressing spread as a FRACTION OF ATR sidesteps
# the pip-convention question entirely, since ATR is already computed in
# raw price units with no currency-specific ambiguity. 0.1 (10% of the
# M1 ATR at entry) is a first-approximation default, not empirically
# tuned - same disclosure as MAX_ENTRY_DRIFT_PERCENT_* above.
BACKTEST_DEFAULT_SPREAD_ATR_FRACTION = _env_float("BACKTEST_DEFAULT_SPREAD_ATR_FRACTION", 0.1)
# Safety cap, not a feature: the user explicitly wants NO artificial
# timeout-close, but a signal whose TP/SL genuinely never resolves must
# still stop pulling forward data somewhere rather than paginate
# indefinitely. Trades still open past this are reported as "still open",
# not force-closed at this cutoff - see backtest.py's walk-forward loop.
BACKTEST_MAX_FORWARD_DAYS = _env_int("BACKTEST_MAX_FORWARD_DAYS", 90) or 90

# Signal outcome tracking (binary-option style): how often the resolver
# loop checks pending signals whose horizon has elapsed, and how big a
# price move (as % of entry price) counts as noise ("flat") rather than a
# real up/down move.
SIGNAL_OUTCOME_CHECK_INTERVAL_MINUTES = _env_float("SIGNAL_OUTCOME_CHECK_INTERVAL_MINUTES", 1.0)
SIGNAL_OUTCOME_FLAT_THRESHOLD_PERCENT = _env_float("SIGNAL_OUTCOME_FLAT_THRESHOLD_PERCENT", 0.02)

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

# Part 3: Binomo binary-option executor (browser automation, Playwright).
# Disabled by default. Meant to run LOCALLY (see binomo_executor.py docstring
# and README) — not on Fly.io. BINOMO_ACCOUNT_MODE has no runtime toggle
# anywhere in this codebase; switching to 'live' is a manual env edit only.
BINOMO_EXECUTOR_ENABLED = _env_bool("BINOMO_EXECUTOR_ENABLED", False)
BINOMO_ACCOUNT_MODE = (_env_str("BINOMO_ACCOUNT_MODE", "demo") or "demo").strip().lower()
if BINOMO_ACCOUNT_MODE not in {"demo", "live"}:
    logger.warning("Unsupported BINOMO_ACCOUNT_MODE=%r. Falling back to 'demo'.", BINOMO_ACCOUNT_MODE)
    BINOMO_ACCOUNT_MODE = "demo"

if BINOMO_EXECUTOR_ENABLED and BINOMO_ACCOUNT_MODE == "live":
    logger.critical(
        "BINOMO_EXECUTOR_ENABLED=true with BINOMO_ACCOUNT_MODE=live — the "
        "executor will place REAL binary-option trades with REAL money on Binomo."
    )
elif BINOMO_EXECUTOR_ENABLED:
    logger.warning("BINOMO_EXECUTOR_ENABLED=true (mode=demo) — executor will place demo-account trades.")

# Fixed stake as % of account balance — no martingale/progression, ever.
BINOMO_STAKE_PERCENT = _env_float("BINOMO_STAKE_PERCENT", 1.0)

# Per-pair stake weighting (POLICY, 2026-08-12) - binomo_executor multiplies
# BINOMO_STAKE_PERCENT by one of these, chosen by the PAIR'S OWN trailing
# 30-day Binomo-style (no flat) win rate, recomputed fresh before every
# trade from independent historical data. This is NOT martingale: martingale
# reacts to THIS pair's own immediately-preceding win/loss and increases
# stake to chase a recovery - explicitly forbidden in this project (see
# CLAUDE.md). This never increases stake after a loss and never looks at
# trade sequence at all, only at a rolling win-rate snapshot; a losing
# streak lowers the tier like any other drop in win rate, it doesn't raise
# it. Replaces a hardcoded pair-exclusion list with a continuous scale, so
# a pair doesn't need code changes to fall out of (or back into) rotation.
BINOMO_STAKE_WEIGHT_MIN_TRADES = _env_int("BINOMO_STAKE_WEIGHT_MIN_TRADES", 20) or 20
BINOMO_STAKE_WEIGHT_DEFAULT = _env_float("BINOMO_STAKE_WEIGHT_DEFAULT", 0.5)
# Win-rate tier floors (%) and their stake multipliers, checked high to low.
BINOMO_STAKE_WEIGHT_TIER_HIGH_WINRATE = _env_float("BINOMO_STAKE_WEIGHT_TIER_HIGH_WINRATE", 80.0)
BINOMO_STAKE_WEIGHT_TIER_HIGH = _env_float("BINOMO_STAKE_WEIGHT_TIER_HIGH", 1.0)
BINOMO_STAKE_WEIGHT_TIER_MID_WINRATE = _env_float("BINOMO_STAKE_WEIGHT_TIER_MID_WINRATE", 65.0)
BINOMO_STAKE_WEIGHT_TIER_MID = _env_float("BINOMO_STAKE_WEIGHT_TIER_MID", 0.7)
# ~100/(100+80): breakeven win rate at an 80%-payout binary option.
BINOMO_STAKE_WEIGHT_TIER_BREAKEVEN_WINRATE = _env_float("BINOMO_STAKE_WEIGHT_TIER_BREAKEVEN_WINRATE", 55.6)
BINOMO_STAKE_WEIGHT_TIER_BREAKEVEN = _env_float("BINOMO_STAKE_WEIGHT_TIER_BREAKEVEN", 0.4)
BINOMO_STAKE_WEIGHT_TIER_LOW = _env_float("BINOMO_STAKE_WEIGHT_TIER_LOW", 0.0)

BINOMO_MAX_TRADES_PER_DAY = _env_int("BINOMO_MAX_TRADES_PER_DAY", 10) or 10
# Kill switch: stop and require /binomo_on after this many losses in a row.
BINOMO_MAX_CONSECUTIVE_LOSSES = _env_int("BINOMO_MAX_CONSECUTIVE_LOSSES", 4) or 4
BINOMO_MAX_DAILY_LOSS_PERCENT = _env_float("BINOMO_MAX_DAILY_LOSS_PERCENT", 5.0)

# POLICY (2026-08-13, user decision): every periodic check the executor
# runs on its own (not in direct response to a signal) must wait a FRESH
# random delay each time, drawn between a min/max bound, rather than a
# fixed interval - a fixed period is a regular, detectable automation
# signature; a range is not. Applies to: checking pending trades for a
# settled result (_resolve_due_trades - was running on every single main
# loop pass, ~every 2s, regardless of whether anything was even due),
# refreshing the watchlist by live payout, and re-verifying the login
# session is still valid. See binomo_executor._RandomizedInterval.
BINOMO_RESOLVE_CHECK_MIN_INTERVAL_SECONDS = _env_float("BINOMO_RESOLVE_CHECK_MIN_INTERVAL_SECONDS", 45.0)
BINOMO_RESOLVE_CHECK_MAX_INTERVAL_SECONDS = _env_float("BINOMO_RESOLVE_CHECK_MAX_INTERVAL_SECONDS", 90.0)
BINOMO_WATCHLIST_REFRESH_MIN_INTERVAL_SECONDS = _env_float("BINOMO_WATCHLIST_REFRESH_MIN_INTERVAL_SECONDS", 3000.0)
BINOMO_WATCHLIST_REFRESH_MAX_INTERVAL_SECONDS = _env_float("BINOMO_WATCHLIST_REFRESH_MAX_INTERVAL_SECONDS", 4200.0)
BINOMO_SESSION_RECHECK_MIN_INTERVAL_SECONDS = _env_float("BINOMO_SESSION_RECHECK_MIN_INTERVAL_SECONDS", 3000.0)
BINOMO_SESSION_RECHECK_MAX_INTERVAL_SECONDS = _env_float("BINOMO_SESSION_RECHECK_MAX_INTERVAL_SECONDS", 4200.0)

# Playwright session/login. Credentials are only used to (re)create
# storage_state.json via the one-time manual login helper — never hardcoded,
# never sent anywhere but binomo.com's own login form.
BINOMO_EMAIL = _env_str("BINOMO_EMAIL")
BINOMO_PASSWORD = _env_str("BINOMO_PASSWORD")
BINOMO_STORAGE_STATE_PATH = _env_str("BINOMO_STORAGE_STATE_PATH", "storage_state.json") or "storage_state.json"
# Headful by default: headless browsers are more readily fingerprinted by
# anti-automation checks, and this is meant to run on a local machine anyway.
BINOMO_HEADLESS = _env_bool("BINOMO_HEADLESS", False)
BINOMO_ASSET_MAP_PATH = _env_str("BINOMO_ASSET_MAP_PATH", "data/binomo_asset_map.json") or "data/binomo_asset_map.json"

# Minimum current Binomo payout (%) for a pair to stay in the auto-managed
# watchlist — see binomo_executor.refresh_watchlist_by_payout(). Payout
# drifts through the day/week (notably for weekend OTC assets), so this is
# re-checked periodically rather than applied once.
BINOMO_MIN_PAYOUT_PERCENT = _env_float("BINOMO_MIN_PAYOUT_PERCENT", 80.0)


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


_CRYPTO_KEYS = {normalize_symbol_key(p) for p in CRYPTO_PAIRS}
_COMMODITY_KEYS = {normalize_symbol_key(p) for p in COMMODITIES}
_STOCK_KEYS = {normalize_symbol_key(p) for p in STOCK_TICKERS}


def classify_instrument_class(pair: str) -> str:
    """"forex" | "crypto" | "commodities" | "stocks" - forex is the
    default/fallback for anything not found in the other three lists
    (matches how FOREX_SESSIONS already works as the catch-all currency-
    pair source elsewhere in this codebase, e.g. scanner.py)."""
    key = normalize_symbol_key(pair)
    if key in _CRYPTO_KEYS:
        return "crypto"
    if key in _COMMODITY_KEYS:
        return "commodities"
    if key in _STOCK_KEYS:
        return "stocks"
    return "forex"


_ENTRY_DRIFT_PERCENT_BY_CLASS = {
    "forex": MAX_ENTRY_DRIFT_PERCENT_FOREX,
    "crypto": MAX_ENTRY_DRIFT_PERCENT_CRYPTO,
    "commodities": MAX_ENTRY_DRIFT_PERCENT_COMMODITIES,
    "stocks": MAX_ENTRY_DRIFT_PERCENT_STOCKS,
}


def entry_drift_percent_for_pair(pair: str) -> float:
    return _ENTRY_DRIFT_PERCENT_BY_CLASS[classify_instrument_class(pair)]


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
