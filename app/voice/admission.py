"""Database-backed admission budgets shared across API workers."""

import hashlib
import hmac
import secrets
from datetime import timedelta
from sqlalchemy import func, select, update, delete
from sqlalchemy.exc import IntegrityError
from ..client_modules import ensure_module
from ..config import settings
from ..models import VoiceAdmissionGate, VoiceRateLimit, VoiceSession, utcnow
from ..services import DomainError
from ..staff_auth import utc
from .provider import configured

COOKIE = "hms_voice_guest"
NOTICE_VERSION = "recording-v1"
NOTICE = "This call is recorded by our voice provider so the clinic administrator can review it. Recording access in this clinic workspace lasts up to {days} days. Use website booking or contact reception if you do not want a recorded call."


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def origin_check(request):
    expected = str(request.base_url).rstrip("/")
    allowed = {
        expected,
        *settings.origins,
        *settings.booking_allowed_origins.split(","),
    }
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and origin.rstrip("/") not in allowed
    ):
        raise DomainError(
            "VOICE_ORIGIN_REQUIRED", "Start the call from the clinic website.", 403
        )
    if (
        settings.app_env == "production"
        and not origin
        and not (
            request.method == "GET"
            and request.headers.get("sec-fetch-site") == "same-origin"
        )
    ):
        raise DomainError(
            "VOICE_ORIGIN_REQUIRED", "Start the call from the clinic website.", 403
        )


def gate(db):
    if not db.get(VoiceAdmissionGate, "clinic"):
        try:
            db.add(VoiceAdmissionGate(key="clinic"))
            db.commit()
        except IntegrityError:
            db.rollback()
    # This update serializes both PostgreSQL workers and SQLite writers.
    db.execute(
        update(VoiceAdmissionGate)
        .where(VoiceAdmissionGate.key == "clinic")
        .values(touched_at=utcnow())
    )


def reconcile(db):
    now = utcnow()
    db.execute(
        update(VoiceSession)
        .where(
            VoiceSession.status.in_(["issued", "active"]),
            (
                (VoiceSession.expires_at <= now)
                | (
                    VoiceSession.expires_at.is_(None)
                    & (
                        VoiceSession.started_at
                        <= now - timedelta(minutes=settings.voice_session_minutes)
                    )
                )
            ),
        )
        .values(status="abandoned", ended_at=now)
        .execution_options(synchronize_session=False)
    )
    db.expire_all()


def admit(db, request):
    gate(db)
    ensure_module(db, "voice")
    if not configured():
        raise DomainError(
            "VOICE_NOT_CONFIGURED",
            "Voice calling needs an approved agent version and server credentials.",
            503,
        )
    reconcile(db)
    now = utcnow()
    previous_token = request.cookies.get(COOKIE, "")
    if 20 <= len(previous_token) <= 128:
        previous = db.scalar(
            select(VoiceSession).where(
                VoiceSession.admission_hash == digest(previous_token)
            )
        )
        if previous and previous.status in ("issued", "active"):
            raise DomainError(
                "VOICE_CALL_ALREADY_ACTIVE",
                "End your current call before starting another.",
                409,
            )
    current = db.scalar(
        select(func.count())
        .select_from(VoiceSession)
        .where(VoiceSession.status.in_(["issued", "active"]))
    )
    if current >= settings.voice_max_concurrent:
        raise DomainError(
            "VOICE_BUSY",
            "All voice assistants are busy. Try again shortly or contact reception.",
            429,
        )
    # No trust in caller-supplied X-Forwarded-For; proxy must supply trusted scope.
    ip = request.client.host if request.client else "unknown"
    key = (
        "ip:"
        + hmac.new(
            settings.voice_service_api_key.encode(), ip.encode(), hashlib.sha256
        ).hexdigest()
    )
    for bucket_key, window, limit in [
        (
            key,
            now.replace(minute=0, second=0, microsecond=0),
            settings.voice_calls_per_ip_hour,
        ),
        (
            "clinic:day",
            now.replace(hour=0, minute=0, second=0, microsecond=0),
            settings.voice_calls_per_day,
        ),
    ]:
        row = db.get(VoiceRateLimit, bucket_key)
        if not row:
            row = VoiceRateLimit(key=bucket_key, window_start=window, count=0)
            db.add(row)
        if utc(row.window_start) != window:
            row.window_start = window
            row.count = 0
        if row.count >= limit:
            raise DomainError(
                "VOICE_CALL_LIMIT",
                "The call limit has been reached. Try later or contact reception.",
                429,
            )
        row.count += 1
    db.execute(
        delete(VoiceRateLimit)
        .where(VoiceRateLimit.window_start < now - timedelta(days=2))
        .execution_options(synchronize_session=False)
    )
    token = secrets.token_urlsafe(32)
    session = VoiceSession(
        runtime_session_id="web-" + secrets.token_hex(16),
        status="issued",
        channel="web_voice",
        agent_version=settings.sarvam_app_version,
        admission_hash=digest(token),
        expires_at=now + timedelta(minutes=settings.voice_session_minutes),
        recording_consent_at=now,
        recording_notice_version=NOTICE_VERSION,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, token


def guest(db, request):
    token = request.cookies.get(COOKIE, "")
    session = (
        db.scalar(
            select(VoiceSession).where(VoiceSession.admission_hash == digest(token))
        )
        if 20 <= len(token) <= 128
        else None
    )
    if not session or not session.expires_at or utc(session.expires_at) <= utcnow():
        raise DomainError(
            "VOICE_ADMISSION_REQUIRED",
            "Start a new call from the clinic call screen.",
            403,
        )
    return session
