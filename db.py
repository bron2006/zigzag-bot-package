# db.py
import sqlite3
import threading
from config import DB_PATH

# Створюємо локальний для потоку об'єкт для зберігання з'єднань
_local = threading.local()

def get_db_connection():
    """Створює або отримує існуюче з'єднання з БД для поточного потоку."""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        # --- ПОЧАТОК ЗМІН: Додано параметр check_same_thread=False ---
        # Це виправлення, рекомендоване аудитором для стабільності в багатопоточному середовищі
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        # --- КІНЕЦЬ ЗМІН ---
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn

def init_db():
    """Ініціалізує таблиці в базі даних, якщо вони не існують."""
    conn = get_db_connection()
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

def add_signal_to_history(data):
    """Додає запис про сигнал до історії."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO signal_history (user_id, pair, price, bull_percentage) VALUES (?, ?, ?, ?)",
            (data['user_id'], data['pair'], data['price'], data['bull_percentage'])
        )
        conn.commit()
    except Exception as e:
        print(f"DB Error: Failed to add signal to history. {e}")

def get_watchlist(user_id: int) -> list:
    """Отримує список обраних пар для користувача."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pair FROM watchlist WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        return [row['pair'] for row in rows]
    except Exception as e:
        print(f"DB Error: Failed to get watchlist. {e}")
        return []

def toggle_watchlist(user_id: int, pair: str) -> bool:
    """Додає або видаляє пару зі списку обраного."""
    try:
        conn = get_db_connection()
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
    except Exception as e:
        print(f"DB Error: Failed to toggle watchlist. {e}")
        return False