"""Trusted runtime correlation and repeat-safe operational events."""

import hashlib
import json
from datetime import timedelta
from sqlalchemy import select, func
from ..config import settings
from ..models import VoiceEventReceipt, VoiceSession, utcnow
from ..services import DomainError
from ..staff_auth import utc
from .admission import gate, reconcile


def session_for_owner(db, owner_key, *, allow_finished=False):
    if not owner_key.startswith("voice:"):
        raise DomainError(
            "VOICE_SESSION_REQUIRED",
            "Use the tracked call session to reserve this slot.",
            403,
        )
    session = db.scalar(
        select(VoiceSession)
        .where(VoiceSession.runtime_session_id == owner_key[6:])
        .with_for_update()
    )
    if not session or (
        not allow_finished
        and (
            session.status != "active"
            or session.expires_at
            and utc(session.expires_at) <= utcnow()
        )
    ):
        raise DomainError(
            "VOICE_SESSION_REQUIRED", "The call session is not active.", 403
        )
    return session


def bind_start(db, body):
    gate(db)
    item = db.scalar(
        select(VoiceSession)
        .where(VoiceSession.runtime_session_id == body.runtime_session_id)
        .with_for_update()
    )
    if not item:
        if body.channel != "phone":
            raise DomainError(
                "VOICE_ADMISSION_REQUIRED",
                "Web calls must be admitted from the public call screen.",
                403,
            )
        reconcile(db)
        count = db.scalar(
            select(func.count())
            .select_from(VoiceSession)
            .where(VoiceSession.status.in_(["issued", "active"]))
        )
        if count >= settings.voice_max_concurrent:
            raise DomainError("VOICE_BUSY", "All voice assistants are busy.", 429)
        item = VoiceSession(
            runtime_session_id=body.runtime_session_id,
            channel="phone",
            status="active",
            agent_version=settings.sarvam_app_version,
            expires_at=utcnow() + timedelta(minutes=settings.voice_session_minutes),
        )
        if body.recording_consent is True:
            item.recording_consent_at = utcnow()
            item.recording_notice_version = "recording-v1"
        db.add(item)
    if body.channel != item.channel:
        raise DomainError(
            "VOICE_SESSION_CONFLICT", "The call channel does not match.", 409
        )
    if item.channel == "web_voice" and not item.provider_reference:
        raise DomainError(
            "VOICE_SESSION_NOT_ISSUED", "The call connection has not been issued.", 409
        )
    if item.channel == "web_voice" and not body.provider_reference:
        raise DomainError(
            "VOICE_REFERENCE_REQUIRED",
            "The trusted provider reference is required to bind this web call.",
            403,
        )
    collision = db.scalar(
        select(VoiceSession).where(VoiceSession.interaction_id == body.interaction_id)
    )
    if collision and collision.id != item.id:
        raise DomainError(
            "VOICE_SESSION_CONFLICT",
            "The interaction already belongs to another call.",
            409,
        )
    if (
        body.provider_reference
        and item.provider_reference
        and body.provider_reference != item.provider_reference
    ):
        raise DomainError(
            "VOICE_SESSION_CONFLICT", "The provider reference does not match.", 409
        )
    if body.agent_version != item.agent_version:
        raise DomainError(
            "VOICE_VERSION_FORBIDDEN",
            "The call did not use the approved agent version.",
            403,
        )
    if item.interaction_id and item.interaction_id != body.interaction_id:
        raise DomainError(
            "VOICE_SESSION_CONFLICT", "The interaction does not match.", 409
        )
    item.interaction_id = body.interaction_id
    if body.provider_reference:
        item.provider_reference = body.provider_reference
    # A late start retry may bind a reference, but cannot reopen a completed call.
    if item.status == "issued":
        item.status = "active"
    if item.recording_consent_at and not item.recording_available_until:
        item.recording_available_until = utcnow() + timedelta(
            days=settings.voice_recording_access_days
        )
    db.commit()
    db.refresh(item)
    return item


def receipt(db, session, event_id, payload):
    gate(db)
    key = hashlib.sha256((session.id + ":" + event_id).encode()).hexdigest()
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    existing = db.get(VoiceEventReceipt, key)
    if existing:
        if existing.fingerprint != fingerprint:
            raise DomainError(
                "VOICE_EVENT_CONFLICT",
                "The event ID was already used for another event.",
                409,
            )
        return False
    db.add(VoiceEventReceipt(key=key, session_id=session.id, fingerprint=fingerprint))
    return True
