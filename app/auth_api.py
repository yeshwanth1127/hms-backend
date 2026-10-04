from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Actor, clear_session_cookie, create_session, current_actor, set_session_cookie, token_hash, verify_password
from .config import settings
from .db import get_db
from .models import Hospital, HospitalMembership, Patient, User, UserSession
from .services import DomainError

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class PatientCodeLoginRequest(BaseModel):
    patient_code: str = Field(min_length=8, max_length=24)
    access_code: str = Field(min_length=8, max_length=200)


def actor_payload(db: Session, actor: Actor) -> dict:
    hospital = db.get(Hospital, actor.hospital_id)
    return {"user_id": actor.user_id, "membership_id": actor.membership_id,
            "hospital_id": actor.hospital_id, "hospital_name": hospital.name if hospital else "",
            "role": actor.role, "display_name": actor.display_name, "patient_id": actor.patient_id}


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise DomainError("INVALID_CREDENTIALS", "The email or password is incorrect.", 401)
    memberships = db.scalars(select(HospitalMembership).where(
        HospitalMembership.user_id == user.id, HospitalMembership.status == "active")).all()
    if len(memberships) != 1:
        raise DomainError("MEMBERSHIP_SELECTION_REQUIRED", "A hospital membership must be selected.", 409)
    raw, session = create_session(db, user, memberships[0])
    set_session_cookie(response, raw)
    patient_id = db.scalar(select(Patient.id).where(Patient.hospital_id == memberships[0].hospital_id,
                                                     Patient.user_id == user.id))
    actor = Actor(user.id, memberships[0].id, memberships[0].hospital_id, memberships[0].role,
                  user.display_name, patient_id, session.id)
    return actor_payload(db, actor)


@router.post("/patient-code-login")
def patient_code_login(body: PatientCodeLoginRequest, response: Response, db: Session = Depends(get_db)):
    patient = db.scalar(select(Patient).where(
        Patient.patient_code == body.patient_code.upper().strip()))
    if (not patient or not patient.user_id or not patient.access_code_hash
            or not verify_password(body.access_code, patient.access_code_hash)):
        raise DomainError("INVALID_CREDENTIALS", "The patient code or access code is incorrect.", 401)
    user = db.get(User, patient.user_id)
    membership = db.scalar(select(HospitalMembership).where(
        HospitalMembership.hospital_id == patient.hospital_id,
        HospitalMembership.user_id == patient.user_id,
        HospitalMembership.role == "patient",
        HospitalMembership.status == "active",
    ))
    if not user or not user.is_active or not membership:
        raise DomainError("ACCESS_REVOKED", "This patient account is not active.", 403)
    raw, session = create_session(db, user, membership)
    set_session_cookie(response, raw)
    return actor_payload(db, Actor(user.id, membership.id, patient.hospital_id, "patient",
                                   user.display_name, patient.id, session.id))


@router.get("/me")
def me(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return actor_payload(db, actor)


@router.post("/logout", status_code=204)
def logout(response: Response, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    session = db.get(UserSession, actor.session_id) if actor.session_id else None
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    clear_session_cookie(response)
