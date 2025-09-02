# db.py
import sqlite3
import logging
from config import DB_PATH

# --- ПОЧАТОК ЗМІН: Додано логер ---
logger = logging.getLogger(__name__)
# --- КІНЕЦЬ ЗМІН ---

def get_db_connection():
    """Створює НОВЕ з'єднання з БД з правильними параметрами."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Ініціалізує таблиці в базі даних, якщо вони не існують."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Історія сигналів (для майбутнього аналізу)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL,
                pair TEXT NOT NULL,
                price REAL NOT NULL,
                bull_percentage INTEGER NOT NULL
            )
        ''')
        # Список обраного для кожного користувача
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist (
                user_id INTEGER NOT NULL,
                pair TEXT NOT NULL,
                PRIMARY KEY (user_id, pair)
            )
        ''')
        conn.commit()
    # --- ПОЧАТОК ЗМІН: Покращено логування помилок ---
    except Exception:
        logger.exception("DB Error during init_db")
    # --- КІНЕЦЬ ЗМІН ---
    finally:
        if conn:
            conn.close()

def add_signal_to_history(data):
    """Додає запис про сигнал до історії."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO signal_history (user_id, pair, price, bull_percentage) VALUES (?, ?, ?, ?)",
            (data['user_id'], data['pair'], data['price'], data['bull_percentage'])
        )
        conn.commit()
    # --- ПОЧАТОК ЗМІН: Покращено логування помилок ---
    except Exception:
        logger.exception("DB Error: Failed to add signal to history")
    # --- КІНЕЦЬ ЗМІН ---
    finally:
        if conn:
            conn.close()

def get_watchlist(user_id: int) -> list:
    """Отримує список обраних пар для користувача."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pair FROM watchlist WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        return [row['pair'] for row in rows]
    # --- ПОЧАТОК ЗМІН: Покращено логування помилок ---
    except Exception:
        logger.exception("DB Error: Failed to get watchlist for user_id: %s", user_id)
        return []
    # --- КІНЕЦЬ ЗМІН ---
    finally:
        if conn:
            conn.close()

def toggle_watchlist(user_id: int, pair: str) -> bool:
    """Додає або видаляє пару зі списку обраного."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Перевіряємо, чи існує пара в списку
        cursor.execute("SELECT 1 FROM watchlist WHERE user_id = ? AND pair = ?", (user_id, pair))
        exists = cursor.fetchone()
        
        if exists:
            # Видаляємо
            cursor.execute("DELETE FROM watchlist WHERE user_id = ? AND pair = ?", (user_id, pair))
        else:
            # Додаємо
            cursor.execute("INSERT INTO watchlist (user_id, pair) VALUES (?, ?)", (user_id, pair))
        
        conn.commit()
        return True
    # --- ПОЧАТОК ЗМІН: Покращено логування помилок ---
    except Exception:
        logger.exception("DB Error: Failed to toggle watchlist for user_id: %s, pair: %s", user_id, pair)
        return False
    # --- КІНЕЦЬ ЗМІН ---
    finally:
        if conn:
            conn.close()