# db.py
import sqlite3
from config import DB_NAME

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        # Існуюча таблиця "watch"
        conn.execute("""
        CREATE TABLE IF NOT EXISTS watch (
            user_id INTEGER,
            pair TEXT,
            PRIMARY KEY(user_id, pair)
        );""")

        # --- НОВЕ: Таблиця для історії сигналів ---
        conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            price REAL,
            signal_type TEXT,
            bull_percentage INTEGER
        );""")
        # Створюємо індекс для швидкого пошуку
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_history_user_pair ON signal_history (user_id, pair);")

def get_watchlist(uid):
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute("SELECT pair FROM watch WHERE user_id=?", (uid,)).fetchall()
        return [r[0] for r in rows]

def toggle_watch(uid, pair):
    with sqlite3.connect(DB_NAME) as conn:
        exists = conn.execute("SELECT 1 FROM watch WHERE user_id=? AND pair=?", (uid, pair)).fetchone()
        if exists:
            conn.execute("DELETE FROM watch WHERE user_id=? AND pair=?", (uid, pair))
        else:
            conn.execute("INSERT INTO watch(user_id, pair) VALUES(?, ?)", (uid, pair))

# --- НОВЕ: Функції для роботи з історією сигналів ---

def add_signal_to_history(signal_data):
    """Додає запис про сигнал в історію та обрізає старі записи до 20."""
    with sqlite3.connect(DB_NAME) as conn:
        signal_type = "NEUTRAL"
        if signal_data['bull_percentage'] > 55: signal_type = "BUY"
        elif signal_data['bull_percentage'] < 45: signal_type = "SELL"

        conn.execute("""
            INSERT INTO signal_history (user_id, pair, price, signal_type, bull_percentage)
            VALUES (?, ?, ?, ?, ?)
        """, (
            signal_data['user_id'],
            signal_data['pair'],
            signal_data['price'],
            signal_type,
            signal_data['bull_percentage']
        ))

        conn.execute("""
            DELETE FROM signal_history
            WHERE id IN (
                SELECT id FROM signal_history
                WHERE user_id = ? AND pair = ?
                ORDER BY timestamp DESC
                LIMIT -1 OFFSET 20
            )
        """, (signal_data['user_id'], signal_data['pair']))

def get_signal_history(user_id, pair, limit=10):
    """Отримує останні N записів історії для конкретної пари."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, price, signal_type, bull_percentage
            FROM signal_history
            WHERE user_id = ? AND pair = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, pair, limit))
        
        return [dict(row) for row in cursor.fetchall()]