import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import (
    Appointment, Branch, Department, Doctor, Reservation, ScheduleRule, VoiceSession,
    VoiceToolCall, utcnow,
)
from .schemas import (
    AppointmentCreate, AppointmentOut, AvailabilityResponse, DoctorOut, HoldCreate, HoldOut,
    VoiceBranchMetaOut, VoiceDepartmentMetaOut, VoiceDoctorOut, VoiceSessionCreate,
    VoiceSessionEnd, VoiceSessionEvent,
)
from .services import DomainError, availability, confirm_appointment, create_hold
from .voice_vocabulary import best_matches, branch_synonyms, department_synonyms

router = APIRouter(prefix="/api/v1/integrations/voice", tags=["voice-integration"])


def require_voice_service(x_service_key: str = Header(alias="X-Service-Key")) -> str:
    if not secrets.compare_digest(x_service_key, settings.voice_service_api_key):
        raise DomainError("SERVICE_AUTH_REQUIRED", "A valid voice service credential is required.", 401)
    return "voice-runtime"


@router.get("/doctors", response_model=list[VoiceDoctorOut])
def doctors(department: str | None = None, branch: str | None = None,
            _: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.is_active.is_(True)).order_by(Doctor.name)).unique().all()
    if department:
        departments = db.scalars(
            select(Department).where(Department.is_active.is_(True)).order_by(Department.name)
        ).all()
        matches = best_matches(department, departments, department_synonyms)
        # Unknown natural-language vocabulary is not a request error. Returning
        # the unfiltered directory lets the caller clarify or choose safely.
        if matches:
            matched_ids = {item.id for item in matches}
            items = [item for item in items if any(value.id in matched_ids for value in item.departments)]
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
        matches = best_matches(branch, branch_by_id.values(), branch_synonyms)
        if matches:
            matched_ids = {item.id for item in matches}
            result = [item for item in result if any(
                value.id in matched_ids
                for value in (*item.in_person_branches, *item.virtual_branches)
            )]
    return result


@router.get("/meta/departments", response_model=list[VoiceDepartmentMetaOut])
def department_vocabulary(_: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    items = db.scalars(
        select(Department).where(Department.is_active.is_(True)).order_by(Department.name)
    ).all()
    return [VoiceDepartmentMetaOut(
        slug=item.slug, name=item.name, synonyms=department_synonyms(item),
    ) for item in items]


@router.get("/meta/branches", response_model=list[VoiceBranchMetaOut])
def branch_vocabulary(_: str = Depends(require_voice_service), db: Session = Depends(get_db)):
    items = db.scalars(
        select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)
    ).all()
    return [VoiceBranchMetaOut(
        slug=item.slug, name=item.name, area=item.area, synonyms=branch_synonyms(item),
    ) for item in items]


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


@router.get("/appointments", response_model=list[AppointmentOut])
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
    return db.scalars(statement).unique().all()


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
