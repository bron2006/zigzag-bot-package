import logging
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from contextlib import contextmanager
from config import get_database_url

logger = logging.getLogger(__name__)

DATABASE_URL = get_database_url()
if not DATABASE_URL:
    logger.critical("DATABASE_URL is not set.")
    engine = None
    SessionLocal = None
else:
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception as e:
        logger.critical(f"Failed to create database engine: {e}")
        engine = None
        SessionLocal = None

Base = declarative_base()

class SignalHistory(Base):
    __tablename__ = "signal_history"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now())
    user_id = Column(Integer)
    pair = Column(String)
    price = Column(Float)
    bull_percentage = Column(Integer)

class UserWatchlist(Base):
    __tablename__ = "user_watchlist"
    user_id = Column(Integer, primary_key=True)
    pair = Column(String, primary_key=True)

@contextmanager
def get_db():
    if not SessionLocal:
        yield None
        return
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

def initialize_database():
    if not engine: return
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialization complete.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

def add_signal_to_history(data):
    try:
        with get_db() as db:
            if not db: return
            new_signal = SignalHistory(
                user_id=data['user_id'], pair=data['pair'],
                price=data['price'], bull_percentage=data['bull_percentage']
            )
            db.add(new_signal); db.commit()
    except SQLAlchemyError:
        logger.exception("Error adding signal")

def get_watchlist(user_id: int) -> list:
    if not user_id: return []
    try:
        with get_db() as db:
            if not db: return []
            res = db.query(UserWatchlist).filter(UserWatchlist.user_id == user_id).all()
            return [item.pair for item in res]
    except SQLAlchemyError:
        return []

def toggle_watchlist(user_id: int, pair: str) -> bool:
    if not user_id or not pair: return False
    try:
        with get_db() as db:
            if not db: return False
            pair = pair.strip()
            existing = db.query(UserWatchlist).filter(UserWatchlist.user_id == user_id, UserWatchlist.pair == pair).first()
            if existing:
                db.delete(existing)
            else:
                db.add(UserWatchlist(user_id=user_id, pair=pair))
            db.commit()
            return True
    except SQLAlchemyError:
        if db: db.rollback()
        return False

initialize_database()
