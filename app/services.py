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
    ).values(status="expired"))
    db.commit()


def availability(db: Session, doctor_id: str, branch_id: str, start_date: date, end_date: date,
                 consultation_type: str = "in_person") -> tuple[list[AvailabilitySlot], str]:
    if end_date < start_date or (end_date - start_date).days > 31:
        raise DomainError("INVALID_DATE_RANGE", "Choose a date range of 31 days or less.", 422)
    doctor = db.get(Doctor, doctor_id)
    branch = db.get(Branch, branch_id)
    if not doctor or not doctor.is_active or not branch or not branch.is_active:
        raise DomainError("CATALOGUE_ITEM_NOT_FOUND", "Doctor or branch was not found.", 404)
    if doctor.hospital_id and branch.hospital_id and doctor.hospital_id != branch.hospital_id:
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
    busy = db.scalars(select(Reservation).where(
        Reservation.doctor_id == doctor_id, Reservation.status.in_(["active", "booked"]),
        Reservation.starts_at < range_end, Reservation.ends_at > range_start,
    )).all()
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
    db.commit()
    return sorted(slots, key=lambda item: item.starts_at), branch.timezone


def create_hold(db: Session, body: HoldCreate) -> Reservation:
    existing = db.scalar(select(Reservation).where(Reservation.idempotency_key == body.idempotency_key))
    if existing:
        return existing
    starts_at, ends_at = _aware_utc(body.starts_at), _aware_utc(body.ends_at)
    if starts_at <= utcnow() or ends_at <= starts_at:
        raise DomainError("INVALID_SLOT", "The selected slot must be in the future.", 422)
    candidates, _ = availability(db, body.doctor_id, body.branch_id, starts_at.date(), ends_at.date(), body.consultation_type)
    if not any(item.starts_at == starts_at and item.ends_at == ends_at for item in candidates):
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "That appointment time is no longer available.", 409)
    doctor = db.get(Doctor, body.doctor_id)
    hold = Reservation(hospital_id=doctor.hospital_id if doctor else None,
                       doctor_id=body.doctor_id, branch_id=body.branch_id,
                       consultation_type=body.consultation_type, starts_at=starts_at, ends_at=ends_at,
                       owner_key=body.owner_key, expires_at=utcnow() + timedelta(minutes=settings.slot_hold_minutes),
                       idempotency_key=body.idempotency_key, status="active")
    db.add(hold)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = db.scalar(select(Reservation).where(Reservation.idempotency_key == body.idempotency_key))
        if replay:
            return replay
        raise DomainError("SLOT_NO_LONGER_AVAILABLE", "That appointment time is no longer available.", 409) from exc
    db.refresh(hold)
    return hold


def confirm_appointment(db: Session, body: AppointmentCreate) -> Appointment:
    existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == body.idempotency_key))
    if existing:
        from .models import Patient
        replay_patient = db.get(Patient, existing.patient_id) if existing.patient_id else None
        existing.patient_code = replay_patient.patient_code if replay_patient else None
        existing.patient_access_code = None
        existing.patient_account_created = False
        return existing
    hold = db.scalar(select(Reservation).where(Reservation.id == body.hold_id).with_for_update())
    if not hold or hold.owner_key != body.owner_key:
        raise DomainError("HOLD_NOT_FOUND", "The slot hold was not found.", 404)
    now = utcnow()
    expires_at = hold.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if hold.status != "active" or not expires_at or expires_at <= now:
        if hold.status == "active":
            hold.status = "expired"
            db.commit()
        raise DomainError("HOLD_EXPIRED", "The slot hold has expired. Please select a new time.", 409)
    from .auth import hash_password
    from .models import Hospital, HospitalMembership, Patient, User
    hospital = db.get(Hospital, hold.hospital_id) if hold.hospital_id else None
    patient = None
    access_code = None
    account_created = False
    if hospital:
        if body.patient_email:
            patient = db.scalar(select(Patient).where(Patient.hospital_id == hospital.id,
                                                       Patient.email == str(body.patient_email).lower()))
        if not patient:
            patient = db.scalar(select(Patient).where(Patient.hospital_id == hospital.id,
                                                       Patient.phone == body.patient_phone.strip()))
        if not patient:
            patient = Patient(hospital_id=hospital.id, name=body.patient_name.strip(),
                              phone=body.patient_phone.strip(),
                              email=str(body.patient_email).lower() if body.patient_email else None)
            db.add(patient)
            db.flush()
        if patient.user_id:
            user = db.get(User, patient.user_id)
        else:
            login_email = patient.email or f"{patient.patient_code.lower()}@patient.exora.local"
            user = db.scalar(select(User).where(User.email == login_email))
            if user is None:
                access_code = str(secrets.randbelow(90000000) + 10000000)
                user = User(email=login_email, display_name=patient.name,
                            password_hash=hash_password(access_code))
                db.add(user)
                db.flush()
                patient.access_code_hash = hash_password(access_code)
                account_created = True
            patient.user_id = user.id
        if user:
            membership = db.scalar(select(HospitalMembership).where(
                HospitalMembership.hospital_id == hospital.id,
                HospitalMembership.user_id == user.id,
                HospitalMembership.role == "patient",
            ))
            if membership is None:
                db.add(HospitalMembership(hospital_id=hospital.id, user_id=user.id, role="patient"))
    appointment = Appointment(
        confirmation_code=f"AVO-{secrets.token_hex(4).upper()}", reservation_id=hold.id,
        hospital_id=hospital.id if hospital else None, patient_id=patient.id if patient else None,
        patient_name=body.patient_name.strip(), patient_phone=body.patient_phone.strip(),
        patient_email=str(body.patient_email) if body.patient_email else None,
        reason=body.reason.strip() if body.reason else None, origin_channel=body.origin_channel,
        consent_to_reminders=body.consent_to_reminders,
        idempotency_key=body.idempotency_key, status="confirmed",
    )
    db.add(appointment)
    db.flush()
    if hold.consultation_type == "virtual":
        from .teleconsultation_service import ensure_for_appointment
        ensure_for_appointment(db, appointment)
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
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = db.scalar(select(Appointment).where(Appointment.idempotency_key == body.idempotency_key))
        if replay:
            return replay
        raise DomainError("APPOINTMENT_CONFLICT", "The appointment could not be confirmed.", 409) from exc
    db.refresh(appointment)
    appointment.patient_code = patient.patient_code if patient else None
    appointment.patient_access_code = access_code
    appointment.patient_account_created = account_created
    return appointment


def cancel_appointment(db: Session, appointment: Appointment, actor_id: str, reason: str) -> Appointment:
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
