import secrets
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import (
    Appointment, AppointmentStatusHistory, Branch, Department, Doctor, Hospital, OutboxEvent,
    Reservation, ScheduleRule, Teleconsultation, TeleconsultationConsent,
    User, VoiceSession,
)
from .schemas import AppointmentCreate, AppointmentStatusUpdate, DoctorAdminUpdate, ScheduleRuleCreate, ScheduleRuleOut
from .services import DomainError, confirm_appointment
from .auth import Actor, optional_actor

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class VirtualOpdCreate(BaseModel):
    doctor_id: str
    patient_name: str = Field(min_length=2, max_length=160)
    patient_phone: str = Field(min_length=7, max_length=32)
    patient_email: EmailStr | None = None
    reason: str | None = Field(default=None, max_length=800)
    starts_at: datetime
    duration_minutes: int = Field(default=30, ge=10, le=180)
    idempotency_key: str = Field(min_length=8, max_length=120)


def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                  actor: Actor | None = Depends(optional_actor), db: Session = Depends(get_db)) -> Actor:
    if actor and actor.role == "hospital_admin":
        return actor
    if x_admin_key and secrets.compare_digest(x_admin_key, settings.admin_api_key):
        hospital = db.scalar(select(Hospital).order_by(Hospital.created_at).limit(1))
        if hospital:
            return Actor("break-glass-admin", "break-glass", hospital.id, "hospital_admin", "Break-glass administrator")
    raise DomainError("ADMIN_AUTH_REQUIRED", "A valid administrator session is required.", 401)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _appointment_row(db: Session, item: Appointment) -> dict:
    reservation = item.reservation
    doctor = db.get(Doctor, reservation.doctor_id)
    branch = db.get(Branch, reservation.branch_id)
    consultation = db.scalar(select(Teleconsultation).where(
        Teleconsultation.appointment_id == item.id)) if reservation.consultation_type == "virtual" else None
    consent = bool(consultation and db.scalar(select(TeleconsultationConsent.id).where(
        TeleconsultationConsent.teleconsultation_id == consultation.id,
        TeleconsultationConsent.withdrawn_at.is_(None))))
    return {
        "id": item.id, "confirmation_code": item.confirmation_code,
        "patient_name": item.patient_name, "patient_phone": item.patient_phone,
        "patient_email": item.patient_email, "reason": item.reason,
        "status": item.status, "origin_channel": item.origin_channel,
        "created_at": item.created_at, "starts_at": reservation.starts_at,
        "ends_at": reservation.ends_at, "consultation_type": reservation.consultation_type,
        "doctor": {"id": doctor.id, "name": doctor.name} if doctor else None,
        "branch": {"id": branch.id, "name": branch.name, "area": branch.area} if branch else None,
        "teleconsultation_status": consultation.status if consultation else None,
        "consent_accepted": consent,
    }


@router.get("/analytics")
def analytics(actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    appointments = db.scalars(select(Appointment).where(Appointment.hospital_id == actor.hospital_id).order_by(Appointment.created_at)).all()
    reservations = db.scalars(select(Reservation).where(Reservation.hospital_id == actor.hospital_id)).all()
    doctors = db.scalars(select(Doctor).where(Doctor.hospital_id == actor.hospital_id)).all()
    rules = db.scalars(select(ScheduleRule).where(ScheduleRule.hospital_id == actor.hospital_id)).all()
    pending_outbox = db.scalars(select(OutboxEvent).where(OutboxEvent.processed_at.is_(None))).all()
    voice_sessions = db.scalars(select(VoiceSession)).all()
    by_status = Counter(item.status for item in appointments)
    by_channel = Counter(item.origin_channel for item in appointments)
    daily = []
    for offset in range(13, -1, -1):
        day = (now - timedelta(days=offset)).date()
        daily.append({
            "date": day.isoformat(),
            "bookings": sum(1 for item in appointments if _utc(item.created_at).date() == day),
        })
    confirmed = by_status.get("confirmed", 0) + by_status.get("checked_in", 0) + by_status.get("completed", 0)
    return {
        "generated_at": now,
        "summary": {
            "appointments_total": len(appointments),
            "appointments_confirmed": confirmed,
            "appointments_cancelled": by_status.get("cancelled", 0),
            "appointments_upcoming": sum(1 for item in appointments if item.status == "confirmed" and _utc(item.reservation.starts_at) >= now),
            "active_holds": sum(1 for item in reservations if item.status == "active" and item.expires_at and _utc(item.expires_at) > now),
            "active_doctors": sum(1 for item in doctors if item.is_active),
            "schedule_rules": sum(1 for item in rules if item.is_active),
            "pending_notifications": len(pending_outbox),
            "conversion_rate": round((confirmed / len(appointments) * 100) if appointments else 0, 1),
            "voice_sessions_total": len(voice_sessions),
            "voice_bookings": sum(1 for item in appointments if item.origin_channel == "voice"),
        },
        "by_status": [{"label": key, "value": value} for key, value in sorted(by_status.items())],
        "by_channel": [{"label": key, "value": value} for key, value in sorted(by_channel.items())],
        "daily_bookings": daily,
        "recent_appointments": [_appointment_row(db, item) for item in appointments[-6:]][::-1],
    }


@router.get("/appointments")
def appointments(status: str | None = None, query: str | None = None,
                 limit: int = Query(100, ge=1, le=500), actor: Actor = Depends(require_admin),
                 db: Session = Depends(get_db)):
    statement = select(Appointment).where(Appointment.hospital_id == actor.hospital_id).order_by(Appointment.created_at.desc()).limit(limit)
    if status and status != "all":
        statement = statement.where(Appointment.status == status)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(Appointment.patient_name.ilike(pattern),
                                        Appointment.patient_phone.ilike(pattern),
                                        Appointment.confirmation_code.ilike(pattern)))
    return [_appointment_row(db, item) for item in db.scalars(statement).all()]


@router.get("/virtual-opd")
def virtual_opd_appointments(limit: int = Query(200, ge=1, le=500),
                             actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(Appointment).join(Reservation).where(
        Appointment.hospital_id == actor.hospital_id,
        Reservation.consultation_type == "virtual",
    ).order_by(Reservation.starts_at.desc()).limit(limit)).all()
    return [_appointment_row(db, item) for item in items]


@router.post("/virtual-opd", status_code=201)
def create_virtual_opd(body: VirtualOpdCreate, actor: Actor = Depends(require_admin),
                       db: Session = Depends(get_db)):
    doctor = db.scalar(select(Doctor).where(Doctor.id == body.doctor_id,
                                            Doctor.hospital_id == actor.hospital_id,
                                            Doctor.is_active.is_(True)))
    if not doctor or not doctor.accepts_virtual:
        raise DomainError("VIRTUAL_DOCTOR_UNAVAILABLE", "Choose an active doctor enabled for virtual care.", 422)
    branch = db.scalar(select(Branch).where(Branch.hospital_id == actor.hospital_id,
                                            Branch.is_virtual.is_(True),
                                            Branch.is_active.is_(True)).limit(1))
    if not branch:
        raise DomainError("VIRTUAL_BRANCH_REQUIRED", "Configure an active Virtual Care branch first.", 422)
    starts_at = _utc(body.starts_at)
    ends_at = starts_at + timedelta(minutes=body.duration_minutes)
    now = datetime.now(timezone.utc)
    if starts_at <= now:
        raise DomainError("INVALID_SLOT", "Virtual OPD appointments must be scheduled in the future.", 422)
    conflict = db.scalar(select(Reservation.id).where(
        Reservation.doctor_id == doctor.id,
        Reservation.status.in_(["active", "booked"]),
        Reservation.starts_at < ends_at,
        Reservation.ends_at > starts_at,
    ))
    if conflict:
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "The doctor already has an appointment at that time.", 409)
    owner_key = f"staff-{actor.user_id}"
    hold = Reservation(hospital_id=actor.hospital_id, doctor_id=doctor.id, branch_id=branch.id,
                       consultation_type="virtual", starts_at=starts_at, ends_at=ends_at,
                       status="active", owner_key=owner_key,
                       expires_at=now + timedelta(minutes=10),
                       idempotency_key=f"{body.idempotency_key}-hold")
    db.add(hold)
    try:
        db.flush()
        appointment = confirm_appointment(db, AppointmentCreate(
            hold_id=hold.id, owner_key=owner_key, patient_name=body.patient_name,
            patient_phone=body.patient_phone, patient_email=body.patient_email,
            reason=body.reason, origin_channel="staff", consent_to_reminders=False,
            idempotency_key=body.idempotency_key,
        ))
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "The doctor already has an appointment at that time.", 409) from exc
    return _appointment_row(db, appointment)


@router.patch("/appointments/{appointment_id}/status")
def appointment_status(appointment_id: str, body: AppointmentStatusUpdate,
                       actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id,
                                               Appointment.hospital_id == actor.hospital_id))
    if not item:
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    allowed = {
        "confirmed": {"checked_in", "cancelled", "no_show"},
        "checked_in": {"completed", "cancelled"},
        "completed": set(), "cancelled": set(), "no_show": set(),
    }
    if body.status == item.status:
        return _appointment_row(db, item)
    if body.status not in allowed.get(item.status, set()):
        raise DomainError("INVALID_STATUS_TRANSITION", f"Cannot change {item.status} to {body.status}.", 409)
    previous = item.status
    item.status = body.status
    if body.status == "cancelled":
        item.reservation.status = "released"
    if item.reservation.consultation_type == "virtual" and body.status in {"completed", "cancelled", "no_show"}:
        consultation = db.scalar(select(Teleconsultation).where(Teleconsultation.appointment_id == item.id))
        if consultation:
            consultation.status = body.status
    db.add(AppointmentStatusHistory(appointment_id=item.id, from_status=previous, to_status=body.status,
                                    actor_type="administrator", actor_id=actor.user_id, reason=body.reason))
    db.add(OutboxEvent(event_type=f"appointment.{body.status}", aggregate_id=item.id,
                       payload={"appointment_id": item.id, "confirmation_code": item.confirmation_code}))
    db.commit()
    db.refresh(item)
    return _appointment_row(db, item)


@router.get("/doctors")
def admin_doctors(actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.hospital_id == actor.hospital_id).order_by(Doctor.name)).unique().all()
    return [{
        "id": item.id, "slug": item.slug, "name": item.name, "title": item.title,
        "consultation_fee": item.consultation_fee, "accepts_virtual": item.accepts_virtual,
        "is_active": item.is_active,
        "login_email": db.get(User, item.user_id).email if item.user_id and db.get(User, item.user_id) else None,
        "departments": [{"id": value.id, "name": value.name} for value in item.departments],
        "branches": [{"id": value.id, "name": value.name} for value in item.branches],
    } for item in items]


@router.patch("/doctors/{doctor_id}")
def update_doctor(doctor_id: str, body: DoctorAdminUpdate,
                  actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.hospital_id == actor.hospital_id))
    if not item:
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return {"id": item.id, "is_active": item.is_active, "consultation_fee": item.consultation_fee,
            "accepts_virtual": item.accepts_virtual}


@router.get("/schedules", response_model=list[ScheduleRuleOut])
def schedules(doctor_id: str | None = None, actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    statement = select(ScheduleRule).where(ScheduleRule.hospital_id == actor.hospital_id).order_by(ScheduleRule.schedule_date, ScheduleRule.starts_at_local)
    if doctor_id:
        statement = statement.where(ScheduleRule.doctor_id == doctor_id)
    return db.scalars(statement).all()


@router.post("/schedules", response_model=ScheduleRuleOut, status_code=201)
def create_schedule(body: ScheduleRuleCreate, actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    if body.ends_at_local <= body.starts_at_local:
        raise DomainError("INVALID_SCHEDULE", "Schedule end time must be after start time.", 422)
    doctor = db.scalar(select(Doctor).where(Doctor.id == body.doctor_id, Doctor.hospital_id == actor.hospital_id))
    branch = db.scalar(select(Branch).where(Branch.id == body.branch_id, Branch.hospital_id == actor.hospital_id))
    if not doctor or not branch:
        raise DomainError("CATALOGUE_ITEM_NOT_FOUND", "Doctor or branch was not found.", 404)
    item = ScheduleRule(hospital_id=actor.hospital_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.scalar(select(ScheduleRule).where(ScheduleRule.id == schedule_id,
                                                ScheduleRule.hospital_id == actor.hospital_id))
    if not item:
        raise DomainError("SCHEDULE_NOT_FOUND", "Schedule rule was not found.", 404)
    db.delete(item)
    db.commit()


@router.get("/catalogue")
def catalogue(actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "branches": [{"id": item.id, "slug": item.slug, "name": item.name, "area": item.area,
                      "is_active": item.is_active, "is_virtual": item.is_virtual}
                     for item in db.scalars(select(Branch).where(Branch.hospital_id == actor.hospital_id).order_by(Branch.name)).all()],
        "departments": [{"id": item.id, "name": item.name, "slug": item.slug, "is_active": item.is_active}
                        for item in db.scalars(select(Department).where(Department.hospital_id == actor.hospital_id).order_by(Department.name)).all()],
    }


@router.get("/operations")
def operations(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    events = db.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at.desc()).limit(100)).all()
    return [{"id": item.id, "event_type": item.event_type, "aggregate_id": item.aggregate_id,
             "created_at": item.created_at, "processed_at": item.processed_at,
             "status": "delivered" if item.processed_at else "pending"} for item in events]


@router.get("/voice-sessions")
def voice_sessions(limit: int = Query(100, ge=1, le=500), _: str = Depends(require_admin),
                   db: Session = Depends(get_db)):
    items = db.scalars(select(VoiceSession).order_by(VoiceSession.started_at.desc()).limit(limit)).all()
    return [{
        "id": item.id, "runtime_session_id": item.runtime_session_id, "status": item.status,
        "channel": item.channel, "turn_count": item.turn_count, "tool_call_count": item.tool_call_count,
        "last_intent": item.last_intent, "appointment_id": item.appointment_id,
        "started_at": item.started_at, "ended_at": item.ended_at,
    } for item in items]
