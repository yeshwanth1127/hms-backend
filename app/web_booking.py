"""Cookie-owned website booking verified by a trusted WhatsApp sender message."""
import hashlib
import hmac
import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, func, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .client_modules import ensure_module
from .models import (Appointment, BookingGate, Branch, Doctor, ReminderJob, Reservation,
                     WaitlistEntry, WebBookingSession, utcnow)
from .schemas import AppointmentCreate, AppointmentOut, HoldCreate, HoldOut
from .services import DomainError, _db_utc, _aware_utc, confirm_appointment, create_hold, cancel_appointment
from .booking_operations import move_appointment
from .whatsapp import require_whatsapp_service

router = APIRouter(prefix='/api/v1/web/booking', tags=['web-booking'])
verification_router = APIRouter(prefix='/api/v1/integrations/whatsapp', tags=['web-verification'])
COOKIE = 'hms_booking_session'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def enabled(db):
    if not settings.web_booking_enabled or settings.demo_mode:
        raise DomainError('WEB_BOOKING_DISABLED', 'Online booking is not available. Contact reception.', 503)
    if not re.fullmatch(r'[1-9][0-9]{6,14}', settings.whatsapp_booking_number):
        raise DomainError('WEB_BOOKING_NOT_CONFIGURED', 'The clinic verification number is not configured.', 503)
    ensure_module(db, 'whatsapp')


def origin(request):
    if not settings.web_booking_origin or (settings.app_env == 'production' and not settings.web_booking_origin.startswith('https://')):
        raise DomainError('WEB_BOOKING_NOT_CONFIGURED', 'The clinic booking origin is not configured.', 503)
    if request.headers.get('origin') != settings.web_booking_origin:
        raise DomainError('BOOKING_ORIGIN_DENIED', 'Open booking on the clinic website.', 403)


def session_for(request, db, verified=True):
    enabled(db)
    token = request.cookies.get(COOKIE, '')
    session = db.get(WebBookingSession, digest(token)) if token else None
    if not session or session.status == 'revoked' or _db_utc(session.expires_at) <= utcnow():
        raise DomainError('BOOKING_SESSION_EXPIRED', 'Verify your WhatsApp number again.', 401)
    if verified and session.status != 'verified':
        raise DomainError('WHATSAPP_VERIFICATION_REQUIRED', 'Send the verification message from your WhatsApp number.', 401)
    if request.method not in {'GET', 'HEAD'}:
        origin(request)
        if not secrets.compare_digest(request.headers.get('X-Booking-CSRF', ''), digest('csrf:' + token)):
            raise DomainError('BOOKING_CSRF_REQUIRED', 'Refresh booking and try again.', 403)
    return session


def owner(session):
    return 'web:' + session.token_hash


def key(session, supplied):
    return 'web:' + digest(session.token_hash + ':' + supplied)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Start(StrictBody):
    phone: str = Field(pattern=r'^\+?[1-9][0-9]{6,14}$')
    privacy_accepted: bool


@router.get('/config')
def config(db: Session=Depends(get_db)):
    enabled(db)
    return {'verification': 'whatsapp_sender', 'verification_minutes': 5,
            'session_minutes': 30, 'reception_phone': settings.clinic_phone,
            'environment': settings.app_env, 'is_demo': settings.app_env != 'production'}


@router.post('/session', status_code=201)
def start(body: Start, request: Request, response: Response, db: Session=Depends(get_db)):
    enabled(db)
    origin(request)
    if not body.privacy_accepted:
        raise DomainError('PRIVACY_ACCEPTANCE_REQUIRED', 'Accept the booking privacy notice to continue.', 422)
    phone, now = body.phone.lstrip('+'), utcnow()
    ip = hmac.new(settings.whatsapp_owner_secret.encode(), (request.client.host if request.client else 'unknown').encode(), hashlib.sha256).hexdigest()
    # Seeded by migration; bootstrap is only for the development create_all path.
    gate = db.get(BookingGate, 'web-verification')
    if not gate:
        try:
            with db.begin_nested():
                db.add(BookingGate(key='web-verification'))
                db.flush()
        except IntegrityError:
            pass
    db.execute(update(BookingGate).where(BookingGate.key == 'web-verification').values(touched_at=now))
    # Keep challenge phone/IP evidence bounded; active sessions and the hourly limiter are retained.
    db.execute(delete(WebBookingSession).where(WebBookingSession.expires_at < now-timedelta(days=1)))
    attempts = db.scalar(select(func.count()).select_from(WebBookingSession).where(
        WebBookingSession.created_at >= now-timedelta(hours=1),
        or_(WebBookingSession.phone == phone, WebBookingSession.ip_hash == ip))) or 0
    if attempts >= 5:
        raise DomainError('VERIFICATION_RATE_LIMIT', 'Too many verification requests. Try later or contact reception.', 429)
    old = db.get(WebBookingSession, digest(request.cookies.get(COOKIE, '')))
    if old:
        old.status = 'revoked'
        db.execute(update(Reservation).where(Reservation.owner_key == owner(old), Reservation.status == 'active').values(status='released'))
    token, code = secrets.token_urlsafe(32), secrets.token_hex(10).upper()
    db.add(WebBookingSession(token_hash=digest(token), code_hash=digest(code), phone=phone, ip_hash=ip,
        status='pending', expires_at=now+timedelta(minutes=5)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.app_env == 'production',
                        samesite='strict', max_age=35*60, path='/api/v1/web/booking')
    return {'status': 'pending', 'csrf_token': digest('csrf:' + token),
        'verification_url': 'https://wa.me/' + settings.whatsapp_booking_number + '?' + urlencode({'text': 'VERIFY WEB ' + code}),
        'expires_in_seconds': 300}


class Verify(StrictBody):
    sender_id: str = Field(pattern=r'^[1-9][0-9]{6,14}$')
    code: str = Field(pattern=r'^[A-F0-9]{20}$')


@verification_router.post('/web-booking/verify')
def verify(body: Verify, _=Depends(require_whatsapp_service), db: Session=Depends(get_db)):
    enabled(db)
    item = db.scalar(select(WebBookingSession).where(WebBookingSession.code_hash == digest(body.code)).with_for_update())
    if not item or item.phone != body.sender_id or item.status not in {'pending', 'verified'} or _db_utc(item.expires_at) <= utcnow():
        raise DomainError('VERIFICATION_NOT_FOUND', 'This verification request is invalid or expired. Return to the clinic website.', 404)
    if item.status == 'pending':
        item.status, item.expires_at = 'verified', utcnow()+timedelta(minutes=30)
        db.commit()
    return {'verified': True, 'message': 'Your number is verified. Return to the clinic website to continue booking. This does not grant marketing consent.'}


@router.get('/session')
def session_status(request: Request, db: Session=Depends(get_db)):
    item = session_for(request, db, verified=False)
    return {'status': item.status, 'expires_at': item.expires_at, 'phone_suffix': item.phone[-4:],
            'csrf_token': digest('csrf:' + request.cookies[COOKIE])}


@router.delete('/session', status_code=204)
def end_session(request: Request, response: Response, db: Session=Depends(get_db)):
    item = session_for(request, db, verified=False)
    item.status = 'revoked'
    db.execute(update(Reservation).where(Reservation.owner_key == owner(item), Reservation.status == 'active').values(status='released'))
    db.commit()
    response.delete_cookie(COOKIE, path='/api/v1/web/booking')


class WebHold(StrictBody):
    doctor_id: str
    branch_id: str
    consultation_type: str = Field(pattern=r'^(in_person|virtual)$')
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=80)


@router.post('/holds', response_model=HoldOut, status_code=201)
def hold(body: WebHold, request: Request, db: Session=Depends(get_db)):
    item = session_for(request, db)
    return create_hold(db, HoldCreate(**body.model_dump(exclude={'idempotency_key'}),
                       owner_key=owner(item), idempotency_key=key(item, body.idempotency_key)))


@router.delete('/holds/{hold_id}', status_code=204)
def release(hold_id: str, request: Request, db: Session=Depends(get_db)):
    item = session_for(request, db)
    hold = db.get(Reservation, hold_id)
    if hold and hold.owner_key == owner(item) and hold.status == 'active':
        hold.status = 'released'
        db.commit()


class Confirm(StrictBody):
    hold_id: str
    patient_name: str = Field(min_length=2, max_length=160)
    expected_fee: int = Field(ge=0)
    consent_to_reminders: bool = False
    acquisition_source: str = Field(default='direct', pattern=r'^(unknown|direct|google_business|organic_search|paid|referral)$')
    idempotency_key: str = Field(min_length=8, max_length=80)


def receipt(db, item):
    doctor, branch = db.get(Doctor, item.reservation.doctor_id), db.get(Branch, item.reservation.branch_id)
    row = AppointmentOut.model_validate(item).model_dump()
    reminder = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == item.id).order_by(ReminderJob.created_at.desc()))
    delivery = ('queued' if reminder.status == 'pending' else reminder.status) if reminder else 'not_requested'
    return {**row, 'doctor_name': doctor.name, 'branch_name': branch.name, 'timezone': branch.timezone,
        'address': branch.address, 'directions_url': branch.directions_url, 'arrival_instructions': branch.arrival_instructions,
        'is_demo': item.is_demo, 'delivery_state': delivery}


@router.post('/appointments', status_code=201)
def confirm(body: Confirm, request: Request, db: Session=Depends(get_db)):
    session = session_for(request, db)
    if not body.patient_name.strip():
        raise DomainError('INVALID_NAME', 'Enter the patient name.', 422)
    hold = db.get(Reservation, body.hold_id)
    if not hold or hold.owner_key != owner(session):
        raise DomainError('HOLD_NOT_FOUND', 'Your slot hold was not found.', 404)
    existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == key(session, body.idempotency_key)))
    if existing and (existing.consent_to_reminders != body.consent_to_reminders or existing.acquisition_source != body.acquisition_source):
        raise DomainError('IDEMPOTENCY_CONFLICT', 'This operation key was already used.', 409)
    doctor = db.scalar(select(Doctor).where(Doctor.id == hold.doctor_id).with_for_update())
    if not existing and doctor.consultation_fee != body.expected_fee:
        raise DomainError('PRICE_CHANGED', 'The consultation fee changed. Review the current fee before confirming.', 409)
    appointment = confirm_appointment(db, AppointmentCreate(hold_id=hold.id, owner_key=owner(session),
        patient_phone='+' + session.phone, patient_name=body.patient_name, origin_channel='web',
        consent_to_reminders=body.consent_to_reminders, acquisition_source=body.acquisition_source,
        idempotency_key=key(session, body.idempotency_key)), commit=False)
    if body.consent_to_reminders and not existing:
        from .whatsapp_outreach import change_preferences, PreferenceChange
        change_preferences(db, session.phone, PreferenceChange(source_message_id='web-consent:' + digest(appointment.id), service_messages=True, stopped_all=False))
        db.add(ReminderJob(appointment_id=appointment.id, sender_id=session.phone,
            due_at=max(utcnow(), _db_utc(hold.starts_at)-timedelta(days=1)), status='pending', attempts=0))
    db.commit()
    return receipt(db, appointment)


def owned(request, db, appointment_id):
    session = session_for(request, db)
    item = db.get(Appointment, appointment_id)
    if not item or item.origin_channel != 'web' or item.patient_phone != '+' + session.phone:
        raise DomainError('APPOINTMENT_NOT_FOUND', 'Appointment was not found.', 404)
    return session, item


@router.get('/appointments')
def visits(request: Request, db: Session=Depends(get_db)):
    session = session_for(request, db)
    return [receipt(db, a) for a in db.scalars(select(Appointment).where(Appointment.origin_channel == 'web',
        Appointment.patient_phone == '+' + session.phone).order_by(Appointment.created_at.desc()).limit(50))]


class Cancel(StrictBody):
    reason: str = Field(min_length=2, max_length=240)


@router.post('/appointments/{appointment_id}/cancel')
def cancel(appointment_id: str, body: Cancel, request: Request, db: Session=Depends(get_db)):
    session, item = owned(request, db, appointment_id)
    if item.status != 'cancelled' and _db_utc(item.reservation.starts_at) <= utcnow():
        raise DomainError('VISIT_ALREADY_STARTED', 'Contact reception to change a past visit.', 409)
    return receipt(db, cancel_appointment(db, item, owner(session), body.reason))


class Move(StrictBody):
    new_hold_id: str
    idempotency_key: str = Field(min_length=8, max_length=80)


@router.post('/appointments/{appointment_id}/reschedule')
def move(appointment_id: str, body: Move, request: Request, db: Session=Depends(get_db)):
    session, item = owned(request, db, appointment_id)
    hold = db.get(Reservation, body.new_hold_id)
    if not hold or hold.owner_key != owner(session):
        raise DomainError('HOLD_NOT_FOUND', 'Your replacement hold was not found.', 404)
    from .models import RescheduleOperation
    replay = db.scalar(select(RescheduleOperation).where(RescheduleOperation.idempotency_key == key(session, body.idempotency_key)))
    previous_owner = replay.owner_key if replay else item.reservation.owner_key
    return receipt(db, move_appointment(db, item.id, hold.id, previous_owner, key(session, body.idempotency_key), owner(session),
        'Patient rescheduled on website', actor_type='patient', replacement_owner=owner(session)))


class JoinWaitlist(StrictBody):
    doctor_id: str
    branch_id: str
    consultation_type: str = Field(pattern=r'^(in_person|virtual)$')
    patient_name: str = Field(min_length=2, max_length=160)
    start_date: date
    end_date: date
    consent_to_waitlist: bool


def waitlist_row(item):
    return {name: getattr(item, name) for name in ('id', 'doctor_id', 'branch_id', 'consultation_type', 'start_date', 'end_date', 'status', 'hold_id', 'appointment_id')}


@router.post('/waitlist', status_code=201)
def join_waitlist(body: JoinWaitlist, request: Request, db: Session=Depends(get_db)):
    session = session_for(request, db)
    if not body.consent_to_waitlist or not body.patient_name.strip():
        raise DomainError('WAITLIST_CONSENT_REQUIRED', 'Agree to this waitlist request and enter the patient name.', 422)
    if body.end_date < body.start_date or (body.end_date-body.start_date).days > 31 or body.end_date < utcnow().date():
        raise DomainError('INVALID_DATE_RANGE', 'Choose a future range of at most 31 days.', 422)
    from .services import availability
    availability(db, body.doctor_id, body.branch_id, body.start_date, body.end_date, body.consultation_type)
    # Same lock as offers/slot allocation, avoiding duplicate active requests per patient preference.
    db.scalar(select(Doctor).where(Doctor.id == body.doctor_id).with_for_update())
    item = db.scalar(select(WaitlistEntry).where(WaitlistEntry.phone == session.phone,
        WaitlistEntry.doctor_id == body.doctor_id, WaitlistEntry.branch_id == body.branch_id,
        WaitlistEntry.consultation_type == body.consultation_type, WaitlistEntry.status.in_(['waiting', 'offered'])))
    if item:
        if item.start_date != body.start_date or item.end_date != body.end_date or item.patient_name != body.patient_name.strip():
            raise DomainError('WAITLIST_ALREADY_ACTIVE', 'Withdraw the existing request before changing your preference.', 409)
        return waitlist_row(item)
    item = WaitlistEntry(**body.model_dump(exclude={'consent_to_waitlist'}), phone=session.phone)
    item.patient_name = item.patient_name.strip()
    db.add(item)
    db.commit()
    return waitlist_row(item)


def expire_offers(db, items):
    for stale in items:
        item = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == stale.id).with_for_update().execution_options(populate_existing=True))
        if item.status == 'offered':
            hold = db.get(Reservation, item.hold_id)
            if not hold or hold.status != 'active' or not hold.expires_at or _db_utc(hold.expires_at) <= utcnow():
                item.status = 'waiting'
                item.hold_id = None
        if item.status == 'waiting' and item.end_date < utcnow().date():
            item.status = 'expired'
    db.commit()


@router.get('/waitlist')
def patient_waitlist(request: Request, db: Session=Depends(get_db)):
    session = session_for(request, db)
    items = db.scalars(select(WaitlistEntry).where(WaitlistEntry.phone == session.phone).order_by(WaitlistEntry.created_at.desc()).limit(50)).all()
    expire_offers(db, items)
    rows=[]
    for item in items:
        row = waitlist_row(item)
        if item.status == 'offered':
            row['offer'] = HoldOut.model_validate(db.get(Reservation, item.hold_id)).model_dump()
        rows.append(row)
    return rows


@router.delete('/waitlist/{entry_id}', status_code=204)
def withdraw(entry_id: str, request: Request, db: Session=Depends(get_db)):
    session = session_for(request, db)
    item = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == entry_id).with_for_update())
    if not item or item.phone != session.phone:
        raise DomainError('WAITLIST_NOT_FOUND', 'Waitlist request was not found.', 404)
    if item.status == 'booked':
        raise DomainError('WAITLIST_ALREADY_BOOKED', 'Manage the confirmed appointment instead.', 409)
    if item.hold_id:
        hold = db.get(Reservation, item.hold_id)
        if hold and hold.status == 'active':
            hold.status = 'released'
    item.status = 'withdrawn'
    db.commit()


class AcceptOffer(StrictBody):
    expected_fee: int = Field(ge=0)
    consent_to_reminders: bool = False
    idempotency_key: str = Field(min_length=8, max_length=80)


@router.post('/waitlist/{entry_id}/accept')
def accept_offer(entry_id: str, body: AcceptOffer, request: Request, db: Session=Depends(get_db)):
    session = session_for(request, db)
    item = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == entry_id).with_for_update())
    if not item or item.phone != session.phone:
        raise DomainError('WAITLIST_NOT_FOUND', 'Waitlist request was not found.', 404)
    if item.status == 'booked':
        return receipt(db, db.get(Appointment, item.appointment_id))
    if item.status != 'offered':
        raise DomainError('WAITLIST_OFFER_UNAVAILABLE', 'There is no current offer. Contact reception.', 409)
    hold = db.get(Reservation, item.hold_id)
    if not hold or hold.status != 'active' or not hold.expires_at or _db_utc(hold.expires_at) <= utcnow():
        raise DomainError('WAITLIST_OFFER_EXPIRED', 'This offer expired. Your request can receive another offer.', 409)
    # Offer ownership is a verified phone, rather than the browser used when joining.
    hold.owner_key = owner(session)
    # Confirm and waitlist transition share one database transaction.
    appointment = confirm_appointment(db, AppointmentCreate(hold_id=hold.id, owner_key=owner(session),
        patient_name=item.patient_name, patient_phone='+'+session.phone, origin_channel='web',
        idempotency_key=key(session, body.idempotency_key), consent_to_reminders=body.consent_to_reminders), commit=False)
    if appointment.consultation_fee != body.expected_fee:
        db.rollback()
        raise DomainError('PRICE_CHANGED', 'Review the current consultation fee before accepting.', 409)
    if body.consent_to_reminders:
        from .whatsapp_outreach import change_preferences, PreferenceChange
        change_preferences(db, session.phone, PreferenceChange(source_message_id='web-consent:'+digest(appointment.id), service_messages=True, stopped_all=False))
        db.add(ReminderJob(appointment_id=appointment.id, sender_id=session.phone,
            due_at=max(utcnow(), _db_utc(hold.starts_at)-timedelta(days=1)), status='pending', attempts=0))
    item.status, item.appointment_id = 'booked', appointment.id
    db.commit()
    return receipt(db, appointment)
