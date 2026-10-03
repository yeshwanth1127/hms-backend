"""Staff schedule disruption controls and shared atomic rescheduling."""
from datetime import datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from . import audit
from .admin import require_admin, _appointment_row
from .permissions import require_capability
from .db import get_db
from .models import (Appointment, AppointmentStatusHistory, BookingOperationAudit, Doctor,
                     Branch, OutboxEvent, ReminderJob, Reservation, RescheduleOperation, ScheduleException, utcnow)
from .schemas import HoldCreate
from .services import DomainError, _aware_utc, _db_utc, create_hold, validate_held_slot

router = APIRouter(prefix='/api/v1/admin', tags=['booking-operations'])


class ExceptionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doctor_id: str
    branch_id: str | None = None
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=2, max_length=240)
    acknowledged_appointments: list[str] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def valid(self):
        self.starts_at, self.ends_at = _aware_utc(self.starts_at), _aware_utc(self.ends_at)
        if self.ends_at <= self.starts_at or self.ends_at-self.starts_at > timedelta(days=366):
            raise ValueError('Choose an ordered block of at most 366 days.')
        if not self.reason.strip():
            raise ValueError('Enter a reason.')
        return self


def exception_scope(body):
    filters = [Reservation.doctor_id == body.doctor_id, Reservation.starts_at < body.ends_at,
               Reservation.ends_at > body.starts_at]
    if body.branch_id:
        filters.append(Reservation.branch_id == body.branch_id)
    return filters


def affected(db, body):
    if not db.get(Doctor, body.doctor_id) or (body.branch_id and not db.get(Branch, body.branch_id)):
        raise DomainError('CATALOGUE_ITEM_NOT_FOUND', 'Doctor or clinic was not found.', 404)
    return db.scalars(select(Appointment).join(Reservation).where(*exception_scope(body),
        Appointment.status.in_(['confirmed', 'checked_in']))).all()


def exception_row(item):
    return {**{key: getattr(item, key) for key in ('id', 'doctor_id', 'branch_id', 'reason')},
            'starts_at': _db_utc(item.starts_at), 'ends_at': _db_utc(item.ends_at)}


@router.get('/schedule-exceptions')
def exceptions(_=Depends(require_admin), db: Session=Depends(get_db)):
    return [exception_row(item) for item in db.scalars(select(ScheduleException).order_by(ScheduleException.starts_at.desc()).limit(500))]


@router.post('/schedule-exceptions/preview')
def exception_preview(body: ExceptionInput, _=Depends(require_admin), db: Session=Depends(get_db)):
    return {'affected_appointments': [_appointment_row(db, item) for item in affected(db, body)],
            'notification_state': 'staff_review_required'}


@router.post('/schedule-exceptions', status_code=201)
def exception_create(body: ExceptionInput, actor=Depends(require_capability('schedule.block')), db: Session=Depends(get_db)):
    db.scalar(select(Doctor).where(Doctor.id == body.doctor_id).with_for_update())
    items = affected(db, body)
    if set(body.acknowledged_appointments) != {item.id for item in items}:
        raise DomainError('AFFECTED_BOOKINGS_CHANGED', 'Review the affected bookings and acknowledge each one before blocking time.', 409)
    item = ScheduleException(**body.model_dump(exclude={'acknowledged_appointments'}))
    db.add(item)
    db.flush()
    # Unconfirmed holds cannot keep a now-blocked time bookable.
    holds = db.scalars(select(Reservation).where(*exception_scope(body), Reservation.status == 'active')).all()
    for hold in holds:
        hold.status = 'released'
    audit.note(targets={'exception_id': item.id, 'doctor_id': body.doctor_id},
               blocked={'starts_at': body.starts_at, 'ends_at': body.ends_at}, affected_appointments=[a.id for a in items], released_holds=len(holds))
    db.add(BookingOperationAudit(actor=actor, action='schedule.blocked', record_id=item.id,
        change={'reason': body.reason, 'affected_appointments': [a.id for a in items], 'released_holds': len(holds)}))
    db.commit()
    return {**exception_row(item), 'affected_appointments': [a.id for a in items], 'notification_state': 'staff_review_required'}


@router.delete('/schedule-exceptions/{exception_id}', status_code=204)
def exception_delete(exception_id: str, actor=Depends(require_capability('schedule.block')), db: Session=Depends(get_db)):
    item = db.get(ScheduleException, exception_id)
    if not item:
        raise DomainError('SCHEDULE_EXCEPTION_NOT_FOUND', 'Blocked time was not found.', 404)
    db.scalar(select(Doctor).where(Doctor.id == item.doctor_id).with_for_update())
    audit.note(targets={'doctor_id': item.doctor_id}, unblocked={'starts_at': item.starts_at, 'ends_at': item.ends_at})
    db.add(BookingOperationAudit(actor=actor, action='schedule.unblocked', record_id=item.id, change={'reason': item.reason}))
    db.delete(item)
    db.commit()


def move_appointment(db, appointment_id, hold_id, owner, idempotency_key, actor, reason, *, actor_type='staff', replacement_owner=None):
    operation = db.scalar(select(RescheduleOperation).where(RescheduleOperation.idempotency_key == idempotency_key))
    if operation:
        if operation.owner_key != owner or operation.appointment_id != appointment_id or operation.new_reservation_id != hold_id:
            raise DomainError('IDEMPOTENCY_CONFLICT', 'This operation key was already used.', 409)
        return db.get(Appointment, appointment_id)
    hold = db.get(Reservation, hold_id)
    if not hold or hold.owner_key != (replacement_owner or owner):
        raise DomainError('HOLD_NOT_FOUND', 'Replacement hold was not found.', 404)
    db.scalar(select(Doctor).where(Doctor.id == hold.doctor_id).with_for_update())
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update(of=Appointment))
    hold = db.scalar(select(Reservation).where(Reservation.id == hold_id).with_for_update())
    if not item or item.reservation.owner_key != owner:
        raise DomainError('APPOINTMENT_NOT_FOUND', 'Appointment was not found.', 404)
    if (item.status != 'confirmed' or _db_utc(item.reservation.starts_at) <= utcnow()
            or hold.status != 'active' or not hold.expires_at or _db_utc(hold.expires_at) <= utcnow()):
        raise DomainError('RESCHEDULE_UNAVAILABLE', 'The visit or replacement time is no longer available.', 409)
    if (hold.doctor_id, hold.branch_id, hold.consultation_type) != (item.reservation.doctor_id, item.reservation.branch_id, item.reservation.consultation_type):
        raise DomainError('VISIT_CHANGE_REQUIRES_REBOOKING', 'Keep the same doctor, clinic and visit type, or cancel and book a new visit after reviewing its fee.', 422)
    validate_held_slot(db, hold)
    audit.note(targets={'code': item.confirmation_code}, starts_at={'from': item.reservation.starts_at, 'to': hold.starts_at})
    item.reservation.status = 'released'
    hold.status, hold.expires_at = 'booked', None
    item.reservation_id, item.reservation = hold.id, hold
    db.add(RescheduleOperation(idempotency_key=idempotency_key, owner_key=owner, appointment_id=item.id, new_reservation_id=hold.id))
    db.add(AppointmentStatusHistory(appointment_id=item.id, from_status='confirmed', to_status='confirmed', actor_type=actor_type, actor_id=actor, reason=reason))
    db.add(OutboxEvent(event_type='appointment.rescheduled', aggregate_id=item.id, payload={'appointment_id': item.id, 'confirmation_code': item.confirmation_code}))
    reminder = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == item.id))
    # Never resurrect a claimed or uncertain delivery while its transport may be running.
    if reminder and reminder.status in {'pending', 'failed'}:
        reminder.due_at, reminder.status = max(utcnow(), _db_utc(hold.starts_at)-timedelta(days=1)), 'pending'
        reminder.claimed_at = None
    db.add(BookingOperationAudit(actor=actor, action='appointment.rescheduled', record_id=item.id, change={'new_reservation_id': hold.id, 'reason': reason}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError('RESCHEDULE_CONFLICT', 'The visit could not be moved. Refresh its current state.', 409) from exc
    return item


class StaffMove(BaseModel):
    model_config = ConfigDict(extra='forbid')
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=80)
    reason: str = Field(min_length=2, max_length=240)


@router.post('/appointments/{appointment_id}/reschedule')
def staff_move(appointment_id: str, body: StaffMove, actor=Depends(require_admin), db: Session=Depends(get_db)):
    item = db.get(Appointment, appointment_id)
    if not item:
        raise DomainError('APPOINTMENT_NOT_FOUND', 'Appointment was not found.', 404)
    operation_key = 'staff-move:' + body.idempotency_key
    operation = db.scalar(select(RescheduleOperation).where(RescheduleOperation.idempotency_key == operation_key))
    if operation:
        if operation.appointment_id != item.id:
            raise DomainError('IDEMPOTENCY_CONFLICT', 'This operation key was already used.', 409)
        hold = db.get(Reservation, operation.new_reservation_id)
        if _db_utc(hold.starts_at) != _aware_utc(body.starts_at) or _db_utc(hold.ends_at) != _aware_utc(body.ends_at):
            raise DomainError('IDEMPOTENCY_CONFLICT', 'This operation key was already used.', 409)
        return _appointment_row(db, item)
    old = item.reservation
    hold = create_hold(db, HoldCreate(doctor_id=old.doctor_id, branch_id=old.branch_id, consultation_type=old.consultation_type,
        starts_at=body.starts_at, ends_at=body.ends_at, owner_key=old.owner_key, idempotency_key=operation_key), commit=False)
    moved = move_appointment(db, item.id, hold.id, old.owner_key, operation_key, actor, body.reason)
    from .whatsapp_outreach import notify_change
    notification = notify_change(db, moved, 'rescheduled')
    db.commit()
    return {**_appointment_row(db, moved), **notification}


@router.get('/booking-operations/audit')
def audits(_=Depends(require_admin), db: Session=Depends(get_db)):
    return [{'id': a.id, 'actor': a.actor, 'action': a.action, 'record_id': a.record_id, 'change': a.change, 'created_at': a.created_at}
            for a in db.scalars(select(BookingOperationAudit).order_by(BookingOperationAudit.created_at.desc()).limit(100))]


@router.get('/waitlist')
def staff_waitlist(_=Depends(require_admin), db: Session=Depends(get_db)):
    from .models import WaitlistEntry
    from .web_booking import expire_offers, waitlist_row
    items = db.scalars(select(WaitlistEntry).order_by(WaitlistEntry.created_at.desc()).limit(200)).all()
    expire_offers(db, items)
    return [{**waitlist_row(item), 'patient_name': item.patient_name, 'phone': item.phone, 'consent_at': item.consent_at} for item in items]


class OfferInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=80)


@router.post('/waitlist/{entry_id}/offer')
def offer(entry_id: str, body: OfferInput, actor=Depends(require_admin), db: Session=Depends(get_db)):
    from .models import WaitlistEntry, WhatsAppContact
    from .web_booking import waitlist_row
    item = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == entry_id).with_for_update())
    if not item or item.status not in {'waiting', 'offered'}:
        raise DomainError('WAITLIST_NOT_WAITING', 'This request is not waiting for a time.', 409)
    contact = db.get(WhatsAppContact, item.phone)
    if contact and contact.stopped_all:
        raise DomainError('CONTACT_STOPPED', 'This patient has stopped proactive contact. Do not send an offer.', 409)
    branch = db.get(Branch, item.branch_id)
    from zoneinfo import ZoneInfo
    day = _aware_utc(body.starts_at).astimezone(ZoneInfo(branch.timezone)).date()
    if not item.start_date <= day <= item.end_date:
        raise DomainError('OUTSIDE_WAITLIST_PREFERENCE', 'Choose a time in the patient\'s requested date range.', 422)
    operation_key = 'waitlist:' + body.idempotency_key
    if item.status == 'offered':
        current = db.get(Reservation, item.hold_id)
        if current and current.status == 'active' and current.expires_at and _db_utc(current.expires_at) > utcnow():
            if current.idempotency_key != operation_key or _db_utc(current.starts_at) != _aware_utc(body.starts_at) or _db_utc(current.ends_at) != _aware_utc(body.ends_at):
                raise DomainError('WAITLIST_OFFER_ACTIVE', 'Withdraw or wait for the current offer to expire before replacing it.', 409)
            return {**waitlist_row(item), 'expires_at': current.expires_at, 'notification_state': 'staff_review_required'}
    hold = create_hold(db, HoldCreate(doctor_id=item.doctor_id, branch_id=item.branch_id,
        consultation_type=item.consultation_type, starts_at=body.starts_at, ends_at=body.ends_at,
        owner_key='waitlist:' + item.id, idempotency_key=operation_key), commit=False)
    if hold.status != 'active' or not hold.expires_at or _db_utc(hold.expires_at) <= utcnow():
        raise DomainError('WAITLIST_OFFER_EXPIRED', 'Use a new operation key to prepare another offer.', 409)
    item.status, item.hold_id = 'offered', hold.id
    db.add(BookingOperationAudit(actor=actor, action='waitlist.offered', record_id=item.id,
        change={'hold_id': hold.id, 'notification_state': 'staff_review_required'}))
    db.commit()
    return {**waitlist_row(item), 'expires_at': hold.expires_at, 'notification_state': 'staff_review_required'}
