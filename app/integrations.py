import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Appointment, Doctor, Reservation, VoiceSession, VoiceToolCall, utcnow
from .schemas import (
    AppointmentCreate, AppointmentOut, AvailabilityResponse, DoctorOut, HoldCreate, HoldOut,
    VoiceSessionCreate, VoiceSessionEnd, VoiceSessionEvent,
)
from .services import DomainError, availability, confirm_appointment, create_hold

router = APIRouter(prefix="/api/v1/integrations/voice", tags=["voice-integration"])


def require_voice_service(x_service_key: str = Header(alias="X-Service-Key")) -> str:
    if not secrets.compare_digest(x_service_key, settings.voice_service_api_key):
        raise DomainError("SERVICE_AUTH_REQUIRED", "A valid voice service credential is required.", 401)
    return "voice-runtime"


@router.get("/doctors", response_model=list[DoctorOut])
def doctors(department: str | None = None, branch: str | None = None,
            _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.is_active.is_(True)).order_by(Doctor.name)).unique().all()
    if department:
        needle = department.casefold()
        items = [item for item in items if any(
            needle in value.name.casefold() or needle == value.slug.casefold() for value in item.departments
        )]
    if branch:
        needle = branch.casefold()
        items = [item for item in items if any(
            needle in value.name.casefold() or needle in value.area.casefold() or needle == value.slug.casefold()
            for value in item.branches
        )]
    return items


@router.get("/availability", response_model=AvailabilityResponse)
def get_availability(doctor_id: str, branch_id: str, start_date: date, end_date: date,
                     consultation_type: str = Query("in_person", pattern="^(in_person|virtual)$"),
                     _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    slots, timezone_name = availability(db, doctor_id, branch_id, start_date, end_date, consultation_type)
    return AvailabilityResponse(slots=slots, timezone=timezone_name)


@router.post("/slot-holds", response_model=HoldOut, status_code=201)
def hold_create(body: HoldCreate, _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    return create_hold(db, body)


@router.delete("/slot-holds/{hold_id}", status_code=204)
def hold_release(hold_id: str, owner_key: str, _: str = Depends(require_voice_service),
                 db: Session = Depends(get_db)):
    hold = db.get(Reservation, hold_id)
    if hold and hold.owner_key == owner_key and hold.status == "active":
        hold.status = "released"
        db.commit()
    return Response(status_code=204)


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def appointment_create(body: AppointmentCreate, _: str = Depends(require_voice_service),
                       db: Session = Depends(get_db)):
    if body.origin_channel != "voice":
        raise DomainError("INVALID_ORIGIN", "Voice service bookings must use the voice origin.", 422)
    return confirm_appointment(db, body)


@router.post("/sessions", status_code=201)
def session_start(body: VoiceSessionCreate, _: str = Depends(require_voice_service),
                  db: Session = Depends(get_db)):
    existing = db.scalar(select(VoiceSession).where(VoiceSession.runtime_session_id == body.runtime_session_id))
    if existing:
        return _session_row(existing)
    item = VoiceSession(runtime_session_id=body.runtime_session_id, channel=body.channel)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _session_row(item)


@router.post("/sessions/{runtime_session_id}/events", status_code=201)
def session_event(runtime_session_id: str, body: VoiceSessionEvent,
                  _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    item = db.scalar(select(VoiceSession).where(VoiceSession.runtime_session_id == runtime_session_id))
    if not item:
        raise DomainError("VOICE_SESSION_NOT_FOUND", "Voice session was not found.", 404)
    if body.kind == "turn":
        item.turn_count += 1
    else:
        item.tool_call_count += 1
    item.last_intent = body.intent or body.tool_name
    if body.appointment_id:
        if not db.get(Appointment, body.appointment_id):
            raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
        item.appointment_id = body.appointment_id
    if body.kind == "tool":
        db.add(VoiceToolCall(voice_session_id=item.id, tool_name=body.tool_name,
                             outcome=body.outcome, appointment_id=body.appointment_id))
    db.commit()
    return _session_row(item)


@router.patch("/sessions/{runtime_session_id}")
def session_end(runtime_session_id: str, body: VoiceSessionEnd,
                _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    item = db.scalar(select(VoiceSession).where(VoiceSession.runtime_session_id == runtime_session_id))
    if not item:
        raise DomainError("VOICE_SESSION_NOT_FOUND", "Voice session was not found.", 404)
    item.status = body.status
    item.ended_at = utcnow()
    db.commit()
    return _session_row(item)


def _session_row(item: VoiceSession) -> dict:
    return {
        "id": item.id, "runtime_session_id": item.runtime_session_id, "status": item.status,
        "channel": item.channel, "turn_count": item.turn_count, "tool_call_count": item.tool_call_count,
        "last_intent": item.last_intent, "appointment_id": item.appointment_id,
        "started_at": item.started_at, "ended_at": item.ended_at,
    }
