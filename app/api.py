from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Appointment, Branch, Department, Doctor, Hospital, Reservation
from .schemas import (
    AppointmentCreate, AppointmentOut, AvailabilityResponse, BranchOut, CancelRequest,
    DepartmentOut, DoctorOut, HoldCreate, HoldOut,
)
from .services import availability, cancel_appointment, confirm_appointment, create_hold
from .auth import Actor, optional_actor
from .tenant import current_hospital

router = APIRouter(prefix="/api/v1")


def require_public_booking_pilot(actor: Actor | None = Depends(optional_actor)) -> Actor | None:
    if settings.app_env == "production" and (not actor or actor.role != "patient"):
        from .services import DomainError
        raise DomainError("PATIENT_AUTH_REQUIRED", "Sign in with a patient account to book.", 403)
    return actor


@router.get("/branches", response_model=list[BranchOut])
def branches(hospital: Hospital = Depends(current_hospital), db: Session = Depends(get_db)):
    return db.scalars(select(Branch).where(Branch.hospital_id == hospital.id,
                                           Branch.is_active.is_(True)).order_by(Branch.name)).all()


@router.get("/departments", response_model=list[DepartmentOut])
def departments(hospital: Hospital = Depends(current_hospital), db: Session = Depends(get_db)):
    return db.scalars(select(Department).where(Department.hospital_id == hospital.id,
                                               Department.is_active.is_(True)).order_by(Department.name)).all()


@router.get("/doctors", response_model=list[DoctorOut])
def doctors(department: str | None = None, branch: str | None = None,
            hospital: Hospital = Depends(current_hospital), db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.hospital_id == hospital.id,
                                            Doctor.is_active.is_(True)).order_by(Doctor.name)).unique().all()
    if department:
        items = [item for item in items if any(d.slug == department or d.id == department for d in item.departments)]
    if branch:
        items = [item for item in items if any(b.slug == branch or b.id == branch for b in item.branches)]
    return items


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
def doctor(doctor_id: str, hospital: Hospital = Depends(current_hospital), db: Session = Depends(get_db)):
    item = db.scalar(select(Doctor).where(Doctor.hospital_id == hospital.id,
                                          (Doctor.id == doctor_id) | (Doctor.slug == doctor_id)))
    if not item:
        from .services import DomainError
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    return item


@router.get("/availability", response_model=AvailabilityResponse)
def get_availability(doctor_id: str, branch_id: str, start_date: date,
                     end_date: date, consultation_type: str = Query("in_person", pattern="^(in_person|virtual)$"),
                     hospital: Hospital = Depends(current_hospital),
                     db: Session = Depends(get_db)):
    if not db.scalar(select(Doctor.id).where(Doctor.id == doctor_id, Doctor.hospital_id == hospital.id)):
        from .services import DomainError
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    slots, timezone_name = availability(db, doctor_id, branch_id, start_date, end_date, consultation_type)
    return AvailabilityResponse(slots=slots, timezone=timezone_name)


@router.post("/slot-holds", response_model=HoldOut, status_code=201)
def hold_create(body: HoldCreate, _: None = Depends(require_public_booking_pilot),
                hospital: Hospital = Depends(current_hospital), db: Session = Depends(get_db)):
    if not db.scalar(select(Doctor.id).where(Doctor.id == body.doctor_id, Doctor.hospital_id == hospital.id)):
        from .services import DomainError
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    return create_hold(db, body)


@router.get("/slot-holds/{hold_id}", response_model=HoldOut)
def hold_get(hold_id: str, owner_key: str, _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    hold = db.get(Reservation, hold_id)
    if not hold or hold.owner_key != owner_key:
        from .services import DomainError
        raise DomainError("HOLD_NOT_FOUND", "The slot hold was not found.", 404)
    return hold


@router.delete("/slot-holds/{hold_id}", status_code=204)
def hold_release(hold_id: str, owner_key: str, _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    hold = db.get(Reservation, hold_id)
    if hold and hold.owner_key == owner_key and hold.status == "active":
        hold.status = "released"
        db.commit()


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def appointment_create(body: AppointmentCreate, _: None = Depends(require_public_booking_pilot),
                       hospital: Hospital = Depends(current_hospital),
                       actor: Actor | None = Depends(optional_actor), db: Session = Depends(get_db)):
    item = confirm_appointment(db, body)
    if item.hospital_id != hospital.id:
        from .services import DomainError
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    if actor and actor.role == "patient" and actor.patient_id:
        if item.hospital_id != actor.hospital_id:
            from .services import DomainError
            raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
        item.patient_id = actor.patient_id
        db.commit(); db.refresh(item)
    return item


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def appointment_get(appointment_id: str, owner_key: str = Header(alias="X-Owner-Key"),
                    actor: Actor | None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    item = db.get(Appointment, appointment_id)
    allowed = bool(item and item.reservation.owner_key == owner_key)
    if settings.app_env == "production":
        allowed = bool(item and actor and actor.role == "patient" and actor.patient_id == item.patient_id
                       and actor.hospital_id == item.hospital_id)
    if not allowed:
        from .services import DomainError
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    return item


@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def appointment_cancel(appointment_id: str, body: CancelRequest,
                       owner_key: str = Header(alias="X-Owner-Key"),
                       actor: Actor | None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    item = db.get(Appointment, appointment_id)
    allowed = bool(item and item.reservation.owner_key == owner_key)
    if settings.app_env == "production":
        allowed = bool(item and actor and actor.role == "patient" and actor.patient_id == item.patient_id
                       and actor.hospital_id == item.hospital_id)
    if not allowed:
        from .services import DomainError
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    return cancel_appointment(db, item, body.actor_id, body.reason)
