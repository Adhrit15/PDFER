"""Accounts, sessions and daily allowances."""
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, func, select, update

from . import config
from .db import AuthSession, Document, Message, SessionLocal, Usage, User, now

DESK_COOKIE = "pdfer_desk"        # anonymous desk, set on first visit
SESSION_COOKIE = "pdfer_session"  # signed-in account
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}")


# ---------- passwords and sessions ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _cookie(response: Response, name: str, value: str, days: int) -> None:
    response.set_cookie(name, value, max_age=days * 86400, httponly=True, samesite="lax",
                        secure=config.COOKIE_SECURE)


def start_session(s, response: Response, user: User) -> None:
    token = secrets.token_urlsafe(32)
    s.add(AuthSession(token_hash=_digest(token), user_id=user.id,
                      expires_at=now() + timedelta(days=config.SESSION_DAYS)))
    _cookie(response, SESSION_COOKIE, token, config.SESSION_DAYS)


def end_session(s, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        s.execute(delete(AuthSession).where(AuthSession.token_hash == _digest(token)))
    response.delete_cookie(SESSION_COOKIE)


# ---------- who is asking ----------

@dataclass
class Who:
    owner: str          # owns documents and messages: "u:<id>" or "g:<desk cookie>"
    usage_key: str      # daily counters: "u:<id>" or "ip:<address>"
    user: User | None
    limits: dict

    @property
    def guest(self) -> bool:
        return self.user is None


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:60]
    return request.client.host if request.client else "unknown"


def desk_cookie(request: Request) -> str | None:
    value = request.cookies.get(DESK_COOKIE, "")
    return value if re.fullmatch(r"[\w-]{20,64}", value) else None


def ensure_desk(request: Request, response: Response) -> str:
    value = desk_cookie(request)
    if not value:
        value = secrets.token_urlsafe(24)
        _cookie(response, DESK_COOKIE, value, 365)
    return value


def current_user(s, request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = s.get(AuthSession, _digest(token))
    if not row:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < now():
        s.delete(row)
        s.commit()
        return None
    return s.get(User, row.user_id)


def identify(request: Request, desk: str | None = None) -> Who:
    with SessionLocal() as s:
        user = current_user(s, request)
    if user:
        key = f"u:{user.id}"
        return Who(key, key, user, config.USER_LIMITS)
    desk = desk or desk_cookie(request)
    if not desk:
        raise HTTPException(401, "Reload the page to start a session.")
    return Who("g:" + desk, "ip:" + client_ip(request), None, config.GUEST_LIMITS)


def who(request: Request) -> Who:
    """FastAPI dependency."""
    return identify(request)


# ---------- daily allowances ----------

def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def usage_row(s, key: str) -> Usage:
    row = s.scalar(select(Usage).where(Usage.key == key, Usage.day == today()))
    if not row:
        row = Usage(key=key, day=today(), pdfs=0, pages=0, messages=0)
        s.add(row)
        s.flush()
    return row


def usage_json(s, w: Who) -> dict:
    row = s.scalar(select(Usage).where(Usage.key == w.usage_key, Usage.day == today()))
    return {k: {"used": getattr(row, k) if row else 0, "limit": w.limits[k]} for k in ("pdfs", "pages", "messages")}


WORDS = {"pdfs": "PDFs", "pages": "pages", "messages": "questions"}


def require(s, w: Who, what: str, amount: int = 1) -> None:
    """Raise 429 if spending `amount` of `what` would go over today's allowance."""
    used, limit = getattr(usage_row(s, w.usage_key), what), w.limits[what]
    if used + amount <= limit:
        return
    if what == "pages" and used < limit:
        msg = f"That PDF would take you over today's {limit}-page allowance ({limit - used} pages left)."
    else:
        msg = f"You've used today's {limit} {WORDS[what]}."
    if w.guest:
        u = config.USER_LIMITS
        msg += f" Create a free account for {u['pdfs']} PDFs and {u['messages']} questions a day."
    else:
        msg += " It resets at midnight UTC."
    raise HTTPException(429, msg)


def spend(s, w: Who, **amounts: int) -> None:
    s.execute(update(Usage).where(Usage.id == usage_row(s, w.usage_key).id)
              .values({k: getattr(Usage, k) + v for k, v in amounts.items()}))


def adopt_guest_desk(s, request: Request, user: User) -> None:
    """Move what a visitor did before signing in onto their account, if the account's desk is empty."""
    desk = desk_cookie(request)
    if not desk:
        return
    guest, owner = "g:" + desk, f"u:{user.id}"
    if s.scalar(select(func.count()).select_from(Document).where(Document.owner_id == owner)):
        return
    docs = s.scalars(select(Document).where(Document.owner_id == guest)).all()
    if docs:
        row = usage_row(s, owner)
        row.pdfs += len(docs)
        row.pages += sum(d.pages for d in docs)
    s.execute(update(Document).where(Document.owner_id == guest).values(owner_id=owner))
    if not s.scalar(select(func.count()).select_from(Message).where(Message.owner_id == owner)):
        s.execute(update(Message).where(Message.owner_id == guest).values(owner_id=owner))


# ---------- brute-force guard for sign-in / sign-up ----------

_attempts: dict[str, list[float]] = {}


def throttle(request: Request, limit: int = 10, window: int = 300) -> None:
    ip, t = client_ip(request), time.time()
    recent = [x for x in _attempts.get(ip, []) if t - x < window]
    if len(recent) >= limit:
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    recent.append(t)
    _attempts[ip] = recent
    if len(_attempts) > 5000:
        _attempts.clear()
