import secrets
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Appointment, AppointmentStatusHistory, Branch, Doctor, OutboxEvent,
    ReminderJob, Reservation, ScheduleException, ScheduleRule, utcnow,
)
from .schemas import AppointmentCreate, AvailabilitySlot, HoldCreate


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise DomainError("TIMEZONE_REQUIRED", "Appointment times must include a timezone.", 422)
    return value.astimezone(timezone.utc)


def _db_utc(value: datetime) -> datetime:
    """SQLite drops offsets; production PostgreSQL preserves them."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def expire_holds(db: Session, now: datetime | None = None) -> None:
    now = now or utcnow()
    db.execute(update(Reservation).where(
        Reservation.status == "active", Reservation.expires_at <= now
    ).values(status="expired").execution_options(synchronize_session="fetch"))


def availability(db: Session, doctor_id: str, branch_id: str, start_date: date, end_date: date,
                 consultation_type: str = "in_person", *, exclude_reservation_id: str | None = None,
                 commit: bool = True) -> tuple[list[AvailabilitySlot], str]:
    if end_date < start_date or (end_date - start_date).days > 31:
        raise DomainError("INVALID_DATE_RANGE", "Choose a date range of 31 days or less.", 422)
    doctor = db.get(Doctor, doctor_id)
    branch = db.get(Branch, branch_id)
    if not doctor or not doctor.is_active or not branch or not branch.is_active:
        raise DomainError("CATALOGUE_ITEM_NOT_FOUND", "Doctor or branch was not found.", 404)
    now = utcnow()
    expire_holds(db, now)
    rules = db.scalars(select(ScheduleRule).where(
        ScheduleRule.doctor_id == doctor_id, ScheduleRule.branch_id == branch_id,
        ScheduleRule.consultation_type == consultation_type, ScheduleRule.is_active.is_(True),
        ScheduleRule.schedule_date <= end_date,
        or_(ScheduleRule.effective_until.is_(None), ScheduleRule.effective_until >= start_date),
    )).all()
    range_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
    range_end = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc) + timedelta(days=1)
    exceptions = db.scalars(select(ScheduleException).where(
        ScheduleException.doctor_id == doctor_id,
        ScheduleException.starts_at < range_end, ScheduleException.ends_at > range_start,
        or_(ScheduleException.branch_id.is_(None), ScheduleException.branch_id == branch_id),
    )).all()
    busy_query = select(Reservation).where(
        Reservation.doctor_id == doctor_id, Reservation.status.in_(["active", "booked"]),
        Reservation.starts_at < range_end, Reservation.ends_at > range_start,
    )
    if exclude_reservation_id:
        busy_query = busy_query.where(Reservation.id != exclude_reservation_id)
    busy = db.scalars(busy_query).all()
    zone = ZoneInfo(branch.timezone)
    slots: list[AvailabilitySlot] = []
    cursor = start_date
    while cursor <= end_date:
        for rule in rules:
            if (rule.weekday != cursor.weekday() or cursor < rule.schedule_date
                    or cursor < rule.effective_from
                    or (rule.effective_until and cursor > rule.effective_until)):
                continue
            local_start = datetime.combine(cursor, rule.starts_at_local, tzinfo=zone)
            local_end = datetime.combine(cursor, rule.ends_at_local, tzinfo=zone)
            slot_start = local_start.astimezone(timezone.utc)
            while slot_start + timedelta(minutes=rule.slot_minutes) <= local_end.astimezone(timezone.utc):
                slot_end = slot_start + timedelta(minutes=rule.slot_minutes)
                blocked = any(_db_utc(item.starts_at) < slot_end and _db_utc(item.ends_at) > slot_start for item in exceptions)
                occupied = any(_db_utc(item.starts_at) < slot_end and _db_utc(item.ends_at) > slot_start for item in busy)
                if slot_start > now and not blocked and not occupied:
                    slots.append(AvailabilitySlot(doctor_id=doctor_id, branch_id=branch_id,
                                                  consultation_type=consultation_type,
                                                  starts_at=slot_start, ends_at=slot_end))
                slot_start = slot_end
        cursor += timedelta(days=1)
    if commit:
        db.commit()
    unique = {(item.starts_at, item.ends_at): item for item in slots}
    return sorted(unique.values(), key=lambda item: item.starts_at), branch.timezone


def create_hold(db: Session, body: HoldCreate, *, commit: bool = True) -> Reservation:
    existing = db.scalar(select(Reservation).where(Reservation.idempotency_key == body.idempotency_key))
    if existing:
        if (existing.owner_key != body.owner_key or existing.doctor_id != body.doctor_id
                or existing.branch_id != body.branch_id or existing.consultation_type != body.consultation_type
                or _db_utc(existing.starts_at) != _aware_utc(body.starts_at)
                or _db_utc(existing.ends_at) != _aware_utc(body.ends_at)):
            raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
        return existing
    # Serialize every channel's slot allocation per doctor, including overlapping rules.
    db.scalar(select(Doctor).where(Doctor.id == body.doctor_id).with_for_update())
    if db.scalar(select(Reservation).where(Reservation.idempotency_key == body.idempotency_key)):
        return create_hold(db, body, commit=commit)
    starts_at, ends_at = _aware_utc(body.starts_at), _aware_utc(body.ends_at)
    if starts_at <= utcnow() or ends_at <= starts_at:
        raise DomainError("INVALID_SLOT", "The selected slot must be in the future.", 422)
    candidates, _ = availability(db, body.doctor_id, body.branch_id, (starts_at - timedelta(days=1)).date(), (ends_at + timedelta(days=1)).date(), body.consultation_type, commit=False)
    if not any(item.starts_at == starts_at and item.ends_at == ends_at for item in candidates):
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "That appointment time is no longer available.", 409)
    hold = Reservation(doctor_id=body.doctor_id, branch_id=body.branch_id,
                       consultation_type=body.consultation_type, starts_at=starts_at, ends_at=ends_at,
                       owner_key=body.owner_key, expires_at=utcnow() + timedelta(minutes=settings.slot_hold_minutes),
                       idempotency_key=body.idempotency_key, status="active")
    db.add(hold)
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = db.scalar(select(Reservation).where(Reservation.idempotency_key == body.idempotency_key))
        if replay:
            return create_hold(db, body, commit=commit)
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "That appointment time is no longer available.", 409) from exc
    db.refresh(hold)
    return hold


def validate_booking_replay(item: Appointment, body: AppointmentCreate) -> Appointment:
    if (item.reservation_id != body.hold_id or item.reservation.owner_key != body.owner_key
            or item.patient_phone != body.patient_phone.strip() or item.patient_name != body.patient_name.strip()):
        raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
    return item


def validate_held_slot(db: Session, hold: Reservation) -> None:
    starts, ends = _db_utc(hold.starts_at), _db_utc(hold.ends_at)
    candidates, _ = availability(db, hold.doctor_id, hold.branch_id,
        (starts - timedelta(days=1)).date(), (ends + timedelta(days=1)).date(), hold.consultation_type,
        exclude_reservation_id=hold.id, commit=False)
    if not any(slot.starts_at == starts and slot.ends_at == ends for slot in candidates):
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "That appointment time is no longer available. Choose a new time.", 409)


def confirm_appointment(db: Session, body: AppointmentCreate, *, commit: bool = True) -> Appointment:
    existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == body.idempotency_key))
    if existing:
        return validate_booking_replay(existing, body)
    # Use the same doctor lock as allocation and schedule changes.
    candidate = db.get(Reservation, body.hold_id)
    if candidate:
        db.scalar(select(Doctor).where(Doctor.id == candidate.doctor_id).with_for_update())
    hold = db.scalar(select(Reservation).where(Reservation.id == body.hold_id).with_for_update())
    if not hold or hold.owner_key != body.owner_key:
        raise DomainError("HOLD_NOT_FOUND", "The slot hold was not found.", 404)
    # A concurrent request may have committed while we waited for the hold.
    existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == body.idempotency_key))
    if existing:
        return validate_booking_replay(existing, body)
    now = utcnow()
    expires_at = hold.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if hold.status != "active" or not expires_at or expires_at <= now:
        if hold.status == "active":
            hold.status = "expired"
            db.commit()
        raise DomainError("HOLD_EXPIRED", "The slot hold has expired. Please select a new time.", 409)
    validate_held_slot(db, hold)
    appointment = Appointment(
        confirmation_code=f"AVO-{secrets.token_hex(8).upper()}", reservation_id=hold.id,
        consultation_fee=db.get(Doctor, hold.doctor_id).consultation_fee,
        patient_name=body.patient_name.strip(), patient_phone=body.patient_phone.strip(),
        patient_email=str(body.patient_email) if body.patient_email else None,
        reason=body.reason.strip() if body.reason else None, origin_channel=body.origin_channel,
        acquisition_source=body.acquisition_source, is_demo=settings.app_env != "production",
        consent_to_reminders=body.consent_to_reminders,
        idempotency_key=body.idempotency_key, status="confirmed",
    )
    db.add(appointment)
    db.flush()
    hold.status = "booked"
    hold.expires_at = None
    db.add(AppointmentStatusHistory(appointment_id=appointment.id, from_status=None, to_status="confirmed",
                                    actor_type=body.origin_channel, actor_id=body.owner_key))
    db.add(OutboxEvent(event_type="appointment.confirmed", aggregate_id=appointment.id,
                       payload={"appointment_id": appointment.id, "confirmation_code": appointment.confirmation_code}))
    if body.origin_channel == "whatsapp" and body.consent_to_reminders:
        due_at = max(now, _db_utc(hold.starts_at) - timedelta(days=1))
        db.add(ReminderJob(appointment_id=appointment.id, sender_id=body.patient_phone.lstrip("+"),
                           due_at=due_at, status="pending", attempts=0))
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = db.scalar(select(Appointment).where(Appointment.idempotency_key == body.idempotency_key))
        if replay:
            return validate_booking_replay(replay, body)
        raise DomainError("APPOINTMENT_CONFLICT", "The appointment could not be confirmed.", 409) from exc
    db.refresh(appointment)
    return appointment


def cancel_appointment(db: Session, appointment: Appointment, actor_id: str, reason: str) -> Appointment:
    # Re-read under the row lock staff status changes use, so a concurrent check-in is never overwritten.
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment.id)
                            .with_for_update(of=Appointment).execution_options(populate_existing=True))
    if appointment.status == "cancelled":
        return appointment
    if appointment.status not in {"confirmed"}:
        raise DomainError("INVALID_STATUS_TRANSITION", "This appointment cannot be cancelled.", 409)
    previous = appointment.status
    appointment.status = "cancelled"
    appointment.reservation.status = "released"
    db.add(AppointmentStatusHistory(appointment_id=appointment.id, from_status=previous, to_status="cancelled",
                                    actor_type="patient", actor_id=actor_id, reason=reason))
    db.add(OutboxEvent(event_type="appointment.cancelled", aggregate_id=appointment.id,
                       payload={"appointment_id": appointment.id, "confirmation_code": appointment.confirmation_code}))
    reminder = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == appointment.id))
    if reminder and reminder.status != "sent":
        reminder.status = "cancelled"
    db.commit()
    db.refresh(appointment)
    return appointment
