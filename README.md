# 📡 Vardraj — The Offline AI Gateway

> **Bridge the digital divide. Access Google Gemini AI using just an SMS — no smartphone or internet required on the user's end.**

[![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Android-green?logo=android)](https://termux.dev)
[![AI](https://img.shields.io/badge/AI-Google%20Gemini-orange?logo=google)](https://aistudio.google.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen)]()

---

## 🌍 The Problem This Solves

Over **2.6 billion people** worldwide still lack internet access. Most AI tools
today — ChatGPT, Gemini, Copilot — require a smartphone and a stable data
connection. This leaves behind rural communities, students in low-connectivity
areas, and anyone relying on a basic feature phone.

**Vardraj changes that.**

By running a lightweight Python gateway on a single Android device, Vardraj
turns any standard SMS into an AI query. The host device handles all internet
communication — the end user needs nothing more than a SIM card and the
ability to send a text message. No app to install. No data plan required.
No smartphone needed.

---

## 💡 How It Was Built

This project was built entirely in Python and runs inside **Termux** — a
Linux terminal emulator for Android. It uses **Google Gemini 1.5 Flash** as
the underlying AI model, accessed via REST API. All conversation memory is
stored locally in a **SQLite database**, making the system stateful and
persistent across restarts.

The architecture is deliberately simple so it can run 24/7 on an inexpensive
Android device — even an old phone that would otherwise sit unused.

Key engineering decisions:
- **SQLite over JSON** — thread-safe, supports concurrent reads/writes, and
  survives crashes without data loss
- **Sentence-boundary chunking** — SMS responses split at natural breakpoints
  so every message reads cleanly
- **Persistent message IDs** — prevents duplicate replies even if the script
  restarts mid-conversation
- **Worker thread queue** — two simultaneous incoming messages are both
  processed correctly, in order
- **Rotating log files** — production-style observability with colored console
  output and separate error logs

  
## 🌍 What Is This?

Vardraj is a Python-based **SMS-to-AI bridge** that runs on an Android phone via Termux.

A user sends a plain text message → the host device intercepts it → forwards it to Gemini AI → sends the response back via SMS.

This means anyone with a **basic feature phone** and a local SIM card can access AI — even with no data plan, no smartphone, and no internet.

```
User's Feature Phone
       │  SMS
       ▼
Host Android (Termux + Python)
       │  REST API (Wi-Fi / Mobile Data)
       ▼
  Google Gemini
       │  AI Response
       ▼
Host Android
       │  SMS
       ▼
User's Feature Phone
```

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 **Contextual Memory** | Remembers last 10 messages per user via SQLite |
| 🔐 **Trigger-Word Filter** | Only processes messages starting with `Vardraj` |
| ✂️ **Smart SMS Chunking** | Splits responses at sentence boundaries, not mid-word |
| 📊 **Observability** | Live STATS command, rotating logs, response time tracking |
| 🌐 **Multi-Language** | Users can set their preferred reply language via SMS |
| ♻️ **Session Pagination** | Long answers paginated with NEXT command |
| 🔄 **SMS Retry Logic** | Auto-retries failed sends up to 3 times |
| 💾 **Persistent State** | Processed message IDs survive restarts — no duplicate replies |

---

## 🗂️ Project Structure

```
vardraj/
│
├── main.py             # Core gateway loop, command dispatcher, all handlers
├── database.py         # SQLite layer — history, processed IDs, user prefs
├── observability.py    # Metrics tracking — query times, SMS rate, API errors
├── logger.py           # Rotating file + colored console logging
├── config.py           # All user settings in one place (start here)
│
├── logs/               # Auto-created on first run
│   ├── vardraj.log         # Full rotating log (5 MB × 3 backups)
│   └── vardraj_errors.log  # Errors only
├── vardraj.db          # Auto-created SQLite database
│
├── .env.example        # Template for environment variables
├── .gitignore          # Keeps secrets and generated files out of Git
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

---

## ⚡ Quick Start

### Prerequisites
- Android phone with [Termux](https://termux.dev) installed (install from F-Droid, not Play Store)
- [Termux:API](https://f-droid.org/packages/com.termux.api/) add-on installed

### Step 1 — Install dependencies in Termux

```bash
pkg update && pkg upgrade
pkg install python termux-api git
pip install requests
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/vardraj.git
cd vardraj
```

### Step 3 — Add your Gemini API key

Get a free key from [Google AI Studio](https://aistudio.google.com) (no credit card needed).

Open `config.py` and paste your key:

```python
API_KEY = "your_gemini_api_key_here"
```

Or set it as an environment variable (more secure):

```bash
export GEMINI_API_KEY="your_key_here"
```

### Step 4 — Grant SMS permissions

```bash
termux-setup-storage
```

Then go to **Android Settings → Apps → Termux:API → Permissions** and enable SMS.

### Step 5 — Run

```bash
python main.py
```

You should see:
```
✅  Vardraj started — trigger word: 'Vardraj'
📭  Skipped N old messages. Waiting for new commands…
```

---

## 📱 SMS Commands

Send these from any phone to the host device's number:

| Command | What It Does |
|---|---|
| `Vardraj <question>` | Ask the AI anything |
| `Vardraj NEXT` | Get the next chunk of a long reply |
| `Vardraj RESET` | Clear your conversation memory |
| `Vardraj HISTORY` | See your last 5 questions |
| `Vardraj LANG Hindi` | Set reply language (any language works) |
| `Vardraj STATS` | See system health: uptime, query count, SMS rate |
| `Vardraj HELP` | Show this command list |

---

## ⚙️ Configuration

All settings live in `config.py`. No need to touch any other file.

```python
TRIGGER_WORD           = "Vardraj"   # Change to any word you like
MAX_HISTORY            = 10          # Conversation turns remembered per user
MEMORY_EXPIRY_DAYS     = 7           # Auto-forget messages older than this
SMS_CHUNK_SIZE         = 150         # Characters per SMS chunk
SMS_RETRY_COUNT        = 3           # Retry attempts for failed sends
SESSION_EXPIRY_MINUTES = 10          # Unread NEXT chunks expire after this
POLL_INTERVAL          = 5           # Seconds between inbox checks
```

---

## 📊 Observability

Vardraj tracks everything automatically:

- **Response times** — how long each Gemini call takes (ms)
- **SMS delivery rate** — percentage of messages sent successfully
- **API error log** — timestamps and types of every Gemini failure
- **Unique users** — how many different numbers have used the system

View it live by texting `Vardraj STATS`, or inspect the log files directly:

```bash
tail -f logs/vardraj.log          # Live feed of all activity
tail -f logs/vardraj_errors.log   # Errors only
```

---

## 🔒 Security Notes

- **Never commit your API key.** Use `config.py` locally or an environment variable.
- The `TRIGGER_WORD` acts as a basic access filter — change it to something unique.
- `memory.json`, `vardraj.db`, and `logs/` are all in `.gitignore` and will never be pushed.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.8+ |
| Runtime | Termux (Android Linux environment) |
| AI Model | Google Gemini 1.5 Flash |
| Storage | SQLite (via Python `sqlite3`) |
| Transport | GSM/SMS via Termux:API |
| Networking | REST API (`requests` library) |
| Logging | Python `logging` with `RotatingFileHandler` |

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

## 👤 Author

**Your Name**
- GitHub: [Ujjwalsingh-afk](https://github.com/Ujjwalsingh-afk)
- LinkedIn: [Ujjwal singh]([https://linkedin.com/in/your-profile](https://www.linkedin.com/in/ujjwal-singh-01a013328?utm_source=share_via&utm_content=profile&utm_medium=member_android))

---

> *Built to make AI accessible to everyone — regardless of device, connectivity, or location.*
