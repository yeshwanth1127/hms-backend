import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Appointment, Branch, Doctor, Reservation, ScheduleRule, VoiceSession, VoiceToolCall, utcnow
from .schemas import (
    AppointmentCreate, AppointmentOut, AvailabilityResponse, BranchOut, DoctorOut, HoldCreate, HoldOut,
    VoiceAppointmentsResponse, VoiceBranchesResponse, VoiceDoctorOut, VoiceDoctorsResponse,
    VoiceSessionCreate, VoiceSessionEnd, VoiceSessionEvent,
)
from .services import DomainError, availability, confirm_appointment, create_hold

router = APIRouter(prefix="/api/v1/integrations/voice", tags=["voice-integration"])


def require_voice_service(x_service_key: str = Header(alias="X-Service-Key")) -> str:
    if not secrets.compare_digest(x_service_key, settings.voice_service_api_key):
        raise DomainError("SERVICE_AUTH_REQUIRED", "A valid voice service credential is required.", 401)
    return "voice-runtime"


# Colloquial / symptom phrases callers use on the voice line → department slugs.
_DEPARTMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "cardiology": (
        "heart", "dil", "cardiac", "cardio", "chest pain", "bp", "blood pressure",
        "hypertension", "heart doctor", "dil ke doctor", "dil ka doctor",
    ),
    "dermatology": ("skin", "rash", "acne", "derma"),
    "orthopedics": (
        "bone", "joint", "ortho", "fracture", "knee", "back pain", "backache",
        "back ache", "spine", "slip disc", "slipped disc", "peeth", "kamar",
    ),
    "neurology": ("neuro", "migraine", "headache", "seizure", "brain"),
    "pediatrics": ("child", "kids", "paediatric", "pediatric", "baby"),
    "ent": ("ear", "nose", "throat", "sinus"),
    "dental": ("tooth", "teeth", "dentist", "gum"),
    "general-medicine": ("general", "fever", "cold", "flu", "physician", "gp"),
    "metabolic": ("diabetes", "thyroid", "sugar", "endocrine"),
}


def _department_match(needle: str, name: str, slug: str) -> bool:
    needle = " ".join(needle.casefold().split())
    name_cf = name.casefold()
    slug_cf = slug.casefold()
    if not needle:
        return False
    if needle in name_cf or needle == slug_cf or slug_cf in needle or name_cf in needle:
        return True
    aliases = _DEPARTMENT_ALIASES.get(slug_cf, ())
    return any(alias in needle or needle in alias for alias in aliases)


@router.get("/branches", response_model=VoiceBranchesResponse)
def list_branches(_: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    """Clinic branches the voice agent can offer when a caller asks where we operate."""
    items = db.scalars(
        select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)
    ).all()
    branches = [BranchOut.model_validate(item) for item in items]
    return VoiceBranchesResponse(branches=branches, count=len(branches))


@router.get("/doctors", response_model=VoiceDoctorsResponse)
def doctors(department: str | None = None, branch: str | None = None,
            _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.is_active.is_(True)).order_by(Doctor.name)).unique().all()
    all_items = items
    department = (department or "").strip() or None
    branch = (branch or "").strip() or None
    if department:
        needle = department
        filtered = [item for item in items if any(
            _department_match(needle, value.name, value.slug) for value in item.departments
        )]
        # Soft fallback: unknown colloquial phrases return the full list so the
        # agent can still offer options instead of failing the call.
        items = filtered or all_items
    active_rules = db.scalars(select(ScheduleRule).where(
        ScheduleRule.is_active.is_(True),
        or_(ScheduleRule.effective_until.is_(None), ScheduleRule.effective_until >= date.today()),
    )).all()
    branch_by_id = {
        item.id: item for item in db.scalars(
            select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)
        ).all()
    }
    scheduled_branches: dict[str, dict[str, set[str]]] = {}
    for rule in active_rules:
        modes = scheduled_branches.setdefault(rule.doctor_id, {
            "in_person": set(), "virtual": set(),
        })
        modes.setdefault(rule.consultation_type, set()).add(rule.branch_id)

    result = []
    for item in items:
        doctor = DoctorOut.model_validate(item)
        modes = scheduled_branches.get(item.id, {"in_person": set(), "virtual": set()})
        # A schedule is the source of truth for where each consultation mode is
        # actually bookable. Virtual-care branches need not be attached to a
        # doctor's physical profile locations.
        in_person = [branch_by_id[value] for value in modes["in_person"] if value in branch_by_id]
        virtual = [branch_by_id[value] for value in modes["virtual"] if value in branch_by_id]
        in_person.sort(key=lambda value: value.name)
        virtual.sort(key=lambda value: value.name)
        result.append(VoiceDoctorOut(
            **doctor.model_dump(exclude={"branches", "accepts_virtual"}),
            branches=in_person, in_person_branches=in_person, virtual_branches=virtual,
            accepts_virtual=bool(virtual),
        ))

    if branch:
        needle = branch.casefold()
        filtered = [item for item in result if any(
            needle in value.name.casefold() or needle in value.area.casefold() or needle == value.slug.casefold()
            for value in item.branches
        )]
        result = filtered or result
    return VoiceDoctorsResponse(doctors=result, count=len(result))


@router.get("/availability", response_model=AvailabilityResponse)
def get_availability(doctor_id: str, branch_id: str, start_date: date, end_date: date,
                     consultation_type: str | None = None,
                     _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    # Voice agents sometimes send an empty consultation_type; treat that as in-person
    # instead of failing request validation.
    if consultation_type not in ("in_person", "virtual"):
        consultation_type = "in_person"
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
        body = body.model_copy(update={"origin_channel": "voice"})
    return confirm_appointment(db, body)


@router.get("/appointments", response_model=VoiceAppointmentsResponse)
def appointment_lookup(patient_phone: str = Query(min_length=7, max_length=32),
                       confirmation_code: str | None = Query(default=None, min_length=4, max_length=20),
                       limit: int = Query(default=10, ge=1, le=25),
                       _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    """Look up a caller's appointments without exposing an unfiltered patient list."""
    statement = (
        select(Appointment)
        .where(Appointment.patient_phone == patient_phone.strip())
        .order_by(Appointment.created_at.desc())
        .limit(limit)
    )
    if confirmation_code:
        statement = statement.where(
            Appointment.confirmation_code == confirmation_code.strip().upper()
        )
    items = list(db.scalars(statement).unique().all())
    return VoiceAppointmentsResponse(appointments=items, count=len(items))


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
