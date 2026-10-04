import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Actor
from .config import settings
from .jitsi import mint_join_grant
from .models import (Appointment, Doctor, Hospital, OutboxEvent, Teleconsultation,
                     TeleconsultationConsent, TeleconsultationEvent)
from .services import DomainError


def ensure_for_appointment(db: Session, appointment: Appointment) -> Teleconsultation | None:
    if appointment.reservation.consultation_type != "virtual" or not appointment.hospital_id:
        return None
    existing = db.scalar(select(Teleconsultation).where(Teleconsultation.appointment_id == appointment.id))
    if existing:
        return existing
    item = Teleconsultation(hospital_id=appointment.hospital_id, appointment_id=appointment.id,
                            room_key=f"exora-{secrets.token_urlsafe(24)}")
    db.add(item)
    db.flush()
    return item


def _appointment_for_actor(db: Session, appointment_id: str, actor: Actor, *, doctor: bool = False):
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id,
                                                       Appointment.hospital_id == actor.hospital_id))
    if not appointment:
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    if doctor:
        doctor_row = db.scalar(select(Doctor).where(Doctor.user_id == actor.user_id,
                                                     Doctor.hospital_id == actor.hospital_id))
        if not doctor_row or appointment.reservation.doctor_id != doctor_row.id:
            raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    elif not actor.patient_id or appointment.patient_id != actor.patient_id:
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    consultation = db.scalar(select(Teleconsultation).where(
        Teleconsultation.appointment_id == appointment.id,
        Teleconsultation.hospital_id == actor.hospital_id))
    if not consultation:
        raise DomainError("TELECONSULTATION_NOT_FOUND", "Virtual consultation was not found.", 404)
    return appointment, consultation


def active_consent(db: Session, consultation: Teleconsultation, patient_id: str) -> TeleconsultationConsent | None:
    return db.scalar(select(TeleconsultationConsent).where(
        TeleconsultationConsent.teleconsultation_id == consultation.id,
        TeleconsultationConsent.patient_id == patient_id,
        TeleconsultationConsent.document_version == settings.teleconsultation_consent_version,
        TeleconsultationConsent.withdrawn_at.is_(None)).order_by(TeleconsultationConsent.accepted_at.desc()))


def event(db: Session, consultation: Teleconsultation, actor: Actor, event_type: str,
          *, request_id: str | None = None, metadata: dict | None = None):
    db.add(TeleconsultationEvent(hospital_id=actor.hospital_id, teleconsultation_id=consultation.id,
                                event_type=event_type, actor_type=actor.role, actor_id=actor.user_id,
                                request_id=request_id, metadata_json=metadata or {}))
    db.add(OutboxEvent(event_type=f"teleconsultation.{event_type}", aggregate_id=consultation.id,
                       payload={"teleconsultation_id": consultation.id, "appointment_id": consultation.appointment_id}))


def view(db: Session, appointment_id: str, actor: Actor, *, doctor: bool = False) -> dict:
    appointment, consultation = _appointment_for_actor(db, appointment_id, actor, doctor=doctor)
    doctor_row = db.get(Doctor, appointment.reservation.doctor_id)
    consent = bool(actor.patient_id and active_consent(db, consultation, actor.patient_id))
    if doctor and appointment.patient_id:
        consent = bool(active_consent(db, consultation, appointment.patient_id))
    return {"id": consultation.id, "appointment_id": appointment.id, "status": consultation.status,
            "consent_version": settings.teleconsultation_consent_version, "consent_accepted": consent,
            "doctor": {"id": doctor_row.id, "name": doctor_row.name} if doctor_row else None,
            "patient": {"id": appointment.patient_id, "name": appointment.patient_name,
                        "phone": appointment.patient_phone} if appointment.patient_id else None,
            "starts_at": appointment.reservation.starts_at, "ends_at": appointment.reservation.ends_at,
            "appointment_status": appointment.status, "version": consultation.version,
            "clinical_capabilities": {"notes": None, "prescription": None, "investigations": None,
                                      "follow_up": None, "documents": None}}


def grant(db: Session, appointment_id: str, actor: Actor, *, doctor: bool = False) -> dict:
    appointment, consultation = _appointment_for_actor(db, appointment_id, actor, doctor=doctor)
    hospital = db.get(Hospital, actor.hospital_id)
    if not hospital or not hospital.virtual_opd_enabled or appointment.status != "confirmed":
        raise DomainError("TELECONSULTATION_UNAVAILABLE", "This consultation is not available.", 409)
    if doctor:
        if consultation.status != "in_progress":
            raise DomainError("CONSULTATION_NOT_STARTED", "Start the consultation before joining.", 409)
    else:
        if not actor.patient_id or not active_consent(db, consultation, actor.patient_id):
            raise DomainError("CONSENT_REQUIRED", "Telemedicine consent is required before joining.", 409)
        if consultation.status != "in_progress":
            raise DomainError("DOCTOR_NOT_READY", "The doctor has not started the consultation yet.", 409)
    now = datetime.now(timezone.utc)
    starts = appointment.reservation.starts_at
    ends = appointment.reservation.ends_at
    starts = starts.replace(tzinfo=timezone.utc) if starts.tzinfo is None else starts
    ends = ends.replace(tzinfo=timezone.utc) if ends.tzinfo is None else ends
    if (now < starts - timedelta(minutes=settings.teleconsultation_join_early_minutes)
            or now > ends + timedelta(minutes=settings.teleconsultation_join_late_minutes)):
        raise DomainError("OUTSIDE_JOIN_WINDOW", "The consultation is outside its join window.", 409)
    result = mint_join_grant(room=consultation.room_key, actor_id=actor.user_id,
                             display_name=actor.display_name, moderator=doctor)
    event(db, consultation, actor, "join_granted", metadata={"role": "doctor" if doctor else "patient"})
    db.commit()
    return {**result, "role": "moderator" if doctor else "participant", "display_name": actor.display_name}
