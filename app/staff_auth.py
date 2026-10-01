"""Named staff accounts. Opaque, revocable sessions; credentials never reach JS storage."""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import StaffLoginLimit, StaffSession, StaffUser, utcnow
from .services import DomainError

router = APIRouter(prefix="/api/v1/staff", tags=["staff-authentication"])
PASSWORDS = PasswordHasher()
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
COOKIE = "hms_staff_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", value):
        raise DomainError("INVALID_USERNAME", "Use 3–64 letters, numbers, dots, underscores or hyphens.", 422)
    return value


def password_hash(value):
    if not 12 <= len(value) <= 128:
        raise DomainError("INVALID_PASSWORD", "Use a password between 12 and 128 characters.", 422)
    return PASSWORDS.hash(value)


def user_row(user):
    return {"id": user.id, "username": user.username, "name": user.display_name, "role": user.role, "active": user.is_active}


def staff_label(user):
    # Preserve full username within existing 100-character audit columns.
    return f"{user.display_name[:96-len(user.username)]} (@{user.username})"


def check_origin(request):
    origin = request.headers.get("origin")
    expected = settings.staff_origin.rstrip("/") if settings.staff_origin else str(request.base_url).rstrip("/")
    if (origin and origin.rstrip("/") != expected) or request.headers.get("sec-fetch-site") == "cross-site":
        raise DomainError("STAFF_ORIGIN_REQUIRED", "Open the staff workspace on its configured address.", 403)


def current_staff(request: Request, db: Session, *, mutate=False):
    token = request.cookies.get(COOKIE)
    session = db.get(StaffSession, digest(token)) if token and len(token) < 256 else None
    now = utcnow()
    if not session or utc(session.expires_at) <= now or utc(session.last_seen_at) + timedelta(minutes=30) <= now:
        raise DomainError("STAFF_SIGN_IN_REQUIRED", "Your session has ended. Sign in again.", 401)
    user = db.get(StaffUser, session.user_id)
    if not user or not user.is_active:
        raise DomainError("STAFF_SIGN_IN_REQUIRED", "Sign in with an active staff account.", 401)
    if mutate:
        check_origin(request)
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not secrets.compare_digest(digest(csrf), session.csrf_hash):
            raise DomainError("STAFF_CSRF_REQUIRED", "Refresh the workspace before trying again.", 403)
    # Bounded write frequency; expired sessions never become live again.
    if utc(session.last_seen_at) + timedelta(minutes=1) < now:
        session.last_seen_at = now
        db.commit()
    request.state.staff_user = user
    return user, session


def require_staff(request: Request, db: Session = Depends(get_db)):
    user, _ = current_staff(request, db, mutate=request.method not in ("GET", "HEAD", "OPTIONS"))
    return user


def require_staff_owner(user: StaffUser = Depends(require_staff)):
    if user.role != "admin":
        raise DomainError("STAFF_ADMIN_REQUIRED", "Only a clinic administrator can manage staff accounts.", 403)
    return user


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CreateUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=12, max_length=128)
    role: str = "staff"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter a staff name with at least two characters.")
        return value


class ChangePassword(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


def login_limits(db, request, login_name):
    # Separate account and IP limits. Do not trust caller-supplied forwarding headers.
    address = request.client.host if request.client else "unknown"
    now = utcnow()
    for value, cap in (("account:" + login_name, 10), ("address:" + address, 30)):
        key = digest(value)
        item = db.scalar(select(StaffLoginLimit).where(StaffLoginLimit.key == key).with_for_update())
        if not item:
            try:
                with db.begin_nested():
                    db.add(StaffLoginLimit(key=key, attempts=0, window_started_at=now))
                    db.flush()
            except IntegrityError:
                pass
            item = db.scalar(select(StaffLoginLimit).where(StaffLoginLimit.key == key).with_for_update())
        if utc(item.window_started_at) + timedelta(minutes=15) <= now:
            item.attempts, item.window_started_at = 0, now
        if item.attempts >= cap:
            db.commit()
            raise DomainError("STAFF_LOGIN_LIMIT", "Too many sign-in attempts. Try again in 15 minutes.", 429)
        item.attempts += 1
    db.commit()


@router.post("/login")
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    name = body.username.strip().lower()
    login_limits(db, request, name)
    user = db.scalar(select(StaffUser).where(StaffUser.username == name))
    try:
        valid = PASSWORDS.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or not user or not user.is_active:
        raise DomainError("STAFF_LOGIN_FAILED", "The username or password is incorrect.", 401)
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(delete(StaffSession).where(StaffSession.token_hash == digest(old)))
    db.execute(delete(StaffSession).where(StaffSession.expires_at < utcnow()))
    if PASSWORDS.check_needs_rehash(user.password_hash):
        user.password_hash = PASSWORDS.hash(body.password)
    token = secrets.token_urlsafe(32)
    csrf = hmac.new(token.encode(), b"staff-csrf", hashlib.sha256).hexdigest()
    db.add(StaffSession(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf), expires_at=utcnow() + timedelta(hours=8)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=8 * 3600, httponly=True, secure=settings.app_env == "production", samesite="strict", path="/")
    return {"user": user_row(user), "csrf_token": csrf, "environment": settings.app_env}


@router.get("/session")
def session(request: Request, db: Session = Depends(get_db)):
    user, item = current_staff(request, db)
    # Stable per session across tabs; inaccessible without the HttpOnly auth cookie.
    csrf = hmac.new(request.cookies[COOKIE].encode(), b"staff-csrf", hashlib.sha256).hexdigest()
    return {"user": user_row(user), "csrf_token": csrf, "environment": settings.app_env}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, user=Depends(require_staff), db: Session = Depends(get_db)):
    db.execute(delete(StaffSession).where(StaffSession.token_hash == digest(request.cookies[COOKIE])))
    db.commit()
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=settings.app_env == "production", samesite="strict")


@router.get("/users")
def users(_=Depends(require_staff_owner), db: Session = Depends(get_db)):
    return [user_row(u) for u in db.scalars(select(StaffUser).order_by(StaffUser.display_name)).all()]


@router.post("/users", status_code=201)
def create_user(body: CreateUser, _=Depends(require_staff_owner), db: Session = Depends(get_db)):
    if body.role not in ("admin", "staff", "growth_manager"):
        raise DomainError("INVALID_ROLE", "Choose admin, staff or growth_manager.", 422)
    user = StaffUser(username=username(body.username), display_name=body.name.strip(), role=body.role, password_hash=password_hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError("USERNAME_TAKEN", "That username is already in use.", 409)
    return user_row(user)


@router.post("/password", status_code=204)
def change_password(body: ChangePassword, request: Request, response: Response, user=Depends(require_staff), db: Session = Depends(get_db)):
    try:
        PASSWORDS.verify(user.password_hash, body.current_password)
    except (VerificationError, InvalidHashError):
        raise DomainError("STAFF_LOGIN_FAILED", "The current password is incorrect.", 401)
    user.password_hash = password_hash(body.new_password)
    db.execute(delete(StaffSession).where(StaffSession.user_id == user.id))
    db.commit()
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=settings.app_env == "production", samesite="strict")
