# db.py
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, create_engine, event, func, inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from config import DEV_USER_ID, SUBSCRIPTION_DAYS, TRIAL_HOURS, get_database_url
from session_times import DEFAULT_TIMEZONE, normalize_timezone

logger = logging.getLogger(__name__)

DATABASE_URL = get_database_url()

Base = declarative_base()

engine = None
SessionLocal = None
_fallback_watchlists: dict[int, set[str]] = {}
_fallback_user_languages: dict[int, str] = {}
_fallback_user_timezones: dict[int, str] = {}
_fallback_user_profiles: dict[int, dict] = {}
_fallback_lock = threading.RLock()


class SignalHistory(Base):
    __tablename__ = "signal_history"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    user_id = Column(Integer, nullable=True, index=True)
    pair = Column(String, nullable=False, index=True)
    price = Column(Float, nullable=True)
    bull_percentage = Column(Integer, nullable=True)


class UserWatchlist(Base):
    __tablename__ = "user_watchlist"

    user_id = Column(Integer, primary_key=True)
    pair = Column(String, primary_key=True)


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    language = Column(String(8), nullable=False, default="en")
    timezone = Column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    subscription_ends_at = Column(DateTime, nullable=True)
    plan_type = Column(String(16), nullable=False, default="free")
    subscription_status = Column(String(16), nullable=False, default="free")
    trial_used = Column(Boolean, nullable=False, default=False)
    subscription_end_date = Column(DateTime, nullable=True)


class PaymentInvoice(Base):
    __tablename__ = "payment_invoices"

    invoice_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    status = Column(String(16), nullable=False, default="paid")
    processed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id = Column(Integer, primary_key=True)
    language = Column(String(8), nullable=False, default="en")


class AppRuntimeSetting(Base):
    __tablename__ = "app_runtime_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class SignalOutcome(Base):
    # 2026-08-10: archived all pre-existing rows (112, a mix of data from
    # before and during the BUY/SELL-swap incident - see scanner.py's
    # HOTFIX FOLLOW-UP comment) to the "signal_outcomes_legacy_20260810"
    # table (CSV snapshot in data/) and started this table fresh, so
    # /api/stats/signals and /winrate report win-rate computed only from
    # signals generated after every part of that fix was live. No code
    # change was needed here - both already just query this model, which
    # now resolves to the new table.
    __tablename__ = "signal_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String, nullable=False, index=True)
    timeframe = Column(String(8), nullable=False, default="")
    verdict = Column(String(8), nullable=False)
    score = Column(Integer, nullable=True)
    entry_price = Column(Float, nullable=False)
    entry_ts = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    # Legacy forex/ATR-based fields (previous TP/SL tracking generation).
    # Kept so old rows don't break on read; no longer written for new rows.
    tp_price = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=True)
    pnl_pips = Column(Float, nullable=True)
    # Binary-option-style tracking: did price move the predicted direction
    # over a fixed horizon, rather than hit a TP/SL level.
    horizon_seconds = Column(Integer, nullable=True)
    exit_price = Column(Float, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    # 'pending' | 'up' | 'down' | 'flat' (legacy rows may still have 'tp' | 'sl' | 'timeout')
    outcome = Column(String(16), nullable=False, default="pending", index=True)


class AutoTrade(Base):
    __tablename__ = "auto_trades"

    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String, nullable=False, index=True)
    direction = Column(String(8), nullable=False)  # BUY | SELL
    volume = Column(Integer, nullable=False)  # cTrader volume units (already x100)
    entry_price = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    ts = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    account_mode = Column(String(8), nullable=False, index=True)  # demo | live
    broker_order_id = Column(String(32), nullable=True, index=True)
    broker_position_id = Column(String(32), nullable=True, index=True)
    # submitted -> open -> closed_tp | closed_sl | closed_manual | error
    status = Column(String(16), nullable=False, default="submitted", index=True)
    pnl_amount = Column(Float, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    error_message = Column(String(255), nullable=True)


class BinomoTrade(Base):
    __tablename__ = "binomo_trades"

    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String, nullable=False, index=True)  # Binomo asset name (data/binomo_asset_map.json)
    pair = Column(String, nullable=True, index=True)  # originating cTrader pair, if any
    direction = Column(String(8), nullable=False)  # up | down
    amount = Column(Float, nullable=False)  # stake, account currency
    expiry_seconds = Column(Integer, nullable=False)
    entry_ts = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    account_mode = Column(String(8), nullable=False, index=True)  # demo | live
    # pending -> win | loss | error
    result = Column(String(16), nullable=False, default="pending", index=True)
    payout_amount = Column(Float, nullable=True)  # net profit/loss once resolved
    resolved_at = Column(DateTime, nullable=True)
    signal_outcome_id = Column(Integer, nullable=True, index=True)
    error_message = Column(String(255), nullable=True)


def _normalize_language(lang: str | None) -> str:
    value = (lang or "").split(",", 1)[0].split("-")[0].split("_")[0].lower()
    return value if value in {"en", "uk", "es", "de", "ru"} else "en"


def _normalize_timezone(value: str | None) -> str:
    return normalize_timezone(value)


def _normalize_plan(plan_type: str | None) -> str:
    value = (plan_type or "free").strip().lower()
    return value if value in {"free", "pro"} else "free"


def _normalize_subscription_status(status: str | None) -> str:
    value = (status or "free").strip().lower()
    return value if value in {"free", "trial", "active"} else "free"


def is_admin_user(user_id: int | str | None) -> bool:
    try:
        return bool(DEV_USER_ID) and int(user_id or 0) == int(DEV_USER_ID)
    except (TypeError, ValueError):
        return False


def _normalize_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Invalid subscription datetime: %r", value)
            return None
    else:
        logger.warning("Unsupported subscription datetime type: %r", type(value))
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _subscription_active(plan_type: str, subscription_ends_at: datetime | None) -> bool:
    plan_type = _normalize_plan(plan_type)
    if plan_type != "pro":
        return False
    return subscription_ends_at is None or subscription_ends_at > _utcnow()


def _status_active(status: str, subscription_end_date: datetime | None) -> bool:
    status = _normalize_subscription_status(status)
    if status not in {"trial", "active"}:
        return False
    return subscription_end_date is None or subscription_end_date > _utcnow()


def _user_to_status(user: User | None, fallback_language: str | None = None) -> dict:
    user_id = int(getattr(user, "user_id", 0) or 0)
    lang = _normalize_language(getattr(user, "language", None) or fallback_language)
    tz = _normalize_timezone(getattr(user, "timezone", None))
    plan = _normalize_plan(getattr(user, "plan_type", None))
    legacy_ends_at = getattr(user, "subscription_ends_at", None)
    status = _normalize_subscription_status(getattr(user, "subscription_status", None))
    end_date = getattr(user, "subscription_end_date", None) or legacy_ends_at
    trial_used = bool(getattr(user, "trial_used", False))

    legacy_active = _subscription_active(plan, legacy_ends_at)
    if status == "free" and legacy_active:
        status = "active"
        end_date = legacy_ends_at

    active = _status_active(status, end_date)
    admin = is_admin_user(user_id)
    if admin:
        plan = "pro"
        status = "active"
        end_date = None
        active = True

    return {
        "user_id": user_id,
        "language": lang,
        "timezone": tz,
        "plan_type": plan,
        "subscription_status": status,
        "trial_used": trial_used,
        "subscription_end_date": _dt_to_iso(end_date),
        "subscription_ends_at": _dt_to_iso(end_date),
        "is_pro": active,
        "is_admin": admin,
        "access_allowed": active,
        "has_active_subscription": active,
    }


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:")


def _build_engine(url: str):
    kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "future": True,
    }

    if _is_sqlite_url(url):
        kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }

    return create_engine(url, **kwargs)


def _configure_sqlite_pragmas(sqlalchemy_engine) -> None:
    @event.listens_for(sqlalchemy_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.execute("PRAGMA temp_store=MEMORY;")
        finally:
            cursor.close()


if not DATABASE_URL:
    logger.critical("DATABASE_URL is not set.")
else:
    try:
        engine = _build_engine(DATABASE_URL)
        if _is_sqlite_url(DATABASE_URL):
            _configure_sqlite_pragmas(engine)

        SessionLocal = scoped_session(
            sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=engine,
                expire_on_commit=False,
                future=True,
            )
        )
        logger.info("Database engine initialized.")
    except Exception as e:
        logger.critical(f"Failed to create database engine: {e}", exc_info=True)
        engine = None
        SessionLocal = None


@contextmanager
def get_db():
    if SessionLocal is None:
        yield None
        return

    session = SessionLocal()
    try:
        yield session
    finally:
        try:
            session.close()
        finally:
            SessionLocal.remove()


@contextmanager
def session_scope():
    if SessionLocal is None:
        yield None
        return

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            session.close()
        finally:
            SessionLocal.remove()


def initialize_database():
    if engine is None:
        logger.warning("Database engine is not initialized. Skipping create_all.")
        return

    try:
        Base.metadata.create_all(bind=engine)
        _ensure_user_columns()
        _ensure_signal_outcome_columns()
        logger.info("Database initialization complete.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}", exc_info=True)


def _ensure_user_columns() -> None:
    try:
        inspector = inspect(engine)
        existing = {column["name"] for column in inspector.get_columns("users")}
        statements = []

        if "timezone" not in existing:
            statements.append(f"ALTER TABLE users ADD COLUMN timezone VARCHAR(64) DEFAULT '{DEFAULT_TIMEZONE}' NOT NULL")
        if "subscription_status" not in existing:
            statements.append("ALTER TABLE users ADD COLUMN subscription_status VARCHAR(16) DEFAULT 'free' NOT NULL")
        if "trial_used" not in existing:
            statements.append("ALTER TABLE users ADD COLUMN trial_used BOOLEAN DEFAULT FALSE NOT NULL")
        if "subscription_end_date" not in existing:
            statements.append("ALTER TABLE users ADD COLUMN subscription_end_date TIMESTAMP NULL")

        if not statements:
            return

        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

        logger.info("Database users table migrated: %s", ", ".join(statements))
    except Exception:
        logger.exception("Could not ensure users table columns")


def _ensure_signal_outcome_columns() -> None:
    """Adds the horizon-based tracking columns to a signal_outcomes table
    created by an earlier (TP/SL-based) version of this model. Additive
    only - never drops the legacy tp_price/sl_price/pnl_pips columns, so
    old rows and old code paths keep working."""
    try:
        inspector = inspect(engine)
        if "signal_outcomes" not in inspector.get_table_names():
            return

        existing = {column["name"] for column in inspector.get_columns("signal_outcomes")}
        statements = []

        if "horizon_seconds" not in existing:
            statements.append("ALTER TABLE signal_outcomes ADD COLUMN horizon_seconds INTEGER NULL")
        if "exit_price" not in existing:
            statements.append("ALTER TABLE signal_outcomes ADD COLUMN exit_price FLOAT NULL")

        if not statements:
            return

        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

        logger.info("Database signal_outcomes table migrated: %s", ", ".join(statements))
    except Exception:
        logger.exception("Could not ensure signal_outcomes table columns")


def _set_runtime_setting(session, key: str, value: str | None) -> None:
    row = session.query(AppRuntimeSetting).filter(AppRuntimeSetting.key == key).first()
    if row is None:
        row = AppRuntimeSetting(key=key)
        session.add(row)
    row.value = value
    row.updated_at = _utcnow()


def _get_runtime_setting(session, key: str) -> str | None:
    row = session.query(AppRuntimeSetting).filter(AppRuntimeSetting.key == key).first()
    return None if row is None else row.value


def get_ctrader_token_bundle() -> dict | None:
    try:
        with get_db() as db:
            if db is None:
                return None

            access_token = _get_runtime_setting(db, "ctrader_access_token")
            refresh_token = _get_runtime_setting(db, "ctrader_refresh_token")
            expires_at_raw = _get_runtime_setting(db, "ctrader_access_token_expires_at")
            expires_at = _normalize_datetime(expires_at_raw)

            if not access_token and not refresh_token:
                return None

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
            }
    except SQLAlchemyError:
        logger.exception("Error loading persisted cTrader token bundle")
        return None


def persist_ctrader_token_bundle(
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
) -> bool:
    try:
        with session_scope() as db:
            if db is None:
                return False

            if access_token is not None:
                _set_runtime_setting(db, "ctrader_access_token", access_token)
            if refresh_token is not None:
                _set_runtime_setting(db, "ctrader_refresh_token", refresh_token)
            if expires_at is not None:
                _set_runtime_setting(db, "ctrader_access_token_expires_at", _dt_to_iso(expires_at))
            elif access_token is not None or refresh_token is not None:
                _set_runtime_setting(db, "ctrader_access_token_expires_at", None)
            return True
    except SQLAlchemyError:
        logger.exception("Error persisting cTrader token bundle")
        return False


def add_signal_to_history(data: dict) -> bool:
    if not data:
        return False

    try:
        with session_scope() as db:
            if db is None:
                return False

            new_signal = SignalHistory(
                user_id=data.get("user_id"),
                pair=(data.get("pair") or "").strip(),
                price=data.get("price"),
                bull_percentage=data.get("bull_percentage"),
            )
            db.add(new_signal)
            return True
    except SQLAlchemyError:
        logger.exception("Error adding signal to history")
        return False


def _fallback_get_watchlist(user_id: int) -> list[str]:
    with _fallback_lock:
        return sorted(_fallback_watchlists.get(int(user_id), set()))


def _fallback_get_user_language(user_id: int) -> str | None:
    with _fallback_lock:
        return _fallback_user_languages.get(int(user_id))


def _fallback_get_user_timezone(user_id: int) -> str | None:
    with _fallback_lock:
        return _fallback_user_timezones.get(int(user_id))


def _fallback_set_user_language(user_id: int, lang: str, *, log_warning: bool = True) -> str:
    lang = _normalize_language(lang)
    with _fallback_lock:
        _fallback_user_languages[int(user_id)] = lang
        profile = _fallback_user_profiles.setdefault(
            int(user_id),
            {
                "user_id": int(user_id),
                "language": lang,
                "timezone": _fallback_user_timezones.get(int(user_id), DEFAULT_TIMEZONE),
                "plan_type": "free",
                "subscription_status": "free",
                "trial_used": False,
                "subscription_end_date": None,
                "subscription_ends_at": None,
                "is_pro": is_admin_user(user_id),
                "is_admin": is_admin_user(user_id),
                "access_allowed": is_admin_user(user_id),
                "has_active_subscription": is_admin_user(user_id),
            },
        )
        profile["language"] = lang
    if log_warning:
        logger.warning("Використано резервне збереження мови для user_id=%s lang=%s", user_id, lang)
    return lang


def _fallback_set_user_timezone(user_id: int, timezone_name: str, *, log_warning: bool = True) -> str:
    tz = _normalize_timezone(timezone_name)
    with _fallback_lock:
        _fallback_user_timezones[int(user_id)] = tz
        profile = _fallback_user_profiles.setdefault(
            int(user_id),
            {
                "user_id": int(user_id),
                "language": _fallback_user_languages.get(int(user_id), "en"),
                "timezone": tz,
                "plan_type": "free",
                "subscription_status": "free",
                "trial_used": False,
                "subscription_end_date": None,
                "subscription_ends_at": None,
                "is_pro": is_admin_user(user_id),
                "is_admin": is_admin_user(user_id),
                "access_allowed": is_admin_user(user_id),
                "has_active_subscription": is_admin_user(user_id),
            },
        )
        profile["timezone"] = tz
    if log_warning:
        logger.warning("Використано резервне збереження timezone для user_id=%s timezone=%s", user_id, tz)
    return tz


def _fallback_get_user_status(user_id: int) -> dict | None:
    with _fallback_lock:
        profile = _fallback_user_profiles.get(int(user_id))
        if profile:
            return dict(profile)

        lang = _fallback_user_languages.get(int(user_id))
        tz = _fallback_user_timezones.get(int(user_id), DEFAULT_TIMEZONE)
        if not lang and not tz:
            return None

        return {
            "user_id": int(user_id),
            "language": lang or "en",
            "timezone": tz,
            "plan_type": "free",
            "subscription_status": "free",
            "trial_used": False,
            "subscription_end_date": None,
            "subscription_ends_at": None,
            "is_pro": is_admin_user(user_id),
            "is_admin": is_admin_user(user_id),
            "access_allowed": is_admin_user(user_id),
            "has_active_subscription": is_admin_user(user_id),
        }


def _fallback_set_user_subscription(
    user_id: int,
    plan_type: str,
    subscription_ends_at=None,
    language: str | None = None,
    *,
    log_warning: bool = True,
) -> dict:
    plan = _normalize_plan(plan_type)
    ends_at = _normalize_datetime(subscription_ends_at)
    lang = _normalize_language(language or _fallback_get_user_language(user_id))
    tz = _normalize_timezone(_fallback_get_user_timezone(user_id))
    admin = is_admin_user(user_id)
    status = "active" if plan == "pro" else "free"
    active = admin or _status_active(status, ends_at)
    profile = {
        "user_id": int(user_id),
        "language": lang,
        "timezone": tz,
        "plan_type": "pro" if admin else plan,
        "subscription_status": "active" if admin else status,
        "trial_used": False,
        "subscription_end_date": None if admin else _dt_to_iso(ends_at),
        "subscription_ends_at": None if admin else _dt_to_iso(ends_at),
        "is_pro": active,
        "is_admin": admin,
        "access_allowed": active,
        "has_active_subscription": active,
    }
    with _fallback_lock:
        _fallback_user_profiles[int(user_id)] = profile
        _fallback_user_languages[int(user_id)] = lang
        _fallback_user_timezones[int(user_id)] = tz
    if log_warning:
        logger.warning("Використано резервне збереження підписки для user_id=%s plan=%s", user_id, plan)
    return dict(profile)


def _fallback_set_watchlist(user_id: int, pairs: list[str]) -> list[str]:
    normalized = {pair.strip().upper() for pair in pairs if pair}
    with _fallback_lock:
        _fallback_watchlists[int(user_id)] = normalized
        return sorted(normalized)


def _fallback_toggle_watchlist(user_id: int, pair: str) -> bool:
    pair = pair.strip().upper()
    with _fallback_lock:
        items = _fallback_watchlists.setdefault(int(user_id), set())
        if pair in items:
            items.remove(pair)
        else:
            items.add(pair)
    logger.warning("Використано резервне обране для user_id=%s pair=%s", user_id, pair)
    return True


def _fallback_add_watchlist(user_id: int, pair: str) -> bool:
    pair = pair.strip().upper()
    with _fallback_lock:
        _fallback_watchlists.setdefault(int(user_id), set()).add(pair)
    logger.warning("Використано резервне додавання в обране для user_id=%s pair=%s", user_id, pair)
    return True


def _fallback_remove_watchlist(user_id: int, pair: str) -> bool:
    pair = pair.strip().upper()
    with _fallback_lock:
        _fallback_watchlists.setdefault(int(user_id), set()).discard(pair)
    logger.warning("Використано резервне видалення з обраного для user_id=%s pair=%s", user_id, pair)
    return True


def get_watchlist(user_id: int) -> list[str]:
    if not user_id:
        return []

    try:
        with get_db() as db:
            if db is None:
                return []

            rows = (
                db.query(UserWatchlist)
                .filter(UserWatchlist.user_id == int(user_id))
                .order_by(UserWatchlist.pair.asc())
                .all()
            )
            pairs = [row.pair for row in rows]
            fallback_pairs = _fallback_get_watchlist(user_id)
            if fallback_pairs:
                pairs = sorted(set(pairs) | set(fallback_pairs))
            return pairs
    except SQLAlchemyError:
        logger.exception("Error loading watchlist")
        return _fallback_get_watchlist(user_id)


def is_in_watchlist(user_id: int, pair: str) -> bool:
    if not user_id or not pair:
        return False

    pair = pair.strip().upper()

    try:
        with get_db() as db:
            if db is None:
                return False

            row = (
                db.query(UserWatchlist)
                .filter(
                    UserWatchlist.user_id == int(user_id),
                    UserWatchlist.pair == pair,
                )
                .first()
            )
            return row is not None
    except SQLAlchemyError:
        logger.exception("Error checking watchlist membership")
        return False


def check_database_status() -> dict:
    fallback_count = 0
    with _fallback_lock:
        fallback_count = sum(len(items) for items in _fallback_watchlists.values())

    if engine is None:
        return {
            "ok": False,
            "label": "двигун бази не ініціалізований",
            "fallback_items": fallback_count,
        }

    try:
        with engine.connect() as conn:
            value = conn.execute(text("select 1")).scalar()
        return {
            "ok": value == 1,
            "label": "працює" if value == 1 else "неочікувана відповідь",
            "fallback_items": fallback_count,
        }
    except Exception as exc:
        logger.exception("Database status check failed")
        return {
            "ok": False,
            "label": f"помилка підключення: {type(exc).__name__}",
            "fallback_items": fallback_count,
        }


def get_user_language(user_id: int) -> str | None:
    status = get_cached_user_status(user_id)
    return status.get("language") if status else None


def get_user_timezone(user_id: int) -> str:
    status = get_cached_user_status(user_id)
    if status and status.get("timezone"):
        return _normalize_timezone(status.get("timezone"))
    return DEFAULT_TIMEZONE


def set_user_language(user_id: int, lang: str) -> str:
    lang = _normalize_language(lang)
    if not user_id:
        return lang

    status = None
    try:
        with session_scope() as db:
            if db is None:
                status = _fallback_set_user_subscription(user_id, "free", None, lang)
                _cache_user_status(user_id, status)
                return lang

            user = _get_or_create_user_row(db, user_id, language=lang)
            user.language = lang

            status = _user_to_status(user)
    except OperationalError:
        logger.exception("OperationalError while saving user language")
        status = _fallback_set_user_subscription(user_id, "free", None, lang)
    except SQLAlchemyError:
        logger.exception("Error saving user language")
        status = _fallback_set_user_subscription(user_id, "free", None, lang)

    _fallback_set_user_language(user_id, lang, log_warning=False)
    _cache_user_status(user_id, status)
    return lang


def set_user_timezone(user_id: int, timezone_name: str | None) -> str:
    tz = _normalize_timezone(timezone_name)
    if not user_id:
        return tz

    status = None
    try:
        with session_scope() as db:
            if db is None:
                _fallback_set_user_timezone(user_id, tz)
                status = _fallback_get_user_status(user_id)
                _cache_user_status(user_id, status)
                return tz

            user = _get_or_create_user_row(db, user_id)
            user.timezone = tz
            status = _user_to_status(user)
    except OperationalError:
        logger.exception("OperationalError while saving user timezone")
        _fallback_set_user_timezone(user_id, tz)
        status = _fallback_get_user_status(user_id)
    except SQLAlchemyError:
        logger.exception("Error saving user timezone")
        _fallback_set_user_timezone(user_id, tz)
        status = _fallback_get_user_status(user_id)

    _fallback_set_user_timezone(user_id, tz, log_warning=False)
    _cache_user_status(user_id, status)
    return tz


def _get_legacy_language(db, user_id: int) -> str | None:
    return None


def _get_or_create_user_row(db, user_id: int, language: str | None = None) -> User:
    user_id = int(user_id)
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is not None:
        if language and not user.language:
            user.language = _normalize_language(language)
        if not getattr(user, "timezone", None):
            user.timezone = _fallback_get_user_timezone(user_id) or DEFAULT_TIMEZONE
        return user

    lang = _normalize_language(language or _get_legacy_language(db, user_id) or _fallback_get_user_language(user_id))
    user = User(
        user_id=user_id,
        language=lang,
        timezone=_fallback_get_user_timezone(user_id) or DEFAULT_TIMEZONE,
        plan_type="free",
        subscription_ends_at=None,
        subscription_status="free",
        trial_used=False,
        subscription_end_date=None,
    )
    db.add(user)
    return user


def _cache_user_status(user_id: int, status: dict | None) -> dict | None:
    if not user_id or not status:
        return status
    try:
        from state import app_state
        return app_state.set_cached_user_status(user_id, status)
    except Exception:
        logger.debug("Could not update user status cache", exc_info=True)
        return status


def invalidate_user_status_cache(user_id: int) -> None:
    try:
        from state import app_state
        app_state.invalidate_user_status(user_id)
    except Exception:
        logger.debug("Could not invalidate user status cache", exc_info=True)


def get_cached_user_status(user_id: int, *, language_hint: str | None = None, max_age_seconds: int = 60) -> dict | None:
    if not user_id:
        return None

    try:
        from state import app_state
        cached = app_state.get_cached_user_status(user_id, max_age_seconds=max_age_seconds)
        if cached:
            return cached
    except Exception:
        logger.debug("Could not read user status cache", exc_info=True)

    status = get_user_status(user_id, language_hint=language_hint)
    return _cache_user_status(user_id, status)


def get_user_status(user_id: int, *, language_hint: str | None = None) -> dict | None:
    if not user_id:
        return None

    fallback_status = _fallback_get_user_status(user_id)

    try:
        with session_scope() as db:
            if db is None:
                return fallback_status or _fallback_set_user_subscription(user_id, "free", None, language_hint)

            user = _get_or_create_user_row(db, user_id, language=language_hint)
            status = _user_to_status(user)
            with _fallback_lock:
                _fallback_user_profiles[int(user_id)] = dict(status)
                _fallback_user_languages[int(user_id)] = status.get("language") or "en"
                _fallback_user_timezones[int(user_id)] = status.get("timezone") or DEFAULT_TIMEZONE
            return status
    except SQLAlchemyError:
        logger.exception("Error loading user status")
        return fallback_status or _fallback_set_user_subscription(user_id, "free", None, language_hint)


def set_user_subscription(user_id: int, plan_type: str = "free", subscription_ends_at=None, *, language: str | None = None) -> dict | None:
    if not user_id:
        return None

    plan = _normalize_plan(plan_type)
    ends_at = _normalize_datetime(subscription_ends_at)
    status = None

    try:
        with session_scope() as db:
            if db is None:
                status = _fallback_set_user_subscription(user_id, plan, ends_at, language)
                _cache_user_status(user_id, status)
                _notify_payment_at_risk("set_user_subscription_no_engine", user_id)
                return status

            user = _get_or_create_user_row(db, user_id, language=language)
            if language:
                user.language = _normalize_language(language)
            user.plan_type = plan
            user.subscription_ends_at = ends_at if plan == "pro" else None
            user.subscription_status = "active" if plan == "pro" else "free"
            user.subscription_end_date = ends_at if plan == "pro" else None
            status = _user_to_status(user)
    except OperationalError:
        logger.exception("OperationalError while saving user subscription")
        status = _fallback_set_user_subscription(user_id, plan, ends_at, language)
        _notify_payment_at_risk("set_user_subscription_operational_error", user_id)
    except SQLAlchemyError:
        logger.exception("Error saving user subscription")
        status = _fallback_set_user_subscription(user_id, plan, ends_at, language)
        _notify_payment_at_risk("set_user_subscription_sqlalchemy_error", user_id)

    _cache_user_status(user_id, status)
    return status


def _notify_subscription_event(text: str, key: str | None = None) -> None:
    try:
        from notifier import notify_admin

        notify_admin(text, alert_key=key)
    except Exception:
        logger.debug("Could not send subscription admin notification", exc_info=True)


def _notify_payment_at_risk(context: str, user_id: int) -> None:
    _notify_subscription_event(
        f"🚨 PAYMENT AT RISK: DB unavailable, subscription stored in-memory only\n"
        f"context: {context}\nuser_id: {user_id}\n"
        "This record will be LOST on restart unless the database recovers.",
        key=f"payment_at_risk_{context}",
    )


def start_user_trial(user_id: int, *, language: str | None = None) -> tuple[dict | None, bool]:
    if not user_id:
        return None, False

    if is_admin_user(user_id):
        return get_user_status(user_id, language_hint=language), True

    end_at = _utcnow() + timedelta(hours=max(1, int(TRIAL_HOURS or 24)))
    status = None
    activated = False

    try:
        with session_scope() as db:
            if db is None:
                profile = _fallback_get_user_status(user_id) or _fallback_set_user_subscription(user_id, "free", None, language)
                if profile.get("trial_used"):
                    return profile, False

                profile.update(
                    {
                        "plan_type": "pro",
                        "subscription_status": "trial",
                        "trial_used": True,
                        "subscription_end_date": _dt_to_iso(end_at),
                        "subscription_ends_at": _dt_to_iso(end_at),
                        "is_pro": True,
                        "access_allowed": True,
                        "has_active_subscription": True,
                    }
                )
                with _fallback_lock:
                    _fallback_user_profiles[int(user_id)] = dict(profile)
                _cache_user_status(user_id, profile)
                _notify_subscription_event(
                    f"🔥 Демо активовано\nuser_id: {user_id}\nдо: {_dt_to_iso(end_at)}",
                    key=f"trial_started_{user_id}",
                )
                return profile, True

            user = _get_or_create_user_row(db, user_id, language=language)
            if bool(getattr(user, "trial_used", False)):
                status = _user_to_status(user)
                return status, False

            if language:
                user.language = _normalize_language(language)
            user.subscription_status = "trial"
            user.trial_used = True
            user.subscription_end_date = end_at
            user.plan_type = "pro"
            user.subscription_ends_at = end_at
            status = _user_to_status(user)
            activated = True
    except SQLAlchemyError:
        logger.exception("Error starting trial for user_id=%s", user_id)
        return get_user_status(user_id, language_hint=language), False

    _cache_user_status(user_id, status)
    if activated:
        _notify_subscription_event(
            f"🔥 Демо активовано\nuser_id: {user_id}\nдо: {_dt_to_iso(end_at)}",
            key=f"trial_started_{user_id}",
        )
    return status, activated


def activate_paid_subscription(user_id: int, *, days: int | None = None, language: str | None = None) -> dict | None:
    if not user_id:
        return None

    if is_admin_user(user_id):
        return get_user_status(user_id, language_hint=language)

    days = max(1, int(days or SUBSCRIPTION_DAYS or 30))
    status = None

    try:
        with session_scope() as db:
            if db is None:
                current = _fallback_get_user_status(user_id) or _fallback_set_user_subscription(user_id, "free", None, language)
                current_end = _normalize_datetime(current.get("subscription_end_date") or current.get("subscription_ends_at"))
                base = current_end if current_end and current_end > _utcnow() else _utcnow()
                new_end = base + timedelta(days=days)
                current.update(
                    {
                        "plan_type": "pro",
                        "subscription_status": "active",
                        "subscription_end_date": _dt_to_iso(new_end),
                        "subscription_ends_at": _dt_to_iso(new_end),
                        "is_pro": True,
                        "access_allowed": True,
                        "has_active_subscription": True,
                    }
                )
                with _fallback_lock:
                    _fallback_user_profiles[int(user_id)] = dict(current)
                _cache_user_status(user_id, current)
                _notify_payment_at_risk("activate_paid_subscription_no_engine", user_id)
                return current

            user = _get_or_create_user_row(db, user_id, language=language)
            if language:
                user.language = _normalize_language(language)
            current_end = _normalize_datetime(getattr(user, "subscription_end_date", None) or getattr(user, "subscription_ends_at", None))
            base = current_end if current_end and current_end > _utcnow() else _utcnow()
            new_end = base + timedelta(days=days)
            user.subscription_status = "active"
            user.subscription_end_date = new_end
            user.plan_type = "pro"
            user.subscription_ends_at = new_end
            status = _user_to_status(user)
    except SQLAlchemyError:
        logger.exception("Error activating paid subscription for user_id=%s", user_id)
        _notify_payment_at_risk("activate_paid_subscription_sqlalchemy_error", user_id)
        return None

    return _cache_user_status(user_id, status)


def mark_payment_invoice_processed(invoice_id, user_id: int) -> bool:
    invoice_key = str(invoice_id or "").strip()
    if not invoice_key or not user_id:
        return False

    try:
        with session_scope() as db:
            if db is None:
                _notify_payment_at_risk("mark_payment_invoice_processed_no_engine", user_id)
                return True

            existing = db.query(PaymentInvoice).filter(PaymentInvoice.invoice_id == invoice_key).first()
            if existing is not None:
                return False

            db.add(
                PaymentInvoice(
                    invoice_id=invoice_key,
                    user_id=int(user_id),
                    status="paid",
                    processed_at=_utcnow(),
                )
            )
            return True
    except SQLAlchemyError:
        logger.exception("Error marking payment invoice as processed: %s", invoice_key)
        return False


def expire_user_access_if_needed(user_id: int, *, notify: bool = True, language_hint: str | None = None) -> dict | None:
    if not user_id:
        return None

    if is_admin_user(user_id):
        return get_user_status(user_id, language_hint=language_hint)

    status = None
    expired_trial_at = None

    try:
        with session_scope() as db:
            if db is None:
                status = _fallback_get_user_status(user_id) or _fallback_set_user_subscription(user_id, "free", None, language_hint)
                current_status = _normalize_subscription_status(status.get("subscription_status"))
                end_at = _normalize_datetime(status.get("subscription_end_date") or status.get("subscription_ends_at"))
                if current_status in {"trial", "active"} and end_at and end_at <= _utcnow():
                    if current_status == "trial":
                        expired_trial_at = end_at
                    status.update(
                        {
                            "plan_type": "free",
                            "subscription_status": "free",
                            "subscription_end_date": _dt_to_iso(end_at),
                            "subscription_ends_at": None,
                            "is_pro": False,
                            "access_allowed": False,
                            "has_active_subscription": False,
                        }
                    )
                    with _fallback_lock:
                        _fallback_user_profiles[int(user_id)] = dict(status)
                _cache_user_status(user_id, status)
                if notify and expired_trial_at:
                    _notify_subscription_event(
                        f"⏱ Демо завершилося\nuser_id: {user_id}\nбуло до: {_dt_to_iso(expired_trial_at)}",
                        key=f"trial_expired_{user_id}",
                    )
                return status

            user = _get_or_create_user_row(db, user_id, language=language_hint)
            current_status = _normalize_subscription_status(getattr(user, "subscription_status", None))
            end_at = _normalize_datetime(getattr(user, "subscription_end_date", None) or getattr(user, "subscription_ends_at", None))
            if current_status in {"trial", "active"} and end_at and end_at <= _utcnow():
                if current_status == "trial":
                    expired_trial_at = end_at
                user.subscription_status = "free"
                user.plan_type = "free"
                user.subscription_ends_at = None
                user.subscription_end_date = end_at
            status = _user_to_status(user)
    except SQLAlchemyError:
        logger.exception("Error expiring user access for user_id=%s", user_id)
        status = get_user_status(user_id, language_hint=language_hint)

    _cache_user_status(user_id, status)
    if notify and expired_trial_at:
        _notify_subscription_event(
            f"⏱ Демо завершилося\nuser_id: {user_id}\nбуло до: {_dt_to_iso(expired_trial_at)}",
            key=f"trial_expired_{user_id}",
        )
    return status


def get_user_access_status(user_id: int, *, language_hint: str | None = None, notify_expired: bool = True) -> dict | None:
    status = expire_user_access_if_needed(user_id, notify=notify_expired, language_hint=language_hint)
    if not status:
        return None

    allowed = bool(status.get("is_admin") or status.get("has_active_subscription") or status.get("is_pro"))
    status["access_allowed"] = allowed
    return status


def ensure_trial_or_access(user_id: int, *, language_hint: str | None = None) -> tuple[dict | None, bool]:
    status = get_user_access_status(user_id, language_hint=language_hint)
    if not status:
        return None, False

    if status.get("access_allowed"):
        return status, False

    if not status.get("trial_used"):
        return start_user_trial(user_id, language=language_hint)

    return status, False


def notify_new_user_once(user_id: int, *, language_hint: str | None = None) -> None:
    if not user_id or is_admin_user(user_id):
        return

    created = False
    try:
        with session_scope() as db:
            if db is None:
                with _fallback_lock:
                    created = int(user_id) not in _fallback_user_profiles
                if created:
                    _fallback_set_user_subscription(user_id, "free", None, language_hint, log_warning=False)
            else:
                existing = db.query(User).filter(User.user_id == int(user_id)).first()
                created = existing is None
                if created:
                    _get_or_create_user_row(db, user_id, language=language_hint)
    except SQLAlchemyError:
        logger.exception("Error checking new user notification for user_id=%s", user_id)
        return

    if created:
        _notify_subscription_event(
            f"👤 Новий користувач запустив бота\nuser_id: {user_id}\nмова: {_normalize_language(language_hint)}",
            key=f"new_user_{user_id}",
        )


def refresh_cached_user_statuses() -> None:
    try:
        from state import app_state
        user_ids = app_state.get_cached_user_status_ids()
    except Exception:
        logger.debug("Could not list cached user statuses", exc_info=True)
        return

    for user_id in user_ids:
        try:
            status = get_user_status(user_id)
            _cache_user_status(user_id, status)
        except Exception:
            logger.exception("Could not refresh cached user status for user_id=%s", user_id)


def list_users(limit: int = 100, plan_type: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit or 100), 500))
    plan = _normalize_plan(plan_type) if plan_type else None

    try:
        with get_db() as db:
            if db is None:
                with _fallback_lock:
                    return list(_fallback_user_profiles.values())[:limit]

            query = db.query(User).order_by(User.user_id.asc())
            if plan:
                query = query.filter(User.plan_type == plan)

            return [_user_to_status(row) for row in query.limit(limit).all()]
    except SQLAlchemyError:
        logger.exception("Error listing users")
        with _fallback_lock:
            users = list(_fallback_user_profiles.values())
            if plan:
                users = [item for item in users if item.get("plan_type") == plan]
            return users[:limit]


def add_to_watchlist(user_id: int, pair: str) -> bool:
    if not user_id or not pair:
        return False

    pair = pair.strip().upper()

    try:
        with session_scope() as db:
            if db is None:
                return False

            existing = (
                db.query(UserWatchlist)
                .filter(
                    UserWatchlist.user_id == int(user_id),
                    UserWatchlist.pair == pair,
                )
                .first()
            )

            if existing is None:
                db.add(UserWatchlist(user_id=int(user_id), pair=pair))

            _fallback_add_watchlist(user_id, pair)
            return True
    except OperationalError:
        logger.exception("OperationalError while adding to watchlist")
        return _fallback_add_watchlist(user_id, pair)
    except SQLAlchemyError:
        logger.exception("Error adding to watchlist")
        return False


def remove_from_watchlist(user_id: int, pair: str) -> bool:
    if not user_id or not pair:
        return False

    pair = pair.strip().upper()

    try:
        with session_scope() as db:
            if db is None:
                return False

            existing = (
                db.query(UserWatchlist)
                .filter(
                    UserWatchlist.user_id == int(user_id),
                    UserWatchlist.pair == pair,
                )
                .first()
            )

            if existing is not None:
                db.delete(existing)

            _fallback_remove_watchlist(user_id, pair)
            return True
    except OperationalError:
        logger.exception("OperationalError while removing from watchlist")
        return _fallback_remove_watchlist(user_id, pair)
    except SQLAlchemyError:
        logger.exception("Error removing from watchlist")
        return False


def toggle_watchlist(user_id: int, pair: str) -> bool:
    if not user_id or not pair:
        return False

    pair = pair.strip().upper()

    try:
        with session_scope() as db:
            if db is None:
                return False

            existing = (
                db.query(UserWatchlist)
                .filter(
                    UserWatchlist.user_id == int(user_id),
                    UserWatchlist.pair == pair,
                )
                .first()
            )

            fallback_has_pair = pair in _fallback_get_watchlist(user_id)

            if existing or fallback_has_pair:
                if existing:
                    db.delete(existing)
                _fallback_remove_watchlist(user_id, pair)
            else:
                db.add(UserWatchlist(user_id=int(user_id), pair=pair))
                _fallback_add_watchlist(user_id, pair)

            return True
    except OperationalError:
        logger.exception("OperationalError while toggling watchlist")
        return _fallback_toggle_watchlist(user_id, pair)
    except SQLAlchemyError:
        logger.exception("Error toggling watchlist")
        return False


# ----------------------------------------------------------------------
# Signal outcome tracking
# ----------------------------------------------------------------------


def create_signal_outcome(
    *,
    pair: str,
    timeframe: str,
    verdict: str,
    score: int | float | None,
    entry_price: float,
    horizon_seconds: int,
) -> int | None:
    try:
        with session_scope() as session:
            if session is None:
                logger.debug("Signal outcome tracking skipped: no database engine")
                return None

            row = SignalOutcome(
                pair=(pair or "").strip().upper(),
                timeframe=(timeframe or "").strip(),
                verdict=(verdict or "").strip().upper(),
                score=int(score) if isinstance(score, (int, float)) else None,
                entry_price=float(entry_price),
                horizon_seconds=int(horizon_seconds),
                outcome="pending",
            )
            session.add(row)
            session.flush()
            return row.id
    except SQLAlchemyError:
        logger.exception("Error creating signal outcome for pair=%s", pair)
        return None


def get_pending_signal_outcomes(limit: int = 500) -> list[dict]:
    """Only returns horizon-based (new-style) pending rows. Legacy TP/SL
    rows from the previous tracking generation (horizon_seconds IS NULL)
    are left untouched — nothing resolves them anymore, but they're
    harmless leftover history."""
    limit = max(1, min(int(limit or 500), 2000))

    try:
        with get_db() as session:
            if session is None:
                return []

            rows = (
                session.query(SignalOutcome)
                .filter(SignalOutcome.outcome == "pending")
                .filter(SignalOutcome.horizon_seconds.isnot(None))
                .order_by(SignalOutcome.entry_ts.asc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "pair": row.pair,
                    "timeframe": row.timeframe,
                    "verdict": row.verdict,
                    "entry_price": row.entry_price,
                    "horizon_seconds": row.horizon_seconds,
                    "entry_ts": row.entry_ts,
                }
                for row in rows
            ]
    except SQLAlchemyError:
        logger.exception("Error loading pending signal outcomes")
        return []


def resolve_signal_outcome(outcome_id: int, *, outcome: str, exit_price: float | None) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False

            row = session.query(SignalOutcome).filter(SignalOutcome.id == outcome_id).first()
            if row is None or row.outcome != "pending":
                return False

            row.outcome = outcome
            row.exit_price = exit_price
            row.resolved_at = _utcnow()
            return True
    except SQLAlchemyError:
        logger.exception("Error resolving signal outcome id=%s", outcome_id)
        return False


def _row_is_correct_direction(row) -> bool:
    return (row.verdict == "BUY" and row.outcome == "up") or (row.verdict == "SELL" and row.outcome == "down")


def _row_is_wrong_direction(row) -> bool:
    return (row.verdict == "BUY" and row.outcome == "down") or (row.verdict == "SELL" and row.outcome == "up")


def _aggregate_signal_outcomes(rows: list) -> dict:
    """Binary-option-style aggregation: a 'win' is price moving in the
    signal's predicted direction over its horizon, a 'loss' is the
    opposite, 'flat' means the move was inside the noise threshold
    (excluded from win_rate, like a push). Legacy tp/sl/timeout rows from
    the previous tracking generation are counted as resolved-but-excluded
    so they don't skew win_rate."""
    wins = sum(1 for r in rows if _row_is_correct_direction(r))
    losses = sum(1 for r in rows if _row_is_wrong_direction(r))
    flats = sum(1 for r in rows if r.outcome == "flat")
    legacy = sum(1 for r in rows if r.outcome in ("tp", "sl", "timeout"))
    resolved = wins + losses + flats + legacy
    decided = wins + losses
    return {
        "total": len(rows),
        "resolved": resolved,
        "pending": len(rows) - resolved,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round(100.0 * wins / decided, 1) if decided else None,
    }


def get_signal_outcome_stats(days: int = 7) -> dict:
    days = max(1, min(int(days or 7), 365))
    since = _utcnow() - timedelta(days=days)
    empty = {"ok": False, "days": days, "by_pair": [], "by_timeframe": [], **_aggregate_signal_outcomes([])}

    try:
        with get_db() as session:
            if session is None:
                return empty

            rows = session.query(SignalOutcome).filter(SignalOutcome.entry_ts >= since).all()
    except SQLAlchemyError:
        logger.exception("Error loading signal outcome stats")
        return empty

    by_pair_map: dict[str, list] = {}
    by_tf_map: dict[str, list] = {}
    for row in rows:
        by_pair_map.setdefault(row.pair, []).append(row)
        by_tf_map.setdefault(row.timeframe or "?", []).append(row)

    by_pair = [
        {"pair": pair, **_aggregate_signal_outcomes(items)}
        for pair, items in sorted(by_pair_map.items(), key=lambda kv: -len(kv[1]))
    ]
    by_timeframe = [
        {"timeframe": tf, **_aggregate_signal_outcomes(items)}
        for tf, items in sorted(by_tf_map.items())
    ]

    return {
        "ok": True,
        "days": days,
        **_aggregate_signal_outcomes(rows),
        "by_pair": by_pair,
        "by_timeframe": by_timeframe,
    }


def get_signal_outcome_score_breakdown(days: int = 30, bucket_size: int = 5) -> list[dict]:
    """Win-rate per score bucket (e.g. 75-80, 80-85, ...), used to evaluate
    whether the BUY/SELL threshold in config is well calibrated. BUY signals
    use score directly and SELL signals use (100 - score) so both directions
    land on the same "distance from 50 = confidence" scale."""
    days = max(1, min(int(days or 30), 365))
    bucket_size = max(1, min(int(bucket_size or 5), 25))
    since = _utcnow() - timedelta(days=days)

    try:
        with get_db() as session:
            if session is None:
                return []

            rows = (
                session.query(SignalOutcome)
                .filter(SignalOutcome.entry_ts >= since)
                .filter(SignalOutcome.outcome.in_(("up", "down")))
                .filter(SignalOutcome.score.isnot(None))
                .all()
            )
    except SQLAlchemyError:
        logger.exception("Error loading signal outcome score breakdown")
        return []

    buckets: dict[int, list] = {}
    for row in rows:
        # HOTFIX FOLLOW-UP (2026-08-10): analysis.py's BUY/SELL verdict was
        # swapped relative to score (BUY is now a LOW raw score, SELL a
        # HIGH one - see analysis.py's TEMPORARY HOTFIX comment). This
        # normalization used to assume the opposite (BUY=high, SELL=low)
        # to fold both directions onto one "higher = more confident" scale
        # for threshold_advisor.py. Flipped which branch inverts to match,
        # otherwise every bucket here would rank confidence backwards.
        normalized_score = (100 - row.score) if row.verdict == "BUY" else row.score
        bucket_start = (normalized_score // bucket_size) * bucket_size
        buckets.setdefault(bucket_start, []).append(row)

    result = []
    for bucket_start in sorted(buckets):
        items = buckets[bucket_start]
        agg = _aggregate_signal_outcomes(items)
        result.append(
            {
                "bucket_start": bucket_start,
                "score_range": f"{bucket_start}-{bucket_start + bucket_size}",
                **agg,
            }
        )

    return result


# ----------------------------------------------------------------------
# Autotrader (Part 3)
# ----------------------------------------------------------------------


def _auto_trade_to_dict(row: "AutoTrade") -> dict:
    return {
        "id": row.id,
        "pair": row.pair,
        "direction": row.direction,
        "volume": row.volume,
        "entry_price": row.entry_price,
        "sl_price": row.sl_price,
        "tp_price": row.tp_price,
        "ts": row.ts,
        "account_mode": row.account_mode,
        "broker_order_id": row.broker_order_id,
        "broker_position_id": row.broker_position_id,
        "status": row.status,
        "pnl_amount": row.pnl_amount,
        "closed_at": row.closed_at,
        "error_message": row.error_message,
    }


def create_auto_trade(
    *,
    pair: str,
    direction: str,
    volume: int,
    sl_price: float | None,
    tp_price: float | None,
    account_mode: str,
) -> int | None:
    try:
        with session_scope() as session:
            if session is None:
                logger.warning("Autotrade skipped: no database engine")
                return None

            row = AutoTrade(
                pair=(pair or "").strip().upper(),
                direction=(direction or "").strip().upper(),
                volume=int(volume),
                sl_price=float(sl_price) if sl_price is not None else None,
                tp_price=float(tp_price) if tp_price is not None else None,
                account_mode=(account_mode or "demo").strip().lower(),
                status="submitted",
            )
            session.add(row)
            session.flush()
            return row.id
    except SQLAlchemyError:
        logger.exception("Error creating auto trade for pair=%s", pair)
        return None


def get_auto_trade(trade_id: int) -> dict | None:
    try:
        with get_db() as session:
            if session is None:
                return None
            row = session.query(AutoTrade).filter(AutoTrade.id == trade_id).first()
            return _auto_trade_to_dict(row) if row else None
    except SQLAlchemyError:
        logger.exception("Error loading auto trade id=%s", trade_id)
        return None


def find_auto_trade_by_broker_order_id(broker_order_id: str) -> dict | None:
    try:
        with get_db() as session:
            if session is None:
                return None
            row = (
                session.query(AutoTrade)
                .filter(AutoTrade.broker_order_id == str(broker_order_id))
                .first()
            )
            return _auto_trade_to_dict(row) if row else None
    except SQLAlchemyError:
        logger.exception("Error looking up auto trade by broker_order_id=%s", broker_order_id)
        return None


def find_auto_trade_by_broker_position_id(broker_position_id: str) -> dict | None:
    try:
        with get_db() as session:
            if session is None:
                return None
            row = (
                session.query(AutoTrade)
                .filter(AutoTrade.broker_position_id == str(broker_position_id))
                .order_by(AutoTrade.ts.desc())
                .first()
            )
            return _auto_trade_to_dict(row) if row else None
    except SQLAlchemyError:
        logger.exception("Error looking up auto trade by broker_position_id=%s", broker_position_id)
        return None


def mark_auto_trade_open(
    trade_id: int,
    *,
    broker_order_id: str | None,
    broker_position_id: str | None,
    entry_price: float | None,
) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            row = session.query(AutoTrade).filter(AutoTrade.id == trade_id).first()
            if row is None:
                return False

            if broker_order_id:
                row.broker_order_id = str(broker_order_id)
            if broker_position_id:
                row.broker_position_id = str(broker_position_id)
            if entry_price is not None:
                row.entry_price = float(entry_price)
            row.status = "open"
            return True
    except SQLAlchemyError:
        logger.exception("Error marking auto trade open id=%s", trade_id)
        return False


def mark_auto_trade_closed(trade_id: int, *, status: str, pnl_amount: float | None) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            row = session.query(AutoTrade).filter(AutoTrade.id == trade_id).first()
            if row is None or row.status not in {"submitted", "open"}:
                return False

            row.status = status
            row.pnl_amount = pnl_amount
            row.closed_at = _utcnow()
            return True
    except SQLAlchemyError:
        logger.exception("Error marking auto trade closed id=%s", trade_id)
        return False


def mark_auto_trade_error(trade_id: int, error_message: str) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            row = session.query(AutoTrade).filter(AutoTrade.id == trade_id).first()
            if row is None:
                return False

            row.status = "error"
            row.error_message = (error_message or "")[:255]
            row.closed_at = _utcnow()
            return True
    except SQLAlchemyError:
        logger.exception("Error marking auto trade as error id=%s", trade_id)
        return False


def count_open_auto_trades(account_mode: str) -> int:
    try:
        with get_db() as session:
            if session is None:
                return 0
            return (
                session.query(AutoTrade)
                .filter(AutoTrade.account_mode == (account_mode or "demo").lower())
                .filter(AutoTrade.status.in_(("submitted", "open")))
                .count()
            )
    except SQLAlchemyError:
        logger.exception("Error counting open auto trades")
        return 0


def get_daily_auto_trade_pnl(account_mode: str) -> float:
    day_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        with get_db() as session:
            if session is None:
                return 0.0

            rows = (
                session.query(AutoTrade)
                .filter(AutoTrade.account_mode == (account_mode or "demo").lower())
                .filter(AutoTrade.closed_at.isnot(None))
                .filter(AutoTrade.closed_at >= day_start)
                .filter(AutoTrade.pnl_amount.isnot(None))
                .all()
            )
            return sum(row.pnl_amount for row in rows)
    except SQLAlchemyError:
        logger.exception("Error computing daily auto trade pnl")
        return 0.0


# ----------------------------------------------------------------------
# Binomo executor (Part 3)
# ----------------------------------------------------------------------


def _binomo_trade_to_dict(row: "BinomoTrade") -> dict:
    return {
        "id": row.id,
        "asset": row.asset,
        "pair": row.pair,
        "direction": row.direction,
        "amount": row.amount,
        "expiry_seconds": row.expiry_seconds,
        "entry_ts": row.entry_ts,
        "account_mode": row.account_mode,
        "result": row.result,
        "payout_amount": row.payout_amount,
        "resolved_at": row.resolved_at,
        "signal_outcome_id": row.signal_outcome_id,
        "error_message": row.error_message,
    }


def create_binomo_trade(
    *,
    asset: str,
    pair: str | None,
    direction: str,
    amount: float,
    expiry_seconds: int,
    account_mode: str,
    signal_outcome_id: int | None = None,
) -> int | None:
    try:
        with session_scope() as session:
            if session is None:
                logger.warning("Binomo trade skipped: no database engine")
                return None

            row = BinomoTrade(
                asset=(asset or "").strip(),
                pair=(pair or "").strip().upper() or None,
                direction=(direction or "").strip().lower(),
                amount=float(amount),
                expiry_seconds=int(expiry_seconds),
                account_mode=(account_mode or "demo").strip().lower(),
                result="pending",
                signal_outcome_id=signal_outcome_id,
            )
            session.add(row)
            session.flush()
            return row.id
    except SQLAlchemyError:
        logger.exception("Error creating binomo trade for asset=%s", asset)
        return None


def get_binomo_trade(trade_id: int) -> dict | None:
    try:
        with get_db() as session:
            if session is None:
                return None
            row = session.query(BinomoTrade).filter(BinomoTrade.id == trade_id).first()
            return _binomo_trade_to_dict(row) if row else None
    except SQLAlchemyError:
        logger.exception("Error loading binomo trade id=%s", trade_id)
        return None


def get_pending_binomo_trades(account_mode: str, limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit or 200), 1000))

    try:
        with get_db() as session:
            if session is None:
                return []

            rows = (
                session.query(BinomoTrade)
                .filter(BinomoTrade.account_mode == (account_mode or "demo").lower())
                .filter(BinomoTrade.result == "pending")
                .order_by(BinomoTrade.entry_ts.asc())
                .limit(limit)
                .all()
            )
            return [_binomo_trade_to_dict(row) for row in rows]
    except SQLAlchemyError:
        logger.exception("Error loading pending binomo trades")
        return []


def resolve_binomo_trade(trade_id: int, *, result: str, payout_amount: float | None) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False

            row = session.query(BinomoTrade).filter(BinomoTrade.id == trade_id).first()
            if row is None or row.result != "pending":
                return False

            row.result = result
            row.payout_amount = payout_amount
            row.resolved_at = _utcnow()
            return True
    except SQLAlchemyError:
        logger.exception("Error resolving binomo trade id=%s", trade_id)
        return False


def mark_binomo_trade_error(trade_id: int, error_message: str) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False

            row = session.query(BinomoTrade).filter(BinomoTrade.id == trade_id).first()
            if row is None:
                return False

            row.result = "error"
            row.error_message = (error_message or "")[:255]
            row.resolved_at = _utcnow()
            return True
    except SQLAlchemyError:
        logger.exception("Error marking binomo trade as error id=%s", trade_id)
        return False


def count_binomo_trades_today(account_mode: str) -> int:
    day_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        with get_db() as session:
            if session is None:
                return 0
            return (
                session.query(BinomoTrade)
                .filter(BinomoTrade.account_mode == (account_mode or "demo").lower())
                .filter(BinomoTrade.entry_ts >= day_start)
                .count()
            )
    except SQLAlchemyError:
        logger.exception("Error counting today's binomo trades")
        return 0


def get_consecutive_binomo_losses(account_mode: str, limit: int = 50) -> int:
    """Counts losses in the most recent resolved trades, stopping at the
    first non-loss (win) result. Used for the MAX_CONSECUTIVE_LOSSES kill
    switch - 'error' results don't count as losses or reset the streak,
    they're skipped (a broken selector isn't a trading loss)."""
    try:
        with get_db() as session:
            if session is None:
                return 0

            rows = (
                session.query(BinomoTrade)
                .filter(BinomoTrade.account_mode == (account_mode or "demo").lower())
                .filter(BinomoTrade.result.in_(("win", "loss")))
                .order_by(BinomoTrade.resolved_at.desc())
                .limit(max(1, min(int(limit or 50), 200)))
                .all()
            )
    except SQLAlchemyError:
        logger.exception("Error computing consecutive binomo losses")
        return 0

    streak = 0
    for row in rows:
        if row.result == "loss":
            streak += 1
        else:
            break
    return streak


def get_daily_binomo_pnl(account_mode: str) -> float:
    day_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        with get_db() as session:
            if session is None:
                return 0.0

            rows = (
                session.query(BinomoTrade)
                .filter(BinomoTrade.account_mode == (account_mode or "demo").lower())
                .filter(BinomoTrade.resolved_at.isnot(None))
                .filter(BinomoTrade.resolved_at >= day_start)
                .filter(BinomoTrade.payout_amount.isnot(None))
                .all()
            )
            return sum(row.payout_amount for row in rows)
    except SQLAlchemyError:
        logger.exception("Error computing daily binomo pnl")
        return 0.0


# ----------------------------------------------------------------------
# Binomo executor runtime state (shared DB flags — the executor runs as a
# separate LOCAL process, so /binomo_on /binomo_off /binomo_status in
# Telegram (cloud process) can't touch any in-memory flag directly; both
# sides read/write these AppRuntimeSetting rows instead, reusing the same
# key-value table already used to persist cTrader tokens.)
# ----------------------------------------------------------------------

_BINOMO_ENABLED_KEY = "binomo_runtime_enabled"
_BINOMO_KILL_SWITCH_KEY = "binomo_kill_switch_tripped"
_BINOMO_KILL_SWITCH_REASON_KEY = "binomo_kill_switch_reason"


def get_binomo_runtime_state() -> dict:
    try:
        with get_db() as session:
            if session is None:
                return {"runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None}

            enabled_raw = _get_runtime_setting(session, _BINOMO_ENABLED_KEY)
            tripped_raw = _get_runtime_setting(session, _BINOMO_KILL_SWITCH_KEY)
            reason = _get_runtime_setting(session, _BINOMO_KILL_SWITCH_REASON_KEY)

            return {
                "runtime_enabled": enabled_raw != "false",  # unset -> enabled by default
                "kill_switch_tripped": tripped_raw == "true",
                "kill_switch_reason": reason,
            }
    except SQLAlchemyError:
        logger.exception("Error loading binomo runtime state")
        return {"runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None}


def set_binomo_runtime_enabled(enabled: bool) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            _set_runtime_setting(session, _BINOMO_ENABLED_KEY, "true" if enabled else "false")
            return True
    except SQLAlchemyError:
        logger.exception("Error setting binomo runtime enabled=%s", enabled)
        return False


def trip_binomo_kill_switch(reason: str) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            _set_runtime_setting(session, _BINOMO_KILL_SWITCH_KEY, "true")
            _set_runtime_setting(session, _BINOMO_KILL_SWITCH_REASON_KEY, (reason or "")[:255])
            return True
    except SQLAlchemyError:
        logger.exception("Error tripping binomo kill switch")
        return False


def clear_binomo_kill_switch() -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            _set_runtime_setting(session, _BINOMO_KILL_SWITCH_KEY, "false")
            _set_runtime_setting(session, _BINOMO_KILL_SWITCH_REASON_KEY, None)
            return True
    except SQLAlchemyError:
        logger.exception("Error clearing binomo kill switch")
        return False


# ----------------------------------------------------------------------
# Scanner category toggles (forex/crypto/commodities/watchlist) — these
# used to live only in app_state.SCANNER_STATE (in-memory), which silently
# resets to all-off on every process restart/deploy, since nothing ever
# persisted the last-known state. That meant every deploy silently stopped
# all signal generation until someone noticed and manually re-toggled it in
# the Web App. Persisted here the same way as Binomo's runtime flags.
# ----------------------------------------------------------------------

_SCANNER_STATE_KEY_PREFIX = "scanner_state_"


def get_persisted_scanner_state() -> dict:
    try:
        with get_db() as session:
            if session is None:
                return {}
            state = {}
            for category in ("forex", "crypto", "commodities", "watchlist"):
                raw = _get_runtime_setting(session, _SCANNER_STATE_KEY_PREFIX + category)
                if raw is not None:
                    state[category] = raw == "true"
            return state
    except SQLAlchemyError:
        logger.exception("Error loading persisted scanner state")
        return {}


def set_persisted_scanner_state(category: str, enabled: bool) -> bool:
    try:
        with session_scope() as session:
            if session is None:
                return False
            _set_runtime_setting(session, _SCANNER_STATE_KEY_PREFIX + category, "true" if enabled else "false")
            return True
    except SQLAlchemyError:
        logger.exception("Error persisting scanner state %s=%s", category, enabled)
        return False


initialize_database()
