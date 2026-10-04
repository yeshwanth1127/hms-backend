from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Actor, require_roles
from .config import settings
from .db import get_db
from .models import Appointment, Branch, Doctor, Teleconsultation, TeleconsultationConsent
from .services import DomainError
from .teleconsultation_service import _appointment_for_actor, active_consent, event, grant, view

router = APIRouter(prefix="/api/v1", tags=["virtual-opd"])


class ConsentRequest(BaseModel):
    document_version: str
    accepted: bool


class EndRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=240)


@router.get("/me/appointments")
def my_appointments(consultation_type: str | None = None,
                    actor: Actor = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    statement = select(Appointment).where(Appointment.hospital_id == actor.hospital_id,
                                           Appointment.patient_id == actor.patient_id)
    items = db.scalars(statement.order_by(Appointment.created_at.desc())).all()
    if consultation_type:
        items = [item for item in items if item.reservation.consultation_type == consultation_type]
    return [{"id": item.id, "confirmation_code": item.confirmation_code, "status": item.status,
             "consultation_type": item.reservation.consultation_type,
             "starts_at": item.reservation.starts_at, "ends_at": item.reservation.ends_at} for item in items]


@router.get("/me/appointments/{appointment_id}/teleconsultation")
def patient_view(appointment_id: str, actor: Actor = Depends(require_roles("patient")),
                 db: Session = Depends(get_db)):
    return view(db, appointment_id, actor)


@router.post("/me/appointments/{appointment_id}/teleconsultation/consent", status_code=201)
def consent(appointment_id: str, body: ConsentRequest, request: Request,
            actor: Actor = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    _, consultation = _appointment_for_actor(db, appointment_id, actor)
    if not body.accepted or body.document_version != settings.teleconsultation_consent_version:
        raise DomainError("CONSENT_VERSION_INVALID", "Accept the current telemedicine consent to continue.", 422)
    existing = active_consent(db, consultation, actor.patient_id or "")
    if not existing:
        db.add(TeleconsultationConsent(hospital_id=actor.hospital_id, teleconsultation_id=consultation.id,
                                       patient_id=actor.patient_id, document_version=body.document_version,
                                       captured_by_actor_type="patient", captured_by_actor_id=actor.user_id))
        event(db, consultation, actor, "consent_accepted", request_id=request.state.request_id,
              metadata={"document_version": body.document_version})
        db.commit()
    return view(db, appointment_id, actor)


@router.post("/me/appointments/{appointment_id}/teleconsultation/check-in")
def check_in(appointment_id: str, request: Request, actor: Actor = Depends(require_roles("patient")),
             db: Session = Depends(get_db)):
    _, consultation = _appointment_for_actor(db, appointment_id, actor)
    if not actor.patient_id or not active_consent(db, consultation, actor.patient_id):
        raise DomainError("CONSENT_REQUIRED", "Telemedicine consent is required before check-in.", 409)
    if consultation.status == "scheduled":
        consultation.status = "waiting"; consultation.version += 1
        consultation.last_activity_at = datetime.now(timezone.utc)
        event(db, consultation, actor, "patient_checked_in", request_id=request.state.request_id)
        db.commit()
    return view(db, appointment_id, actor)


@router.post("/me/appointments/{appointment_id}/teleconsultation/join-grant")
def patient_grant(appointment_id: str, actor: Actor = Depends(require_roles("patient")),
                  db: Session = Depends(get_db)):
    return grant(db, appointment_id, actor)


@router.get("/doctor/appointments")
def doctor_appointments(actor: Actor = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == actor.user_id, Doctor.hospital_id == actor.hospital_id))
    if not doctor:
        return []
    items = db.scalars(select(Appointment).where(Appointment.hospital_id == actor.hospital_id)).all()
    return [view(db, item.id, actor, doctor=True) for item in items
            if item.reservation.doctor_id == doctor.id and item.reservation.consultation_type == "virtual"]


@router.get("/doctor/dashboard/appointments")
def doctor_dashboard_appointments(actor: Actor = Depends(require_roles("doctor")),
                                  db: Session = Depends(get_db)):
    """Return the doctor's complete HMS worklist, including clinic and virtual visits."""
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == actor.user_id,
                                            Doctor.hospital_id == actor.hospital_id))
    if not doctor:
        return []
    items = db.scalars(select(Appointment).where(
        Appointment.hospital_id == actor.hospital_id).order_by(Appointment.created_at.desc())).all()
    result = []
    for item in items:
        reservation = item.reservation
        if reservation.doctor_id != doctor.id:
            continue
        branch = db.get(Branch, reservation.branch_id)
        consultation = db.scalar(select(Teleconsultation).where(
            Teleconsultation.appointment_id == item.id)) if reservation.consultation_type == "virtual" else None
        result.append({
            "id": item.id,
            "confirmation_code": item.confirmation_code,
            "patient_name": item.patient_name,
            "patient_phone": item.patient_phone,
            "patient_email": item.patient_email,
            "reason": item.reason,
            "status": item.status,
            "origin_channel": item.origin_channel,
            "consultation_type": reservation.consultation_type,
            "starts_at": reservation.starts_at,
            "ends_at": reservation.ends_at,
            "branch": ({"id": branch.id, "name": branch.name, "area": branch.area}
                       if branch else None),
            "teleconsultation_status": consultation.status if consultation else None,
        })
    return result


@router.get("/doctor/appointments/{appointment_id}/teleconsultation")
def doctor_view(appointment_id: str, actor: Actor = Depends(require_roles("doctor")),
                db: Session = Depends(get_db)):
    return view(db, appointment_id, actor, doctor=True)


@router.post("/doctor/appointments/{appointment_id}/teleconsultation/start")
def start(appointment_id: str, request: Request, actor: Actor = Depends(require_roles("doctor")),
          db: Session = Depends(get_db)):
    _, consultation = _appointment_for_actor(db, appointment_id, actor, doctor=True)
    if consultation.status not in {"scheduled", "waiting", "ready", "in_progress"}:
        raise DomainError("INVALID_STATUS_TRANSITION", "This consultation cannot be started.", 409)
    if consultation.status != "in_progress":
        now = datetime.now(timezone.utc)
        consultation.status = "in_progress"; consultation.doctor_started_at = now
        consultation.started_at = now; consultation.version += 1
        event(db, consultation, actor, "started", request_id=request.state.request_id)
        db.commit()
    return view(db, appointment_id, actor, doctor=True)


@router.post("/doctor/appointments/{appointment_id}/teleconsultation/join-grant")
def doctor_grant(appointment_id: str, actor: Actor = Depends(require_roles("doctor")),
                 db: Session = Depends(get_db)):
    return grant(db, appointment_id, actor, doctor=True)


@router.post("/doctor/appointments/{appointment_id}/teleconsultation/end")
def end(appointment_id: str, body: EndRequest, request: Request,
        actor: Actor = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    appointment, consultation = _appointment_for_actor(db, appointment_id, actor, doctor=True)
    if consultation.status not in {"in_progress", "completed"}:
        raise DomainError("INVALID_STATUS_TRANSITION", "This consultation is not in progress.", 409)
    if consultation.status != "completed":
        consultation.status = "completed"; consultation.ended_at = datetime.now(timezone.utc)
        consultation.ended_by_actor_type = "doctor"; consultation.ended_by_actor_id = actor.user_id
        consultation.end_reason = body.reason; consultation.version += 1
        appointment.status = "completed"
        event(db, consultation, actor, "completed", request_id=request.state.request_id)
        db.commit()
    return view(db, appointment_id, actor, doctor=True)
