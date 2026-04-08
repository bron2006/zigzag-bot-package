# db.py

import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, event, func
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from config import get_database_url

logger = logging.getLogger(__name__)

DATABASE_URL = get_database_url()

Base = declarative_base()

engine = None
SessionLocal = None


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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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
        logger.info("Database initialization complete.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}", exc_info=True)


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
            return [row.pair for row in rows]
    except SQLAlchemyError:
        logger.exception("Error loading watchlist")
        return []


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

            return True
    except OperationalError:
        logger.exception("OperationalError while adding to watchlist")
        return False
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

            return True
    except OperationalError:
        logger.exception("OperationalError while removing from watchlist")
        return False
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

            if existing:
                db.delete(existing)
            else:
                db.add(UserWatchlist(user_id=int(user_id), pair=pair))

            return True
    except OperationalError:
        logger.exception("OperationalError while toggling watchlist")
        return False
    except SQLAlchemyError:
        logger.exception("Error toggling watchlist")
        return False


initialize_database()
