"""Clinic-scoped call history and audited, administrator-only recording access."""

from datetime import timedelta
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..models import VoiceSession, VoiceRecordingAccess, StaffUser, utcnow
from ..services import DomainError
from ..staff_access import permission_required
from ..staff_auth import utc
from . import provider
from .admission import gate, reconcile

router = APIRouter(prefix="/api/v1/staff/voice", tags=["staff-voice"])
read = permission_required("voice.read", "voice")
recordings = permission_required("voice.recordings", "voice")


def recording_state(item):
    if not item.recording_consent_at:
        return "no_consent"
    if (
        item.recording_available_until
        and utc(item.recording_available_until) <= utcnow()
    ):
        return "expired"
    if (
        not item.interaction_id
        or not item.ended_at
        or not item.recording_available_until
    ):
        return "pending"
    if (
        not provider.configured()
        or not settings.sarvam_recording_url_field
        or not settings.voice_recording_hosts
    ):
        return "not_configured"
    # Eligibility does not assert that the provider has processed the recording.
    return "eligible"


@router.get("")
def history(
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(25, ge=1, le=100),
    user: StaffUser = Depends(read),
    db: Session = Depends(get_db),
):
    gate(db)
    reconcile(db)
    db.commit()
    rows = db.scalars(
        select(VoiceSession)
        .order_by(VoiceSession.started_at.desc(), VoiceSession.id)
        .offset(offset)
        .limit(limit)
    ).all()
    since = utcnow() - timedelta(days=30)
    recent = select(VoiceSession).where(VoiceSession.started_at >= since)
    counts = {
        status: count
        for status, count in db.execute(
            select(VoiceSession.status, func.count())
            .where(VoiceSession.started_at >= since)
            .group_by(VoiceSession.status)
        )
    }
    return {
        "calls": [
            {
                "id": r.id,
                "runtime_session_id": r.runtime_session_id,
                "status": r.status,
                "channel": r.channel,
                "agent_version": r.agent_version,
                "started_at": utc(r.started_at),
                "ended_at": utc(r.ended_at) if r.ended_at else None,
                "turn_count": r.turn_count,
                "tool_call_count": r.tool_call_count,
                "last_intent": r.last_intent,
                "appointment": (
                    {
                        "id": r.appointment.id,
                        "confirmation_code": r.appointment.confirmation_code,
                        "status": r.appointment.status,
                    }
                    if r.appointment
                    else None
                ),
                "recording_state": recording_state(r),
                "consented_at": (
                    utc(r.recording_consent_at) if r.recording_consent_at else None
                ),
                "recording_available_until": (
                    utc(r.recording_available_until)
                    if r.recording_available_until
                    else None
                ),
            }
            for r in rows
        ],
        "total": db.scalar(select(func.count()).select_from(VoiceSession)),
        "summary": {
            "calls": sum(counts.values()),
            "bookings": db.scalar(
                select(func.count()).select_from(
                    recent.where(VoiceSession.appointment_id.is_not(None)).subquery()
                )
            ),
            "errors": counts.get("error", 0),
            "period_days": 30,
        },
        "can_review_recordings": user.role == "admin",
        "configuration": {
            "calls_ready": provider.configured(),
            "recordings_ready": bool(
                provider.configured()
                and settings.sarvam_recording_url_field
                and settings.voice_recording_hosts
            ),
            "access_days": settings.voice_recording_access_days,
            "agent_version": settings.sarvam_app_version,
        },
    }


@router.post("/sessions/{session_id}/recording")
def recording(
    session_id: str,
    user: StaffUser = Depends(recordings),
    db: Session = Depends(get_db),
):
    item = db.get(VoiceSession, session_id)
    if not item:
        raise DomainError("VOICE_SESSION_NOT_FOUND", "Call was not found.", 404)
    audit = VoiceRecordingAccess(
        session_id=item.id, actor_id=user.id, outcome="requested"
    )
    db.add(audit)
    db.commit()
    try:
        state = recording_state(item)
        if state == "no_consent":
            raise DomainError(
                "VOICE_RECORDING_NO_CONSENT",
                "There is no recorded consent for this call.",
                403,
            )
        if state == "expired":
            raise DomainError(
                "VOICE_RECORDING_EXPIRED",
                "Recording access for this call has expired.",
                410,
            )
        if state == "pending":
            raise DomainError(
                "VOICE_RECORDING_PENDING",
                "The call has not finished or its provider reference is pending.",
                409,
            )
        if state == "not_configured":
            raise DomainError(
                "VOICE_RECORDING_NOT_CONFIGURED",
                "Recording playback needs provider configuration.",
                503,
            )
        audio, mime = provider.download_recording(
            provider.recording_url(item.interaction_id)
        )
        # Provider requests can be slow; recheck the access deadline before release.
        if utc(item.recording_available_until) <= utcnow():
            raise DomainError(
                "VOICE_RECORDING_EXPIRED",
                "Recording access for this call has expired.",
                410,
            )
    except DomainError as exc:
        audit.outcome = exc.code.removeprefix("VOICE_RECORDING_").lower()[:24]
        db.commit()
        raise
    audit.outcome = "delivered"
    db.commit()
    return Response(
        audio,
        media_type=mime,
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/recording-access")
def access_log(
    limit: int = Query(50, ge=1, le=200),
    _=Depends(recordings),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(VoiceRecordingAccess, StaffUser.display_name)
        .join(StaffUser, VoiceRecordingAccess.actor_id == StaffUser.id)
        .order_by(VoiceRecordingAccess.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "actor": name,
            "outcome": r.outcome,
            "created_at": utc(r.created_at),
        }
        for r, name in rows
    ]
