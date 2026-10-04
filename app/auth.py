"""First-party HMS sessions and actor-aware authorization dependencies."""
import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import HospitalMembership, Patient, User, UserSession
from .services import DomainError


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_value, expected = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value + "=" * (-len(salt_value) % 4))
        actual = hash_password(password, salt=salt).split("$", 2)[2]
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Actor:
    user_id: str
    membership_id: str
    hospital_id: str
    role: str
    display_name: str
    patient_id: str | None = None
    session_id: str | None = None


def create_session(db: Session, user: User, membership: HospitalMembership) -> tuple[str, UserSession]:
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    item = UserSession(token_hash=token_hash(raw), user_id=user.id, membership_id=membership.id,
                       expires_at=now + timedelta(hours=settings.session_hours), last_seen_at=now)
    db.add(item)
    db.commit()
    db.refresh(item)
    return raw, item


def set_session_cookie(response: Response, raw: str) -> None:
    response.set_cookie(settings.session_cookie_name, raw, max_age=settings.session_hours * 3600,
                        httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def current_actor(session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
                  db: Session = Depends(get_db)) -> Actor:
    if not session_token:
        raise DomainError("AUTH_REQUIRED", "Please sign in to continue.", 401)
    now = datetime.now(timezone.utc)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(session_token)))
    if not session or session.revoked_at is not None:
        raise DomainError("SESSION_INVALID", "Your session is no longer valid.", 401)
    expires = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
    if expires <= now:
        raise DomainError("SESSION_EXPIRED", "Your session has expired.", 401)
    membership = db.get(HospitalMembership, session.membership_id)
    user = db.get(User, session.user_id)
    if not membership or membership.status != "active" or not user or not user.is_active:
        raise DomainError("ACCESS_REVOKED", "Your access is no longer active.", 403)
    patient_id = db.scalar(select(Patient.id).where(Patient.hospital_id == membership.hospital_id,
                                                     Patient.user_id == user.id))
    return Actor(user.id, membership.id, membership.hospital_id, membership.role, user.display_name,
                 patient_id, session.id)


def optional_actor(session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
                   db: Session = Depends(get_db)) -> Actor | None:
    if not session_token:
        return None
    try:
        return current_actor(session_token, db)
    except DomainError:
        return None


def require_roles(*roles: str):
    def dependency(actor: Actor = Depends(current_actor)) -> Actor:
        if actor.role not in roles:
            raise DomainError("FORBIDDEN", "You do not have permission to perform this action.", 403)
        return actor
    return dependency
