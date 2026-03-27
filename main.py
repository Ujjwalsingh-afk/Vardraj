"""
main.py — Vardraj: The Offline AI Gateway
==========================================
Improvements in this version:
  [1] Memory & Storage   — SQLite replaces JSON; timestamps; age-based expiry
  [2] Reliability        — persistent processed IDs; message queue; SMS retry
  [3] SMS Chunking       — sentence-boundary splits; chunk counter (1/N); session expiry
  [4] AI Quality         — HELP/HISTORY/LANG commands; proper system_instruction field
  [5] Observability      — rotating logs, colored console, per-query timing,
                           SMS delivery rate, API error tracking, STATS command
"""

import subprocess
import json
import time
import threading
import queue
import requests

from config import (
    API_KEY,
    TRIGGER_WORD,
    SMS_CHUNK_SIZE,
    POLL_INTERVAL,
    SMS_RETRY_COUNT,
    SESSION_EXPIRY_MINUTES,
)
from logger import get_logger
from database import (
    initialize_db,
    is_processed,
    mark_processed,
    cleanup_old_processed_ids,
    get_user_history,
    update_history,
    clear_user_history,
    get_history_summary,
    get_user_language,
    set_user_language,
)
from observability import (
    record_query,
    record_sms,
    record_api_error,
    get_stats_report,
    cleanup_old_metrics,
)

# ================================================================
#  LOGGING  —  structured, rotating, colored console
# ================================================================

log = get_logger(__name__)

# ================================================================
#  CONSTANTS
# ================================================================

API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/gemini-1.5-flash-latest:generateContent?key={API_KEY}"
)

HELP_TEXT = (
    f"VARDRAJ COMMANDS\n"
    f"{TRIGGER_WORD} <question>  Ask AI\n"
    f"{TRIGGER_WORD} NEXT        Next chunk\n"
    f"{TRIGGER_WORD} RESET       Clear memory\n"
    f"{TRIGGER_WORD} HISTORY     Recent questions\n"
    f"{TRIGGER_WORD} LANG <n>    Set reply language\n"
    f"{TRIGGER_WORD} STATS       System health report\n"
    f"{TRIGGER_WORD} HELP        This menu"
)

# Track process start time for uptime reporting
_START_TIME = time.time()

# ================================================================
#  [2] MESSAGE QUEUE  —  one worker thread processes SMS in order
# ================================================================

message_queue: queue.Queue = queue.Queue()

# ================================================================
#  [3] SESSION STORE  —  thread-safe, with expiry
# ================================================================

_sessions: dict = {}
_session_lock = threading.Lock()


def _session_get_chunks(sender: str) -> list:
    with _session_lock:
        s = _sessions.get(sender)
        if not s:
            return []
        if time.time() - s["last_active"] > SESSION_EXPIRY_MINUTES * 60:
            del _sessions[sender]
            log.info(f"Session expired for {sender}")
            return []
        return list(s["chunks"])


def _session_pop_chunk(sender: str):
    with _session_lock:
        s = _sessions.get(sender)
        if not s or not s["chunks"]:
            _sessions.pop(sender, None)
            return None
        chunk = s["chunks"].pop(0)
        s["last_active"] = time.time()
        if not s["chunks"]:
            del _sessions[sender]
        return chunk


def _session_set(sender: str, chunks: list):
    with _session_lock:
        _sessions[sender] = {"chunks": chunks, "last_active": time.time()}


# ================================================================
#  [2] SMS — with retry loop + [5] delivery tracking
# ================================================================

def send_sms(contact: str, message: str) -> bool:
    """Send an SMS via Termux, retrying up to SMS_RETRY_COUNT times.
    Records delivery success/failure to observability metrics."""
    clean = message.replace("*", "").replace("#", "")
    for attempt in range(1, SMS_RETRY_COUNT + 1):
        result = subprocess.run(
            ["termux-sms-send", "-n", contact, clean],
            capture_output=True,
        )
        if result.returncode == 0:
            log.info(f"SMS → {contact} (attempt {attempt}) OK")
            record_sms(success=True)     # [5] track delivery
            return True
        log.warning(f"SMS → {contact} attempt {attempt} failed")
        time.sleep(2)

    log.error(f"SMS → {contact} failed after {SMS_RETRY_COUNT} retries")
    record_sms(success=False)            # [5] track failure
    return False


def get_inbox() -> list:
    try:
        result = subprocess.run(
            ["termux-sms-list", "-l", "10", "-t", "inbox"],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(result.stdout)
    except Exception as e:
        log.error(f"Inbox fetch error: {e}")
        return []


# ================================================================
#  [3] SENTENCE-AWARE SMS CHUNKING
# ================================================================

def split_into_chunks(text: str, limit: int = SMS_CHUNK_SIZE) -> list:
    """
    Split text at sentence boundaries (. ! ?) so each SMS reads
    naturally rather than cutting mid-word or mid-idea.
    Falls back to hard-cut only when a single sentence exceeds limit.
    """
    sentences, current = [], ""
    for ch in text:
        current += ch
        if ch in ".!?" and len(current) >= 15:
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())

    chunks, chunk = [], ""
    for sentence in sentences:
        candidate = sentence if not chunk else chunk + " " + sentence

        if len(candidate) <= limit:
            chunk = candidate
        else:
            if chunk:
                chunks.append(chunk)
            if len(sentence) > limit:
                for i in range(0, len(sentence), limit):
                    chunks.append(sentence[i : i + limit])
                chunk = ""
            else:
                chunk = sentence

    if chunk:
        chunks.append(chunk)

    return chunks if chunks else [text]


# ================================================================
#  [4] GEMINI API — proper system_instruction + [5] timing & error tracking
# ================================================================

def ask_gemini(question: str, history: list, language: str = "English") -> tuple:
    """
    Call Gemini and return (answer_text, elapsed_ms).
    Errors are recorded to observability metrics automatically.
    """
    system_instruction = {
        "parts": [{
            "text": (
                "You are a helpful AI assistant delivered over SMS to users "
                "who may not have internet access. "
                "Rules: Keep responses under 300 words. "
                "Be concise and direct. "
                "Never use markdown formatting (no *, **, #, -, or bullet symbols). "
                f"Always reply in {language}."
            )
        }]
    }

    contents = history + [{"role": "user", "parts": [{"text": question}]}]
    payload  = {"system_instruction": system_instruction, "contents": contents}

    t0 = time.time()
    try:
        resp = requests.post(
            API_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        elapsed_ms = (time.time() - t0) * 1000

        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            log.info(f"Gemini responded in {elapsed_ms:.0f}ms")
            return text, elapsed_ms

        reason = f"HTTP {resp.status_code}"
        log.error(f"Gemini {reason}: {resp.text[:200]}")
        record_api_error(reason)                          # [5] track error
        return "AI is temporarily unavailable. Please try again.", elapsed_ms

    except requests.Timeout:
        elapsed_ms = (time.time() - t0) * 1000
        log.error("Gemini request timed out")
        record_api_error("timeout")                       # [5] track error
        return "Request timed out. Please try again.", elapsed_ms

    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        log.error(f"Gemini exception: {e}")
        record_api_error(str(type(e).__name__))           # [5] track error
        return "Connection error. Check the host device's internet.", elapsed_ms


# ================================================================
#  [4] + [5] COMMAND HANDLERS
# ================================================================

def handle_help(sender: str):
    send_sms(sender, HELP_TEXT)


def handle_reset(sender: str):
    clear_user_history(sender)
    send_sms(sender, "Memory cleared. Fresh start!")


def handle_next(sender: str):
    chunks = _session_get_chunks(sender)
    if not chunks:
        send_sms(sender, "No more messages in queue.")
        return
    chunk     = _session_pop_chunk(sender)
    remaining = len(_session_get_chunks(sender))
    suffix    = f" ({remaining} more — Reply '{TRIGGER_WORD} NEXT')" if remaining else ""
    send_sms(sender, chunk + suffix)


def handle_history(sender: str):
    rows = get_history_summary(sender)
    if not rows:
        send_sms(sender, "No history found.")
        return
    lines = [f"[{r['time']}] {r['question'][:55]}" for r in rows]
    send_sms(sender, "Recent questions:\n" + "\n".join(lines))


def handle_lang(sender: str, raw_args: str):
    lang = raw_args.strip().title()
    if not lang:
        send_sms(sender, f"Usage: {TRIGGER_WORD} LANG Hindi")
        return
    set_user_language(sender, lang)
    send_sms(sender, f"Language set to {lang}. Future replies will use it.")


def handle_stats(sender: str):
    """[5] SMS back a live system health report."""
    uptime = time.time() - _START_TIME
    report = get_stats_report(uptime)
    log.info(f"STATS requested by {sender}")
    send_sms(sender, report)


def handle_question(sender: str, question: str):
    language          = get_user_language(sender)
    history           = get_user_history(sender)
    answer, elapsed_ms = ask_gemini(question, history, language)

    update_history(sender, question, answer)
    record_query(sender, elapsed_ms)     # [5] persist timing metric

    chunks = split_into_chunks(answer)
    total  = len(chunks)

    if total > 1:
        _session_set(sender, chunks[1:])
        send_sms(sender, f"{chunks[0]} (1/{total} — Reply '{TRIGGER_WORD} NEXT')")
    else:
        send_sms(sender, chunks[0])

    log.info(
        f"Replied to {sender} | chunks={total} | "
        f"lang={language} | elapsed={elapsed_ms:.0f}ms"
    )


# ================================================================
#  COMMAND DISPATCHER
# ================================================================

def dispatch(sender: str, body: str):
    upper = body.upper().strip()

    if upper == "HELP":
        handle_help(sender)
    elif upper == "RESET":
        handle_reset(sender)
    elif upper == "NEXT":
        handle_next(sender)
    elif upper == "HISTORY":
        handle_history(sender)
    elif upper == "STATS":
        handle_stats(sender)                    # [5] new command
    elif upper.startswith("LANG"):
        handle_lang(sender, body[4:])
    elif body.strip():
        handle_question(sender, body.strip())
    else:
        send_sms(sender, f"No question given. Try: {TRIGGER_WORD} HELP")


# ================================================================
#  [2] WORKER THREAD
# ================================================================

def _worker():
    while True:
        try:
            sender, command = message_queue.get(timeout=1)
            log.info(f"[Worker] Processing from {sender}: {command[:60]}")
            dispatch(sender, command)
        except queue.Empty:
            continue
        except Exception as e:
            log.error(f"Worker unhandled error: {e}", exc_info=True)
        finally:
            try:
                message_queue.task_done()
            except Exception:
                pass


# ================================================================
#  MAIN
# ================================================================

def main():
    initialize_db()
    log.info("=" * 50)
    log.info("Vardraj started.")
    log.info(f"Trigger word: '{TRIGGER_WORD}' | Poll interval: {POLL_INTERVAL}s")
    log.info("=" * 50)

    # Skip pre-existing messages on restart
    old_messages = get_inbox()
    for msg in old_messages:
        if "_id" in msg:
            mark_processed(msg["_id"])
    log.info(f"Startup: marked {len(old_messages)} old messages as processed.")

    # Periodic housekeeping
    cleanup_old_processed_ids(days=30)
    cleanup_old_metrics(days=90)

    # Start background worker thread
    threading.Thread(target=_worker, daemon=True, name="sms-worker").start()
    log.info("Worker thread started.")

    # Poll loop
    while True:
        try:
            for msg in get_inbox():
                msg_id = msg.get("_id")
                sender = msg.get("number", "")
                body   = msg.get("body", "").strip()

                if is_processed(msg_id):
                    continue

                mark_processed(msg_id)

                if body.lower().startswith(TRIGGER_WORD.lower()):
                    command = body[len(TRIGGER_WORD):].strip()
                    log.info(f"Queued | sender={sender} | cmd={command[:60]}")
                    message_queue.put((sender, command))
                else:
                    log.debug(f"Ignored | sender={sender} | no trigger word")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Vardraj stopped by user (KeyboardInterrupt).")
            break
        except Exception as e:
            log.error(f"Poll loop error: {e}", exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
