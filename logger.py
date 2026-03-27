"""
logger.py — Structured, rotating logger for Vardraj.

Features:
  • Rotating file handler — max 5 MB per file, keeps 3 backups
  • Separate error-only log so crashes are easy to find
  • Colored console output for live Termux monitoring
  • get_logger(name) — call from any module, consistent format everywhere
"""

import logging
import logging.handlers
import os

# ── FILE PATHS ────────────────────────────────────────────────────
LOG_DIR       = "logs"
MAIN_LOG      = os.path.join(LOG_DIR, "vardraj.log")
ERROR_LOG     = os.path.join(LOG_DIR, "vardraj_errors.log")

MAX_BYTES     = 5 * 1024 * 1024   # 5 MB per file
BACKUP_COUNT  = 3                  # Keep last 3 rotated files


# ── ANSI COLORS (Termux terminal supports these) ──────────────────
class _ColorFormatter(logging.Formatter):
    """Applies color to log levels in console output only."""

    COLORS = {
        logging.DEBUG:    "\033[36m",    # Cyan
        logging.INFO:     "\033[32m",    # Green
        logging.WARNING:  "\033[33m",    # Yellow
        logging.ERROR:    "\033[31m",    # Red
        logging.CRITICAL: "\033[35m",    # Magenta
    }
    RESET = "\033[0m"
    FMT   = "%(asctime)s {color}[%(levelname)s]{reset} %(name)s — %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        formatter = logging.Formatter(
            self.FMT.format(color=color, reset=self.RESET),
            datefmt="%H:%M:%S",
        )
        return formatter.format(record)


# ── SETUP (called once at startup) ───────────────────────────────
_configured = False

def _setup():
    global _configured
    if _configured:
        return
    _configured = True

    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Rotating main log (all levels)
    main_handler = logging.handlers.RotatingFileHandler(
        MAIN_LOG, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    main_handler.setLevel(logging.DEBUG)
    main_handler.setFormatter(fmt)

    # 2. Error-only log (easy to grep for problems)
    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    # 3. Colored console for live Termux monitoring
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(_ColorFormatter())

    root.addHandler(main_handler)
    root.addHandler(error_handler)
    root.addHandler(console_handler)


# ── PUBLIC API ────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger. Call once at the top of each module:
        from logger import get_logger
        log = get_logger(__name__)
    """
    _setup()
    return logging.getLogger(name)
