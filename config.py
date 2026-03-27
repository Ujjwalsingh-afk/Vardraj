import os

# ================================================================
#   VARDRAJ CONFIGURATION — Edit this file to set up your bot
# ================================================================

# ── REQUIRED ────────────────────────────────────────────────────
# Get your free key at: https://aistudio.google.com
# Option A: Paste it directly below (NOT recommended for sharing)
# Option B: Set env variable GEMINI_API_KEY (recommended)
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

# ── TRIGGER WORD ─────────────────────────────────────────────────
# Only SMS messages starting with this word are processed
TRIGGER_WORD = "Vardraj"

# ── MEMORY SETTINGS ──────────────────────────────────────────────
MAX_HISTORY          = 10   # Max message pairs stored per user
MEMORY_EXPIRY_DAYS   = 7    # Automatically forget messages older than this

# ── SMS SETTINGS ─────────────────────────────────────────────────
SMS_CHUNK_SIZE          = 150  # Max characters per SMS chunk
SMS_RETRY_COUNT         = 3    # Retry attempts for a failed SMS send
SESSION_EXPIRY_MINUTES  = 10   # Clear unread NEXT chunks after this long

# ── SYSTEM SETTINGS ──────────────────────────────────────────────
POLL_INTERVAL = 5   # Seconds between inbox checks

# ================================================================
