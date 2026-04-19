# db.py
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, event, func, inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from config import get_database_url
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


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id = Column(Integer, primary_key=True)
    language = Column(String(8), nullable=False, default="en")


def _normalize_language(lang: str | None) -> str:
    value = (lang or "").split(",", 1)[0].split("-")[0].split("_")[0].lower()
    return value if value in {"en", "uk", "es", "de", "ru"} else "en"


def _normalize_timezone(value: str | None) -> str:
    return normalize_timezone(value)


def _normalize_plan(plan_type: str | None) -> str:
    value = (plan_type or "free").strip().lower()
    return value if value in {"free", "pro"} else "free"


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


def _user_to_status(user: User | None, fallback_language: str | None = None) -> dict:
    lang = _normalize_language(getattr(user, "language", None) or fallback_language)
    tz = _normalize_timezone(getattr(user, "timezone", None))
    plan = _normalize_plan(getattr(user, "plan_type", None))
    ends_at = getattr(user, "subscription_ends_at", None)
    active = _subscription_active(plan, ends_at)

    return {
        "user_id": int(getattr(user, "user_id", 0) or 0),
        "language": lang,
        "timezone": tz,
        "plan_type": plan,
        "subscription_ends_at": _dt_to_iso(ends_at),
        "is_pro": active,
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

        if not statements:
            return

        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

        logger.info("Database users table migrated: %s", ", ".join(statements))
    except Exception:
        logger.exception("Could not ensure users table columns")


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
                "subscription_ends_at": None,
                "is_pro": False,
                "has_active_subscription": False,
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
                "subscription_ends_at": None,
                "is_pro": False,
                "has_active_subscription": False,
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
            "subscription_ends_at": None,
            "is_pro": False,
            "has_active_subscription": False,
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
    active = _subscription_active(plan, ends_at)
    profile = {
        "user_id": int(user_id),
        "language": lang,
        "timezone": tz,
        "plan_type": plan,
        "subscription_ends_at": _dt_to_iso(ends_at),
        "is_pro": active,
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
            _fallback_set_user_subscription(
                user_id,
                status["plan_type"],
                status["subscription_ends_at"],
                status["language"],
                log_warning=False,
            )
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
                return status

            user = _get_or_create_user_row(db, user_id, language=language)
            if language:
                user.language = _normalize_language(language)
            user.plan_type = plan
            user.subscription_ends_at = ends_at if plan == "pro" else None
            status = _user_to_status(user)
    except OperationalError:
        logger.exception("OperationalError while saving user subscription")
        status = _fallback_set_user_subscription(user_id, plan, ends_at, language)
    except SQLAlchemyError:
        logger.exception("Error saving user subscription")
        status = _fallback_set_user_subscription(user_id, plan, ends_at, language)

    _cache_user_status(user_id, status)
    return status


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


initialize_database()
