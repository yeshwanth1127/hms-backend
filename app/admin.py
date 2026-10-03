import secrets
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import (
    Appointment, AppointmentStatusHistory, Branch, Department, Doctor, OutboxEvent,
    Reservation, ScheduleRule,
    VoiceSession, utcnow,
)
from .schemas import AppointmentStatusUpdate, DoctorAdminUpdate, ScheduleRuleCreate, ScheduleRuleOut
from . import audit
from .permissions import require_capability
from .services import DomainError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(request: Request, x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"), db: Session = Depends(get_db)) -> str:
    # Legacy keys remain server-to-server compatibility only; the staff UI uses cookies.
    # Disabled in production: every production change must name a staff member.
    if x_admin_key and settings.app_env != "production" and secrets.compare_digest(
            x_admin_key.encode("latin-1", "replace"), settings.admin_api_key.encode()):
        from . import audit
        audit.actor("admin_key", "local-admin", "Local admin key")
        return "local-admin"
    from .staff_auth import current_staff
    user, _ = current_staff(request, db, mutate=request.method not in ("GET", "HEAD", "OPTIONS"))
    if user.role not in ("admin", "staff"):
        raise DomainError("STAFF_PERMISSION_DENIED", "Your account does not have access to clinic operations.", 403)
    return user.id


def _utc(value: datetime) -> datetime:
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
    # Aggregates in SQL: this dashboard polls, and the appointment table only grows.
    from .models import WhatsAppOutbound
    now = datetime.now(timezone.utc)
    count = lambda model, *where: db.scalar(select(func.count()).select_from(model).where(*where))
    by_status = dict(db.execute(select(Appointment.status, func.count()).group_by(Appointment.status)).all())
    by_channel = dict(db.execute(select(Appointment.origin_channel, func.count()).group_by(Appointment.origin_channel)).all())
    total = sum(by_status.values())
    first_day = (now - timedelta(days=13)).date()
    created = db.scalars(select(Appointment.created_at).where(
        Appointment.created_at >= datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc))).all()
    per_day = Counter(_utc(value).date() for value in created)
    daily = [{"date": (first_day + timedelta(days=i)).isoformat(), "bookings": per_day.get(first_day + timedelta(days=i), 0)} for i in range(14)]
    confirmed = by_status.get("confirmed", 0) + by_status.get("checked_in", 0) + by_status.get("completed", 0)
    recent = db.scalars(select(Appointment).order_by(Appointment.created_at.desc()).limit(6)).all()
    return {
        "generated_at": now,
        "summary": {
            "appointments_total": total,
            "appointments_confirmed": confirmed,
            "appointments_cancelled": by_status.get("cancelled", 0),
            "appointments_upcoming": db.scalar(select(func.count()).select_from(Appointment).join(Reservation, Appointment.reservation_id == Reservation.id)
                                               .where(Appointment.status == "confirmed", Reservation.starts_at >= now)),
            "active_holds": count(Reservation, Reservation.status == "active", Reservation.expires_at > now),
            "active_doctors": count(Doctor, Doctor.is_active.is_(True)),
            "schedule_rules": count(ScheduleRule, ScheduleRule.is_active.is_(True)),
            "pending_notifications": count(WhatsAppOutbound, WhatsAppOutbound.status.in_(("pending", "claimed"))),
            "conversion_rate": round((confirmed / total * 100) if total else 0, 1),
            "voice_sessions_total": count(VoiceSession),
            "voice_bookings": sum(by_channel.get(key, 0) for key in ("voice", "web_voice", "phone")),
        },
        "by_status": [{"label": key, "value": value} for key, value in sorted(by_status.items())],
        "by_channel": [{"label": key, "value": value} for key, value in sorted(by_channel.items())],
        "daily_bookings": daily,
        "recent_appointments": [_appointment_row(db, item) for item in recent],
    }


@router.get("/appointments")
def appointments(status: str | None = None, query: str | None = None,
                 day: date | None = None, doctor_id: str | None = None,
                 branch_id: str | None = None, offset: int = Query(0, ge=0),
                 limit: int = Query(100, ge=1, le=500), _: str = Depends(require_admin),
                 db: Session = Depends(get_db)):
    statement = select(Appointment).join(Reservation, Appointment.reservation_id == Reservation.id).join(Doctor, Reservation.doctor_id == Doctor.id)
    if day:
        start = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata"))
        statement = statement.where(Reservation.starts_at >= start.astimezone(timezone.utc),
                                    Reservation.starts_at < (start + timedelta(days=1)).astimezone(timezone.utc))
    if doctor_id:
        statement = statement.where(Reservation.doctor_id == doctor_id)
    if branch_id:
        statement = statement.where(Reservation.branch_id == branch_id)
    if status and status != "all":
        statement = statement.where(Appointment.status == status)
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(Appointment.patient_name.ilike(pattern),
                                        Appointment.patient_phone.ilike(pattern),
                                        Appointment.confirmation_code.ilike(pattern), Doctor.name.ilike(pattern)))
    statement = statement.order_by(Reservation.starts_at, Appointment.id).offset(offset).limit(limit)
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
    audit.note(targets={"code": item.confirmation_code}, status={"from": previous, "to": body.status})
    item.status = body.status
    if body.status == "cancelled":
        item.reservation.status = "released"
    db.add(AppointmentStatusHistory(appointment_id=item.id, from_status=previous, to_status=body.status,
                                    actor_type="administrator", actor_id=admin_id, reason=body.reason))
    db.add(OutboxEvent(event_type=f"appointment.{body.status}", aggregate_id=item.id,
                       payload={"appointment_id": item.id, "confirmation_code": item.confirmation_code}))
    from .whatsapp_outreach import notify_change, queue_followup
    notification = {}
    if body.status in {"completed", "no_show"}:
        queue_followup(db, item, "feedback" if body.status == "completed" else "no_show")
    elif body.status == "cancelled":
        notification = notify_change(db, item, "cancelled")
    db.commit()
    db.refresh(item)
    return {**_appointment_row(db, item), **notification}


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
def update_doctor(doctor_id: str, body: DoctorAdminUpdate, request: Request,
                  _: str = Depends(require_capability("doctors.manage")), db: Session = Depends(get_db)):
    item = db.scalar(select(Doctor).where(Doctor.id == doctor_id).with_for_update())
    if not item:
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    changes = body.model_dump(exclude_unset=True)
    before = {key: getattr(item, key) for key in changes}
    user = getattr(request.state, "staff_user", None)
    if "consultation_fee" in changes and changes["consultation_fee"] != item.consultation_fee and user and user.role != "admin":
        raise DomainError("FEE_ADMIN_ONLY", "Only a clinic administrator can change consultation fees.", 403)
    audit.note(**audit.diff(before, changes))
    for key, value in changes.items():
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
def create_schedule(body: ScheduleRuleCreate, _: str = Depends(require_capability("schedules.manage")), db: Session = Depends(get_db)):
    if body.ends_at_local <= body.starts_at_local:
        raise DomainError("INVALID_SCHEDULE", "Schedule end time must be after start time.", 422)
    if not db.scalar(select(Doctor).where(Doctor.id == body.doctor_id).with_for_update()) or not db.get(Branch, body.branch_id):
        raise DomainError("CATALOGUE_ITEM_NOT_FOUND", "Doctor or branch was not found.", 404)
    item = ScheduleRule(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    audit.note(targets={"schedule_id": item.id, "doctor_id": item.doctor_id}, added=body.model_dump(mode="json"))
    return item


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, _: str = Depends(require_capability("schedules.manage")), db: Session = Depends(get_db)):
    item = db.get(ScheduleRule, schedule_id)
    if not item:
        raise DomainError("SCHEDULE_NOT_FOUND", "Schedule rule was not found.", 404)
    audit.note(targets={"doctor_id": item.doctor_id}, removed=ScheduleRuleOut.model_validate(item).model_dump(mode="json"))
    db.scalar(select(Doctor).where(Doctor.id == item.doctor_id).with_for_update())
    db.delete(item)
    db.commit()


@router.get("/catalogue")
def catalogue(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "branches": [{"id": item.id, "name": item.name, "area": item.area, "is_active": item.is_active, "is_virtual": item.is_virtual, "address": item.address, "directions_url": item.directions_url, "arrival_instructions": item.arrival_instructions}
                     for item in db.scalars(select(Branch).order_by(Branch.name)).all()],
        "departments": [{"id": item.id, "name": item.name, "slug": item.slug, "is_active": item.is_active}
                        for item in db.scalars(select(Department).order_by(Department.name)).all()],
    }


@router.get("/operations")
def operations(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    events = db.scalars(select(OutboxEvent).where(OutboxEvent.event_type != "demo.website_activity").order_by(OutboxEvent.created_at.desc()).limit(100)).all()
    return [{"id": item.id, "event_type": item.event_type, "aggregate_id": item.aggregate_id,
             "created_at": item.created_at, "processed_at": item.processed_at,
             "status": "delivered" if item.processed_at else "pending"} for item in events]


@router.get("/voice-sessions")
def voice_sessions(limit: int = Query(100, ge=1, le=500), _: str = Depends(require_admin),
                   db: Session = Depends(get_db)):
    from .client_modules import ensure_module
    ensure_module(db, "voice")
    items = db.scalars(select(VoiceSession).order_by(VoiceSession.started_at.desc()).limit(limit)).all()
    return [{
        "id": item.id, "runtime_session_id": item.runtime_session_id, "status": item.status,
        "channel": item.channel, "turn_count": item.turn_count, "tool_call_count": item.tool_call_count,
        "last_intent": item.last_intent, "appointment_id": item.appointment_id,
        "started_at": item.started_at, "ended_at": item.ended_at,
    } for item in items]
