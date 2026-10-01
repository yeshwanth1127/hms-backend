import secrets
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import (
    Appointment, AppointmentStatusHistory, Branch, Department, Doctor, OutboxEvent,
    Reservation, ScheduleRule,
    VoiceSession, utcnow,
)
from .schemas import AppointmentStatusUpdate, DoctorAdminUpdate, ScheduleRuleCreate, ScheduleRuleOut
from .services import DomainError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(request: Request, x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"), db: Session = Depends(get_db)) -> str:
    # Legacy keys remain server-to-server compatibility only; the staff UI uses cookies.
    if x_admin_key and secrets.compare_digest(x_admin_key, settings.admin_api_key):
        return "local-admin"
    from .staff_auth import current_staff
    user, _ = current_staff(request, db, mutate=request.method not in ("GET", "HEAD", "OPTIONS"))
    if user.role not in ("admin", "staff"):
        raise DomainError("STAFF_PERMISSION_DENIED", "Your account does not have access to clinic operations.", 403)
    return user.id


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _appointment_row(db: Session, item: Appointment) -> dict:
    reservation = item.reservation
    doctor = db.get(Doctor, reservation.doctor_id)
    branch = db.get(Branch, reservation.branch_id)
    return {
        "id": item.id, "confirmation_code": item.confirmation_code,
        "patient_name": item.patient_name, "patient_phone": item.patient_phone,
        "patient_email": item.patient_email, "reason": item.reason,
        "status": item.status, "origin_channel": item.origin_channel,
        "created_at": _utc(item.created_at), "starts_at": _utc(reservation.starts_at),
        "ends_at": _utc(reservation.ends_at), "consultation_type": reservation.consultation_type,
        "doctor": {"id": doctor.id, "name": doctor.name} if doctor else None,
        "branch": {"id": branch.id, "name": branch.name, "area": branch.area} if branch else None,
    }


@router.get("/analytics")
def analytics(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    appointments = db.scalars(select(Appointment).order_by(Appointment.created_at)).all()
    reservations = db.scalars(select(Reservation)).all()
    doctors = db.scalars(select(Doctor)).all()
    rules = db.scalars(select(ScheduleRule)).all()
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
                 limit: int = Query(100, ge=1, le=500), _: str = Depends(require_admin),
                 db: Session = Depends(get_db)):
    statement = select(Appointment).order_by(Appointment.created_at.desc()).limit(limit)
    if status and status != "all":
        statement = statement.where(Appointment.status == status)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(Appointment.patient_name.ilike(pattern),
                                        Appointment.patient_phone.ilike(pattern),
                                        Appointment.confirmation_code.ilike(pattern)))
    return [_appointment_row(db, item) for item in db.scalars(statement).all()]


@router.patch("/appointments/{appointment_id}/status")
def appointment_status(appointment_id: str, body: AppointmentStatusUpdate,
                       admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update(of=Appointment))
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
    visit_start = item.reservation.starts_at
    visit_start = visit_start.replace(tzinfo=timezone.utc) if visit_start.tzinfo is None else visit_start.astimezone(timezone.utc)
    if body.status in {"completed", "no_show"} and visit_start > utcnow():
        raise DomainError("VISIT_NOT_STARTED", "A future visit cannot be marked completed or no-show.", 409)
    previous = item.status
    item.status = body.status
    if body.status == "cancelled":
        item.reservation.status = "released"
    db.add(AppointmentStatusHistory(appointment_id=item.id, from_status=previous, to_status=body.status,
                                    actor_type="administrator", actor_id=admin_id, reason=body.reason))
    db.add(OutboxEvent(event_type=f"appointment.{body.status}", aggregate_id=item.id,
                       payload={"appointment_id": item.id, "confirmation_code": item.confirmation_code}))
    if body.status in {"completed", "no_show"}:
        from .whatsapp_outreach import queue_followup
        queue_followup(db, item, "feedback" if body.status == "completed" else "no_show")
    db.commit()
    db.refresh(item)
    return _appointment_row(db, item)


@router.get("/doctors")
def admin_doctors(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).order_by(Doctor.name)).unique().all()
    return [{
        "id": item.id, "slug": item.slug, "name": item.name, "title": item.title,
        "consultation_fee": item.consultation_fee, "accepts_virtual": item.accepts_virtual,
        "is_active": item.is_active,
        "departments": [{"id": value.id, "name": value.name} for value in item.departments],
        "branches": [{"id": value.id, "name": value.name} for value in item.branches],
    } for item in items]


@router.patch("/doctors/{doctor_id}")
def update_doctor(doctor_id: str, body: DoctorAdminUpdate,
                  _: str = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(Doctor, doctor_id)
    if not item:
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return {"id": item.id, "is_active": item.is_active, "consultation_fee": item.consultation_fee,
            "accepts_virtual": item.accepts_virtual}


@router.get("/schedules", response_model=list[ScheduleRuleOut])
def schedules(doctor_id: str | None = None, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    statement = select(ScheduleRule).order_by(ScheduleRule.schedule_date, ScheduleRule.starts_at_local)
    if doctor_id:
        statement = statement.where(ScheduleRule.doctor_id == doctor_id)
    return db.scalars(statement).all()


@router.post("/schedules", response_model=ScheduleRuleOut, status_code=201)
def create_schedule(body: ScheduleRuleCreate, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if body.ends_at_local <= body.starts_at_local:
        raise DomainError("INVALID_SCHEDULE", "Schedule end time must be after start time.", 422)
    if not db.get(Doctor, body.doctor_id) or not db.get(Branch, body.branch_id):
        raise DomainError("CATALOGUE_ITEM_NOT_FOUND", "Doctor or branch was not found.", 404)
    item = ScheduleRule(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(ScheduleRule, schedule_id)
    if not item:
        raise DomainError("SCHEDULE_NOT_FOUND", "Schedule rule was not found.", 404)
    db.delete(item)
    db.commit()


@router.get("/catalogue")
def catalogue(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "branches": [{"id": item.id, "name": item.name, "area": item.area, "is_active": item.is_active, "address": item.address, "directions_url": item.directions_url, "arrival_instructions": item.arrival_instructions}
                     for item in db.scalars(select(Branch).order_by(Branch.name)).all()],
        "departments": [{"id": item.id, "name": item.name, "slug": item.slug, "is_active": item.is_active}
                        for item in db.scalars(select(Department).order_by(Department.name)).all()],
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
