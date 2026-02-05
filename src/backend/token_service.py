import sqlite3
import os
import threading
from datetime import datetime
from config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "tokens.db")
_lock = threading.Lock()


def _get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL,
            timestamp   TEXT    NOT NULL,
            prompt      INTEGER NOT NULL DEFAULT 0,
            response    INTEGER NOT NULL DEFAULT 0,
            total       INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def record(session_id: str, prompt: int, response: int, total: int):
    with _lock:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO token_usage (session_id, timestamp, prompt, response, total) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, datetime.utcnow().isoformat(), prompt, response, total),
            )
            conn.commit()
        finally:
            conn.close()


def get_summary() -> dict:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(prompt),0), COALESCE(SUM(response),0), "
                "COALESCE(SUM(total),0), COUNT(*) FROM token_usage"
            ).fetchone()
            today = datetime.utcnow().strftime("%Y-%m-%d")
            today_row = conn.execute(
                "SELECT COALESCE(SUM(prompt),0), COALESCE(SUM(response),0), "
                "COALESCE(SUM(total),0), COUNT(*) FROM token_usage "
                "WHERE timestamp LIKE ?",
                (f"{today}%",),
            ).fetchone()
            return {
                "all_time": {
                    "prompt": row[0],
                    "response": row[1],
                    "total": row[2],
                    "count": row[3],
                },
                "today": {
                    "prompt": today_row[0],
                    "response": today_row[1],
                    "total": today_row[2],
                    "count": today_row[3],
                },
            }
        finally:
            conn.close()


def reset():
    with _lock:
        conn = _get_conn()
        try:
            conn.execute("DELETE FROM token_usage")
            conn.commit()
        finally:
            conn.close()
