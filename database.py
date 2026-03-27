"""
database.py — Persistent SQLite storage for Vardraj.

Replaces the old memory.json with three tables:
  • history       — per-user conversation turns with timestamps
  • processed_ids — survives restarts so no message is re-processed
  • user_prefs    — per-user settings like preferred language
"""

import sqlite3
import time
from datetime import datetime
from config import MAX_HISTORY, MEMORY_EXPIRY_DAYS
from logger import get_logger

log = get_logger(__name__)
DB_FILE = "vardraj.db"


# ── CONNECTION ────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # Safe for concurrent reads/writes
    return conn


# ── INITIALISATION ────────────────────────────────────────────────

def initialize_db():
    """Create all tables if they don't exist. Call once at startup."""
    conn = _get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT    NOT NULL,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            timestamp REAL    NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_ids (
            msg_id    TEXT PRIMARY KEY,
            timestamp REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id    TEXT PRIMARY KEY,
            language   TEXT NOT NULL DEFAULT 'English',
            updated_at REAL NOT NULL
        )
    """)

    # Index for fast per-user history lookups
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_user_time
        ON history (user_id, timestamp)
    """)

    conn.commit()
    conn.close()

    # Also initialise observability tables (import here to avoid circular imports)
    from observability import initialize_metrics_tables
    initialize_metrics_tables()

    log.info("Database initialised.")


# ── PROCESSED IDs (Reliability) ───────────────────────────────────

def is_processed(msg_id: str) -> bool:
    """Return True if this SMS ID has already been handled."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM processed_ids WHERE msg_id = ?", (str(msg_id),)
    ).fetchone()
    conn.close()
    return row is not None


def mark_processed(msg_id: str):
    """Persist that we've handled this SMS ID — survives restarts."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO processed_ids (msg_id, timestamp) VALUES (?, ?)",
        (str(msg_id), time.time())
    )
    conn.commit()
    conn.close()


def cleanup_old_processed_ids(days: int = 30):
    """Prune very old processed IDs so the table doesn't grow forever."""
    cutoff = time.time() - (days * 86400)
    conn = _get_conn()
    conn.execute("DELETE FROM processed_ids WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()


# ── CONVERSATION HISTORY ──────────────────────────────────────────

def get_user_history(user_id: str) -> list:
    """
    Return recent conversation turns in Gemini API format.
    Automatically excludes turns older than MEMORY_EXPIRY_DAYS.
    """
    cutoff = time.time() - (MEMORY_EXPIRY_DAYS * 86400)
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT role, content FROM history
        WHERE user_id = ? AND timestamp > ?
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (user_id, cutoff, MAX_HISTORY * 2)   # *2 because each turn = user + model
    ).fetchall()
    conn.close()

    return [
        {"role": r["role"], "parts": [{"text": r["content"]}]}
        for r in rows
    ]


def update_history(user_id: str, user_text: str, model_text: str):
    """
    Save a user/model turn pair, then prune to MAX_HISTORY pairs.
    """
    now = time.time()
    conn = _get_conn()

    conn.execute(
        "INSERT INTO history (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, "user", user_text, now)
    )
    conn.execute(
        "INSERT INTO history (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, "model", model_text, now + 0.001)
    )

    # Keep only the newest MAX_HISTORY * 2 rows for this user
    conn.execute(
        """
        DELETE FROM history
        WHERE user_id = ? AND id NOT IN (
            SELECT id FROM history
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        )
        """,
        (user_id, user_id, MAX_HISTORY * 2)
    )

    conn.commit()
    conn.close()


def clear_user_history(user_id: str):
    """Delete all conversation history for a user (RESET command)."""
    conn = _get_conn()
    conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    log.info(f"History cleared for {user_id}")


def get_history_summary(user_id: str) -> list:
    """
    Return the last 5 user questions with timestamps for the
    HISTORY command — returns list of dicts with keys:
    question, timestamp
    """
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT content, timestamp FROM history
        WHERE user_id = ? AND role = 'user'
        ORDER BY timestamp DESC
        LIMIT 5
        """,
        (user_id,)
    ).fetchall()
    conn.close()

    return [
        {
            "question": r["content"],
            "time": datetime.fromtimestamp(r["timestamp"]).strftime("%d/%m %H:%M")
        }
        for r in reversed(rows)   # Oldest first so reading order is natural
    ]


# ── USER PREFERENCES ──────────────────────────────────────────────

def get_user_language(user_id: str) -> str:
    """Return the user's preferred reply language (default: English)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT language FROM user_prefs WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["language"] if row else "English"


def set_user_language(user_id: str, language: str):
    """Upsert the user's preferred language."""
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO user_prefs (user_id, language, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET language = excluded.language,
                                           updated_at = excluded.updated_at
        """,
        (user_id, language, time.time())
    )
    conn.commit()
    conn.close()
    log.info(f"Language for {user_id} set to {language}")
