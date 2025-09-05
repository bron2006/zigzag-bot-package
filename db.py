# db.py
import sqlite3
import logging
from config import DB_NAME

logger = logging.getLogger(__name__)

def initialize_database():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
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

def get_watchlist(user_id: int) -> list:
    if not user_id:
        return []
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT subscribed_pairs FROM user_settings WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            if result and result[0]:
                return result[0].split(',')
            return []
    except Exception as e:
        logger.error(f"Помилка отримання списку обраного для user_id {user_id}: {e}")
        return []

# --- ПОЧАТОК ЗМІН: Функція тепер повертає True/False ---
def toggle_watchlist(user_id: int, pair: str) -> bool:
    """Додає або видаляє пару зі списку обраного. Повертає True при успіху, False при невдачі."""
    if not user_id or not pair:
        return False
    try:
        current_list = get_watchlist(user_id)
        
        if pair in current_list:
            current_list.remove(pair)
        else:
            current_list.append(pair)
        
        new_list_str = ",".join(sorted(list(set(current_list)))) # Сортуємо для порядку
        
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_settings (user_id, subscribed_pairs) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET subscribed_pairs = excluded.subscribed_pairs
            ''', (user_id, new_list_str))
            conn.commit()
            logger.info(f"Оновлено список обраного для user_id {user_id}: {new_list_str}")
        return True
    except Exception as e:
        logger.error(f"Помилка оновлення списку обраного для user_id {user_id}: {e}", exc_info=True)
        return False
# --- КІНЕЦЬ ЗМІН ---

initialize_database()