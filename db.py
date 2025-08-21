# db.py
import sqlite3
import logging
from config import DB_NAME # <-- Імпортуємо просту назву

logger = logging.getLogger(__name__)

def initialize_database():
    """Ініціалізує таблиці в базі даних, якщо вони ще не існують."""
    try:
        # --- ПОВЕРТАЄМОСЬ ДО ПРОСТОГО ПІДКЛЮЧЕННЯ ---
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            # Таблиця для історії сигналів
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signal_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER,
                    pair TEXT,
                    price REAL,
                    bull_percentage INTEGER
                )
            ''')
            # Таблиця для налаштувань користувача
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    subscribed_pairs TEXT
                )
            ''')
            conn.commit()
            logger.info("База даних успішно ініціалізована.")
    except Exception as e:
        logger.error(f"Помилка ініціалізації бази даних: {e}")

def add_signal_to_history(data):
    """Додає запис про сигнал до історії."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO signal_history (user_id, pair, price, bull_percentage)
                VALUES (?, ?, ?, ?)
            ''', (data['user_id'], data['pair'], data['price'], data['bull_percentage']))
            conn.commit()
    except Exception as e:
        logger.error(f"Помилка додавання сигналу в історію: {e}")

# Викликаємо ініціалілізацію при першому імпорті модуля
initialize_database()