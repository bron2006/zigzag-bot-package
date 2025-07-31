# db.py
import sqlite3
import time
import secrets # Додано для генерації state
from config import DB_NAME

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        # Існуючі таблиці...
        conn.execute("""
        CREATE TABLE IF NOT EXISTS watch (
            user_id INTEGER,
            pair TEXT,
            PRIMARY KEY(user_id, pair)
        );""")

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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_history_user_pair ON signal_history (user_id, pair);")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS ctrader_tokens (
            telegram_user_id INTEGER PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );""")
        
        # --- ПОЧАТОК ЗМІН: Нова таблиця для OAuth state ---
        conn.execute("""
        CREATE TABLE IF NOT EXISTS oauth_state (
            state TEXT PRIMARY KEY,
            telegram_user_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );""")
        # Створюємо індекс для автоматичного очищення старих записів
        conn.execute("CREATE INDEX IF NOT EXISTS idx_oauth_state_created_at ON oauth_state (created_at);")
        # --- КІНЕЦЬ ЗМІН ---

# ... (існуючі функції get_watchlist, toggle_watch, і т.д. залишаються без змін) ...

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

def add_signal_to_history(signal_data):
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

def save_ctrader_token(user_id, access_token, refresh_token, expires_in):
    expires_at = int(time.time()) + expires_in
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO ctrader_tokens (telegram_user_id, access_token, refresh_token, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at
        """, (user_id, access_token, refresh_token, expires_at))

def get_ctrader_token(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ctrader_tokens WHERE telegram_user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
        
# --- ПОЧАТОК ЗМІН: Нові функції для роботи з OAuth state ---
def create_oauth_state(user_id):
    """Створює, зберігає та повертає унікальний state для сесії OAuth."""
    with sqlite3.connect(DB_NAME) as conn:
        # Видаляємо старі state-записи (старші за 10 хвилин)
        conn.execute("DELETE FROM oauth_state WHERE created_at < datetime('now', '-10 minutes')")
        
        state = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO oauth_state (state, telegram_user_id) VALUES (?, ?)", (state, user_id))
        return state

def get_user_id_by_state(state):
    """Знаходить user_id за state та видаляє state з бази, щоб уникнути повторного використання."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_user_id FROM oauth_state WHERE state = ?", (state,))
        result = cursor.fetchone()
        if result:
            conn.execute("DELETE FROM oauth_state WHERE state = ?", (state,))
            return result[0]
        return None
# --- КІНЕЦЬ ЗМІН ---