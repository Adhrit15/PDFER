"""Settings, all overridable from the environment / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
WEB_DIR = BASE_DIR / "web"

_db = os.getenv("DATABASE_URL", "").strip()
for _prefix in ("postgres://", "postgresql://"):
    if _db.startswith(_prefix):
        _db = "postgresql+psycopg://" + _db[len(_prefix):]
DATABASE_URL = _db or f"sqlite:///{(DATA_DIR / 'pdfer.db').as_posix()}"

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
# Tried in order; the next one is used when a model is rate-limited or unavailable.
MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3.5-flash-lite").split(",") if m.strip()]

MAX_DOCS = _int("MAX_DOCS", 5)                  # PDFs open on one desk at a time
MAX_FILE_MB = _int("MAX_FILE_MB", 25)
MAX_PAGES = _int("MAX_PAGES", 400)              # per PDF
OCR_MAX_PAGES = _int("OCR_MAX_PAGES", 40)       # scanned PDFs are transcribed by Gemini
CONTEXT_CHARS = _int("CONTEXT_CHARS", 400_000)  # ~100k tokens sent to the model per request
HISTORY_TURNS = _int("HISTORY_TURNS", 8)
AI_TIMEOUT = _int("AI_TIMEOUT", 180)                  # seconds, whole request
FIRST_TOKEN_TIMEOUT = _int("FIRST_TOKEN_TIMEOUT", 35)  # seconds before trying the next model
OCR_TIMEOUT = _int("OCR_TIMEOUT", 60)                  # seconds per model for scanned PDFs

# Daily allowances, reset at midnight UTC. Guests are visitors without an account (counted per IP).
USER_LIMITS = {"pdfs": _int("USER_PDFS_PER_DAY", 5), "pages": _int("USER_PAGES_PER_DAY", 500),
               "messages": _int("USER_MESSAGES_PER_DAY", 100)}
GUEST_LIMITS = {"pdfs": _int("GUEST_PDFS_PER_DAY", 2), "pages": _int("GUEST_PAGES_PER_DAY", 100),
                "messages": _int("GUEST_MESSAGES_PER_DAY", 15)}
SESSION_DAYS = _int("SESSION_DAYS", 30)
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"  # read the visitor IP from X-Forwarded-For

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"  # set to 1 when served over HTTPS
