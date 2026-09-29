"""Authenticated service API for a signature-verifying WhatsApp webhook worker."""

import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .media import asset_row, media_path, save_upload
from .models import (Appointment, AppointmentStatusHistory, Branch, CaseAttachment, Department,
                     Doctor, MediaAsset, OutboxEvent, ReminderJob, Reservation, RescheduleOperation,
                     SupportCase, WhatsAppConversation, utcnow)
from .schemas import (AppointmentCreate, AppointmentOut, AvailabilityResponse, BranchOut,
                      DepartmentOut, DoctorOut, HoldCreate, HoldOut, ReminderComplete,
                      WhatsAppAppointmentCreate, WhatsAppAppointmentOut, WhatsAppCancel, WhatsAppCaseCreate,
                      WhatsAppConversationSave, WhatsAppHoldCreate, WhatsAppReschedule)
from .services import DomainError, availability, cancel_appointment, confirm_appointment, create_hold

router = APIRouter(prefix="/api/v1/integrations/whatsapp", tags=["whatsapp-integration"])


def require_whatsapp_service(x_service_key: str = Header(alias="X-Service-Key")) -> None:
    if not secrets.compare_digest(x_service_key, settings.whatsapp_service_api_key):
        raise DomainError("SERVICE_AUTH_REQUIRED", "A valid WhatsApp service key is required.", 401)


def owner_key(sender_id: str) -> str:
    return "wa:" + hmac.new(settings.whatsapp_owner_secret.encode(), sender_id.encode(), hashlib.sha256).hexdigest()


def _owned_appointment(db: Session, appointment_id: str, sender_id: str) -> Appointment:
    item = db.get(Appointment, appointment_id)
    if not item or item.origin_channel != "whatsapp" or item.reservation.owner_key != owner_key(sender_id):
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    return item


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _appointment_row(db: Session, item: Appointment) -> dict:
    doctor = db.get(Doctor, item.reservation.doctor_id)
    branch = db.get(Branch, item.reservation.branch_id)
    base = AppointmentOut.model_validate(item).model_dump()
    for field in ("starts_at", "ends_at", "expires_at"):
        if base["reservation"].get(field):
            base["reservation"][field] = _utc(base["reservation"][field])
    return {**base, "doctor_name": doctor.name if doctor else "Doctor",
            "branch_name": branch.name if branch else "Clinic",
            "timezone": branch.timezone if branch else "Asia/Kolkata"}


@router.get("/conversations/{sender_id}")
def conversation_get(sender_id: str, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    if not sender_id.isdecimal() or not 7 <= len(sender_id) <= 20:
        raise DomainError("INVALID_SENDER", "Invalid WhatsApp sender.", 422)
    item = db.get(WhatsAppConversation, sender_id)
    if not item:
        return {"state": {"step": "menu", "draft": {}}, "last_message_id": None, "last_reply": None}
    return {"state": item.state, "last_message_id": item.last_message_id, "last_reply": item.last_reply}


@router.put("/conversations/{sender_id}")
def conversation_save(sender_id: str, body: WhatsAppConversationSave,
                      _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    if not sender_id.isdecimal() or not 7 <= len(sender_id) <= 20:
        raise DomainError("INVALID_SENDER", "Invalid WhatsApp sender.", 422)
    item = db.get(WhatsAppConversation, sender_id)
    if not item:
        item = WhatsAppConversation(sender_id=sender_id)
        db.add(item)
    item.state = body.state
    item.last_message_id = body.last_message_id
    item.last_reply = body.last_reply
    item.updated_at = utcnow()
    db.commit()
    return {"saved": True}


@router.get("/catalogue")
def catalogue(_: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    branches = db.scalars(select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)).all()
    departments = db.scalars(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).all()
    return {"branches": [BranchOut.model_validate(item) for item in branches],
            "departments": [DepartmentOut.model_validate(item) for item in departments]}


@router.get("/doctors", response_model=list[DoctorOut])
def doctors(department: str | None = None, branch: str | None = None,
            _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.is_active.is_(True)).order_by(Doctor.name)).unique().all()
    if department:
        items = [item for item in items if any(value.slug == department or value.id == department for value in item.departments)]
    if branch:
        items = [item for item in items if any(value.slug == branch or value.id == branch for value in item.branches)]
    return items


@router.get("/availability", response_model=AvailabilityResponse)
def get_availability(doctor_id: str, branch_id: str, start_date: date, end_date: date,
                     consultation_type: str = Query("in_person", pattern="^(in_person|virtual)$"),
                     _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    slots, timezone_name = availability(db, doctor_id, branch_id, start_date, end_date, consultation_type)
    return AvailabilityResponse(slots=slots, timezone=timezone_name)


@router.post("/slot-holds", response_model=HoldOut, status_code=201)
def hold_create(body: WhatsAppHoldCreate, _: None = Depends(require_whatsapp_service),
                db: Session = Depends(get_db)):
    key = owner_key(body.sender_id)
    existing = db.scalar(select(Reservation).where(Reservation.idempotency_key == body.idempotency_key))
    if existing and (existing.owner_key != key or existing.doctor_id != body.doctor_id
                     or existing.branch_id != body.branch_id or _utc(existing.starts_at) != _utc(body.starts_at)
                     or _utc(existing.ends_at) != _utc(body.ends_at)):
        raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
    hold = create_hold(db, HoldCreate(**body.model_dump(exclude={"sender_id"}), owner_key=key))
    if hold.owner_key != key:
        raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
    row = HoldOut.model_validate(hold).model_dump()
    for field in ("starts_at", "ends_at", "expires_at"):
        if row.get(field):
            row[field] = _utc(row[field])
    return row


@router.delete("/slot-holds/{hold_id}", status_code=204)
def hold_release(hold_id: str, sender_id: str = Query(pattern=r"^[0-9]{7,20}$"),
                 _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    hold = db.get(Reservation, hold_id)
    if hold and hold.owner_key == owner_key(sender_id) and hold.status == "active":
        hold.status = "released"
        db.commit()
    return Response(status_code=204)


@router.post("/appointments", response_model=WhatsAppAppointmentOut, status_code=201)
def appointment_create(body: WhatsAppAppointmentCreate, _: None = Depends(require_whatsapp_service),
                       db: Session = Depends(get_db)):
    key = owner_key(body.sender_id)
    existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == body.idempotency_key))
    if existing and (existing.reservation.owner_key != key or existing.reservation_id != body.hold_id
                     or existing.patient_name != body.patient_name.strip()):
        raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
    appointment = confirm_appointment(db, AppointmentCreate(
        hold_id=body.hold_id, owner_key=key, patient_name=body.patient_name,
        patient_phone=f"+{body.sender_id}", origin_channel="whatsapp",
        consent_to_reminders=body.consent_to_reminders, idempotency_key=body.idempotency_key))
    if appointment.reservation.owner_key != key:
        raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
    return _appointment_row(db, appointment)


@router.get("/appointments", response_model=list[WhatsAppAppointmentOut])
def appointments(sender_id: str = Query(pattern=r"^[0-9]{7,20}$"), limit: int = Query(20, ge=1, le=100),
                 _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    items = db.scalars(select(Appointment).join(Reservation).where(
        Appointment.origin_channel == "whatsapp", Reservation.owner_key == owner_key(sender_id))
        .order_by(Appointment.created_at.desc()).limit(limit)).all()
    return [_appointment_row(db, item) for item in items]


@router.get("/appointments/{appointment_id}", response_model=WhatsAppAppointmentOut)
def appointment_get(appointment_id: str, sender_id: str = Query(pattern=r"^[0-9]{7,20}$"),
                    _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    return _appointment_row(db, _owned_appointment(db, appointment_id, sender_id))


@router.post("/appointments/{appointment_id}/cancel", response_model=WhatsAppAppointmentOut)
def appointment_cancel(appointment_id: str, body: WhatsAppCancel,
                       _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    item = _owned_appointment(db, appointment_id, body.sender_id)
    return _appointment_row(db, cancel_appointment(db, item, owner_key(body.sender_id), body.reason))


@router.post("/appointments/{appointment_id}/reschedule", response_model=WhatsAppAppointmentOut)
def appointment_reschedule(appointment_id: str, body: WhatsAppReschedule,
                           _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    key = owner_key(body.sender_id)
    operation = db.scalar(select(RescheduleOperation).where(
        RescheduleOperation.idempotency_key == body.idempotency_key))
    if operation:
        if operation.owner_key != key or operation.appointment_id != appointment_id or operation.new_reservation_id != body.new_hold_id:
            raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
        return _appointment_row(db, _owned_appointment(db, appointment_id, body.sender_id))
    item = _owned_appointment(db, appointment_id, body.sender_id)
    item = db.scalar(select(Appointment).where(Appointment.id == item.id).with_for_update())
    new_hold = db.scalar(select(Reservation).where(Reservation.id == body.new_hold_id).with_for_update())
    if not new_hold or new_hold.owner_key != key:
        raise DomainError("HOLD_NOT_FOUND", "The replacement slot hold was not found.", 404)
    if item.status != "confirmed" or new_hold.status != "active" or not new_hold.expires_at or _utc(new_hold.expires_at) <= utcnow():
        raise DomainError("RESCHEDULE_UNAVAILABLE", "This appointment or replacement hold is no longer available.", 409)
    if new_hold.id == item.reservation_id:
        raise DomainError("INVALID_SLOT", "Choose a different slot.", 422)
    old_reservation = item.reservation
    old_reservation.status = "released"
    new_hold.status = "booked"
    new_hold.expires_at = None
    item.reservation_id = new_hold.id
    item.reservation = new_hold
    db.add(RescheduleOperation(idempotency_key=body.idempotency_key, owner_key=key,
                               appointment_id=item.id, new_reservation_id=new_hold.id))
    db.add(AppointmentStatusHistory(appointment_id=item.id, from_status="confirmed", to_status="confirmed",
                                    actor_type="whatsapp", actor_id=key, reason="rescheduled"))
    db.add(OutboxEvent(event_type="appointment.rescheduled", aggregate_id=item.id,
                       payload={"appointment_id": item.id, "confirmation_code": item.confirmation_code}))
    reminder = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == item.id))
    if reminder and reminder.status != "sent":
        reminder.due_at = max(utcnow(), _utc(new_hold.starts_at) - timedelta(days=1))
        reminder.status = "pending"
        reminder.claimed_at = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("RESCHEDULE_CONFLICT", "The appointment could not be moved.", 409) from exc
    db.refresh(item)
    return _appointment_row(db, item)


@router.post("/cases", status_code=201)
def case_create(body: WhatsAppCaseCreate, _: None = Depends(require_whatsapp_service),
                db: Session = Depends(get_db)):
    key = owner_key(body.sender_id)
    existing = db.scalar(select(SupportCase).where(SupportCase.idempotency_key == body.idempotency_key))
    if existing:
        if existing.owner_key != key or existing.kind != body.kind or existing.description != body.description or existing.rating != body.rating:
            raise DomainError("IDEMPOTENCY_CONFLICT", "This operation key was already used.", 409)
        return {"id": existing.id, "status": existing.status}
    if body.kind == "issue" and body.rating is not None:
        raise DomainError("INVALID_RATING", "Only feedback can have a rating.", 422)
    item = SupportCase(owner_key=key, sender_id=body.sender_id, kind=body.kind,
                       description=body.description, rating=body.rating,
                       status="open", idempotency_key=body.idempotency_key)
    db.add(item)
    db.commit()
    return {"id": item.id, "status": item.status}


@router.post("/cases/{case_id}/attachments", status_code=201)
async def case_attachment(case_id: str, sender_id: str = Form(pattern=r"^[0-9]{7,20}$"),
                          source_message_id: str = Form(min_length=8, max_length=120),
                          file: UploadFile = File(), _: None = Depends(require_whatsapp_service),
                          db: Session = Depends(get_db)):
    item = db.get(SupportCase, case_id)
    if not item or item.owner_key != owner_key(sender_id):
        raise DomainError("CASE_NOT_FOUND", "The case was not found.", 404)
    existing = db.scalar(select(CaseAttachment).where(CaseAttachment.source_message_id == source_message_id))
    if existing:
        if existing.case_id != case_id:
            raise DomainError("IDEMPOTENCY_CONFLICT", "This message was already attached elsewhere.", 409)
        return {"id": existing.id, "asset_id": existing.asset_id}
    asset = await save_upload(db, file, "attachment")
    db.flush()
    attachment = CaseAttachment(case_id=case_id, asset_id=asset.id, source_message_id=source_message_id)
    db.add(attachment)
    db.commit()
    return {"id": attachment.id, "asset_id": asset.id}


@router.get("/assets/{asset_id}")
def asset_download(asset_id: str, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    if not asset or not (db.scalar(select(Department.id).where(Department.guide_asset_id == asset_id))
                     or db.scalar(select(Doctor.id).where(Doctor.photo_asset_id == asset_id))):
        raise DomainError("ASSET_NOT_FOUND", "The asset was not found.", 404)
    path = media_path(asset.storage_name)
    if not path.is_file():
        raise DomainError("ASSET_MISSING", "The uploaded asset is missing from storage.", 503)
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_name,
                        headers={"Cache-Control": "private, no-store"})


@router.get("/reminders/due")
def reminders_due(limit: int = Query(20, ge=1, le=100), _: None = Depends(require_whatsapp_service),
                  db: Session = Depends(get_db)):
    now = utcnow()
    jobs = db.scalars(select(ReminderJob).where(
        ReminderJob.due_at <= now, ReminderJob.attempts < 5,
        or_(ReminderJob.status == "pending",
            (ReminderJob.status == "claimed") & (ReminderJob.claimed_at < now - timedelta(minutes=5))))
        .order_by(ReminderJob.due_at).limit(limit).with_for_update(skip_locked=True)).all()
    result = []
    for job in jobs:
        appointment = db.get(Appointment, job.appointment_id)
        if not appointment or appointment.status != "confirmed" or not appointment.consent_to_reminders:
            job.status = "cancelled"
            continue
        doctor = db.get(Doctor, appointment.reservation.doctor_id)
        branch = db.get(Branch, appointment.reservation.branch_id)
        job.status = "claimed"
        job.claimed_at = now
        job.attempts += 1
        result.append({"id": job.id, "sender_id": job.sender_id,
                       "confirmation_code": appointment.confirmation_code,
                       "doctor_name": doctor.name if doctor else "your doctor",
                       "starts_at": _utc(appointment.reservation.starts_at),
                       "timezone": branch.timezone if branch else "Asia/Kolkata"})
    db.commit()
    return result


@router.post("/reminders/{job_id}/complete")
def reminder_complete(job_id: str, body: ReminderComplete, _: None = Depends(require_whatsapp_service),
                      db: Session = Depends(get_db)):
    job = db.get(ReminderJob, job_id)
    if not job:
        raise DomainError("REMINDER_NOT_FOUND", "Reminder was not found.", 404)
    if job.status in {"sent", "cancelled"}:
        return {"id": job.id, "status": job.status}
    if job.status != "claimed":
        raise DomainError("REMINDER_NOT_CLAIMED", "Reminder is not claimed.", 409)
    if body.status == "sent":
        job.status = "sent"
    else:
        job.status = "failed" if job.attempts >= 5 else "pending"
        job.due_at = utcnow() + timedelta(minutes=5)
        job.last_error = body.error
    db.commit()
    return {"id": job.id, "status": job.status}
