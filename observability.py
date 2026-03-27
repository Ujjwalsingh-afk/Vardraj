"""
observability.py — Runtime metrics for Vardraj.

Tracks (all persisted to SQLite so data survives restarts):
  • Every query: sender, response time (ms), timestamp
  • Every SMS send: success or failure
  • Every API error: error type + timestamp

Exposes:
  • record_query(sender, elapsed_ms)
  • record_sms(success)
  • record_api_error(reason)
  • get_stats_report(uptime_seconds) → SMS-ready string
  • get_top_users(n)              → list of (sender, count)
"""

import time
import sqlite3
from datetime import datetime, timedelta
from logger import get_logger

log = get_logger(__name__)
DB_FILE = "vardraj.db"


# ── HELPERS ───────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ── TABLE INIT (called from database.initialize_db) ───────────────

def initialize_metrics_tables():
    """Create metrics tables if they don't exist."""
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS queries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sender      TEXT    NOT NULL,
            elapsed_ms  REAL    NOT NULL,
            timestamp   REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sms_events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            success   INTEGER NOT NULL,   -- 1 = sent, 0 = failed
            timestamp REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_errors (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            reason    TEXT NOT NULL,
            timestamp REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_queries_time   ON queries    (timestamp);
        CREATE INDEX IF NOT EXISTS idx_queries_sender ON queries    (sender);
        CREATE INDEX IF NOT EXISTS idx_sms_time       ON sms_events (timestamp);
        CREATE INDEX IF NOT EXISTS idx_api_err_time   ON api_errors (timestamp);
    """)
    conn.commit()
    conn.close()
    log.debug("Metrics tables ready.")


# ── RECORDING ────────────────────────────────────────────────────

def record_query(sender: str, elapsed_ms: float):
    """Call this after every successful AI response."""
    conn = _conn()
    conn.execute(
        "INSERT INTO queries (sender, elapsed_ms, timestamp) VALUES (?, ?, ?)",
        (sender, elapsed_ms, time.time())
    )
    conn.commit()
    conn.close()
    log.debug(f"Metric: query from {sender} in {elapsed_ms:.0f}ms")


def record_sms(success: bool):
    """Call this after every termux-sms-send attempt resolves."""
    conn = _conn()
    conn.execute(
        "INSERT INTO sms_events (success, timestamp) VALUES (?, ?)",
        (1 if success else 0, time.time())
    )
    conn.commit()
    conn.close()


def record_api_error(reason: str):
    """Call this whenever the Gemini API returns an error."""
    conn = _conn()
    conn.execute(
        "INSERT INTO api_errors (reason, timestamp) VALUES (?, ?)",
        (reason, time.time())
    )
    conn.commit()
    conn.close()
    log.warning(f"API error recorded: {reason}")


# ── STATS QUERIES ─────────────────────────────────────────────────

def _since(days: int) -> float:
    return time.time() - (days * 86400)


def get_stats_report(uptime_seconds: float) -> str:
    """
    Return a compact stats summary formatted for SMS delivery.
    Covers the last 7 days of activity.
    """
    conn   = _conn()
    cutoff = _since(7)

    # Query stats
    q = conn.execute(
        "SELECT COUNT(*) as total, AVG(elapsed_ms) as avg_ms, "
        "MIN(elapsed_ms) as min_ms, MAX(elapsed_ms) as max_ms "
        "FROM queries WHERE timestamp > ?",
        (cutoff,)
    ).fetchone()

    # Unique users in last 7 days
    users = conn.execute(
        "SELECT COUNT(DISTINCT sender) as n FROM queries WHERE timestamp > ?",
        (cutoff,)
    ).fetchone()

    # SMS delivery rate
    sms = conn.execute(
        "SELECT SUM(success) as sent, COUNT(*) as total "
        "FROM sms_events WHERE timestamp > ?",
        (cutoff,)
    ).fetchone()

    # API errors in last 7 days
    errs = conn.execute(
        "SELECT COUNT(*) as n FROM api_errors WHERE timestamp > ?",
        (cutoff,)
    ).fetchone()

    # Today's query count
    today_cutoff = _since(1)
    today = conn.execute(
        "SELECT COUNT(*) as n FROM queries WHERE timestamp > ?",
        (today_cutoff,)
    ).fetchone()

    conn.close()

    # Uptime formatting
    uptime_str = str(timedelta(seconds=int(uptime_seconds)))

    # SMS delivery rate
    sms_total = sms["total"] or 0
    sms_sent  = sms["sent"]  or 0
    sms_rate  = f"{(sms_sent / sms_total * 100):.0f}%" if sms_total > 0 else "N/A"

    avg_ms = q["avg_ms"]
    avg_str = f"{avg_ms:.0f}ms" if avg_ms else "N/A"

    lines = [
        "VARDRAJ STATS (7 days)",
        f"Uptime:     {uptime_str}",
        f"Queries:    {q['total'] or 0} total / {today['n']} today",
        f"Users:      {users['n']} unique",
        f"Avg speed:  {avg_str}",
        f"SMS rate:   {sms_rate} ({sms_sent}/{sms_total})",
        f"API errors: {errs['n']}",
    ]
    return "\n".join(lines)


def get_top_users(n: int = 5) -> list:
    """
    Return the top N users by query count (last 30 days).
    Each item: {"sender": str, "count": int, "avg_ms": float}
    Used internally for admin visibility — not exposed via SMS
    to protect user privacy.
    """
    conn   = _conn()
    cutoff = _since(30)
    rows   = conn.execute(
        """
        SELECT sender, COUNT(*) as count, AVG(elapsed_ms) as avg_ms
        FROM queries
        WHERE timestamp > ?
        GROUP BY sender
        ORDER BY count DESC
        LIMIT ?
        """,
        (cutoff, n)
    ).fetchall()
    conn.close()
    return [{"sender": r["sender"], "count": r["count"], "avg_ms": r["avg_ms"]} for r in rows]


def cleanup_old_metrics(days: int = 90):
    """Prune metrics older than `days` to keep the DB lean."""
    cutoff = _since(days)
    conn   = _conn()
    conn.execute("DELETE FROM queries    WHERE timestamp < ?", (cutoff,))
    conn.execute("DELETE FROM sms_events WHERE timestamp < ?", (cutoff,))
    conn.execute("DELETE FROM api_errors WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()
    log.info(f"Pruned metrics older than {days} days.")
