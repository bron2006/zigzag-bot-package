# db.py
import logging
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from contextlib import contextmanager

from config import get_database_url

logger = logging.getLogger(__name__)

DATABASE_URL = get_database_url()
if not DATABASE_URL:
    logger.critical("DATABASE_URL is not set. Database functionality will be disabled.")
    engine = None
    SessionLocal = None
else:
    try:
        # Додаємо опції для кращого керування з'єднаннями
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"options": "-c timezone=utc"}
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception as e:
        logger.critical(f"Failed to create database engine: {e}")
        engine = None
        SessionLocal = None

Base = declarative_base()

# Модель для історії сигналів
class SignalHistory(Base):
    __tablename__ = "signal_history"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now())
    user_id = Column(Integer)
    pair = Column(String)
    price = Column(Float)
    bull_percentage = Column(Integer)

# Модель для налаштувань користувача (список обраного)
class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id = Column(Integer, primary_key=True, index=True)
    subscribed_pairs = Column(String, default="")

@contextmanager
def get_db():
    """Створює сесію бази даних і гарантує її закриття."""
    if not SessionLocal:
        yield None
        return
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

def initialize_database():
    """Створює таблиці в базі даних, якщо їх не існує."""
    if not engine:
        logger.warning("Database engine not initialized. Skipping table creation.")
        return
    try:
        logger.info("Initializing database and ensuring tables exist...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialization complete.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}", exc_info=True)

def add_signal_to_history(data):
    try:
        with get_db() as db:
            if not db: return
            new_signal = SignalHistory(
                user_id=data['user_id'],
                pair=data['pair'],
                price=data['price'],
                bull_percentage=data['bull_percentage']
            )
            db.add(new_signal)
            db.commit()
    except SQLAlchemyError as e:
        logger.error(f"Error adding signal to history: {e}", exc_info=True)

def get_watchlist(user_id: int) -> list:
    if not user_id: return []
    try:
        with get_db() as db:
            if not db: return []
            user_settings = db.get(UserSettings, user_id)
            if user_settings and user_settings.subscribed_pairs:
                return [item.strip() for item in user_settings.subscribed_pairs.split(',') if item.strip()]
            return []
    except SQLAlchemyError as e:
        logger.error(f"Error getting watchlist for user_id {user_id}: {e}", exc_info=True)
        return []

def toggle_watchlist(user_id: int, pair: str) -> bool:
    if not user_id or not pair: return False
    try:
        with get_db() as db:
            if not db: return False
            cleaned_pair = pair.strip()
            
            user_settings = db.get(UserSettings, user_id)
            if not user_settings:
                user_settings = UserSettings(user_id=user_id, subscribed_pairs="")
                db.add(user_settings)
            
            current_pairs_str = user_settings.subscribed_pairs or ""
            current_set = set([item.strip() for item in current_pairs_str.split(',') if item.strip()])

            if cleaned_pair in current_set:
                current_set.remove(cleaned_pair)
            else:
                current_set.add(cleaned_pair)
            
            user_settings.subscribed_pairs = ",".join(sorted(list(current_set)))
            
            db.commit()
            logger.info(f"Updated watchlist for user_id {user_id}: '{user_settings.subscribed_pairs}'")
            return True
    except SQLAlchemyError as e:
        logger.error(f"Error toggling watchlist for user_id {user_id}: {e}", exc_info=True)
        db.rollback() # Відкат змін у разі помилки
        return False

# Ініціалізуємо базу даних при старті додатку
initialize_database()