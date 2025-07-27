# db.py
import sqlite3
from config import DB_NAME

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS watch (
            user_id INTEGER,
            pair TEXT,
            PRIMARY KEY(user_id, pair)
        );""")

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